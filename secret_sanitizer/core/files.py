"""Datei- und Ordnerlauf: Binär-Erkennung, Limits, blockweise Verarbeitung, Bericht.

Ablauf eines Laufs (eine Datei oder ein ganzer Ordner):
  Durchlauf 1 ("lernen"): alle Dateien lesen, Treffer erkennen, Werte ins
      Mapping eintragen. So bekommt derselbe Wert in allen Dateien denselben
      Platzhalter, und auch Stellen VOR dem ersten Auftreten werden ersetzt.
  Durchlauf 2 ("schreiben"): alle Dateien erneut lesen, ersetzen und in den
      Ausgabeordner schreiben (gleiche Unterordnerstruktur).

Große Dateien werden blockweise gelesen. Blöcke werden an Zeilenenden
geschnitten und mit Überlappung analysiert; ein Treffer, der über die
Schnittstelle reicht (z. B. ein PEM-Block), verschiebt den Schnitt nach hinten.

Sicherheit:
  - Originale werden nie verändert (nur gelesen).
  - Ausgabeordner darf nicht der Eingabeordner oder ein übergeordneter Ordner sein.
  - Bericht und Fehlermeldungen enthalten nur relative Pfade, Zähler und
    allgemeine Fehlerarten, niemals Dateiinhalte oder Ausnahmetexte.
"""

from __future__ import annotations

import datetime as _dt
import fnmatch
import json
import os
import re
import shutil
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator

from ..config import APP_NAME, Settings
from .encoding import SAMPLE_SIZE, detect_encoding, dominant_newline, output_encoding_for, restore_newlines
from . import merger
from .replacer import apply_replacements

REPORT_NAME = f"{APP_NAME}_bericht.txt"
MAX_SAMPLES = 12

STATUS_LABELS = {"processed": "bearbeitet", "skipped": "übersprungen", "failed": "fehlgeschlagen"}


class RunError(Exception):
    """Fehler, der den ganzen Lauf verhindert (z. B. Limit überschritten).
    Die Meldung enthält keine Dateiinhalte."""


@dataclass
class FileEntry:
    rel_path: str
    status: str = "processed"
    reason: str = ""
    encoding: str = ""
    size_bytes: int = 0
    counts: dict = field(default_factory=dict)

    @property
    def total(self) -> int:
        return sum(self.counts.values())


@dataclass
class Report:
    input_name: str
    started: str = ""
    finished: str = ""
    mode: str = ""
    entries: list = field(default_factory=list)
    aborted: str = ""
    # Per Ausschlussmuster übersprungene Ordner ("name/") und Dateien
    excluded: list = field(default_factory=list)
    # Dateien im Ausgabeordner, die nicht aus diesem Lauf stammen (frühere Läufe)
    stale: list = field(default_factory=list)
    cleaned: bool = False
    # Stichproben bereinigter Zeilen, nur für die Anzeige (nicht im Berichts-File)
    samples: list = field(default_factory=list)

    def by_status(self, status: str) -> list:
        return [e for e in self.entries if e.status == status]

    def totals(self) -> dict:
        totals: dict = {}
        for e in self.entries:
            for cat, n in e.counts.items():
                totals[cat] = totals.get(cat, 0) + n
        return dict(sorted(totals.items()))

    def to_text(self) -> str:
        lines = [
            f"Bericht {APP_NAME}",
            f"Eingabe: {self.input_name}",
            f"Modus: {self.mode}",
            f"Start: {self.started}   Ende: {self.finished}",
            "",
            f"Bearbeitet: {len(self.by_status('processed'))}   "
            f"Übersprungen: {len(self.by_status('skipped'))}   "
            f"Fehlgeschlagen: {len(self.by_status('failed'))}",
        ]
        if self.excluded:
            lines.append(f"Ausgeschlossen (Ausschlussmuster): {len(self.excluded)}")
        if self.cleaned:
            lines.append("Ausgabeordner wurde vor dem Lauf geleert.")
        if self.stale:
            lines.append(f"WARNUNG: {len(self.stale)} Datei(en) im Ausgabeordner stammen aus einem früheren Lauf "
                         "(andere Platzhalter-Nummerierung möglich).")
        if self.aborted:
            lines.append(f"ABGEBROCHEN: {self.aborted}")
        totals = self.totals()
        if totals:
            lines.append("Ersetzungen gesamt: " + ", ".join(f"{k}={v}" for k, v in totals.items()))
        for status in ("processed", "skipped", "failed"):
            entries = self.by_status(status)
            if not entries:
                continue
            lines += ["", f"--- {STATUS_LABELS[status]} ---"]
            for e in entries:
                detail = e.reason or (", ".join(f"{k}={v}" for k, v in sorted(e.counts.items())) or "keine Treffer")
                lines.append(f"{e.rel_path}  [{e.encoding or '-'}]  {detail}")
        if self.excluded:
            lines += ["", "--- ausgeschlossen (Ausschlussmuster) ---"] + list(self.excluded)
        if self.stale:
            lines += ["", "--- veraltet (nicht aus diesem Lauf, mit 'Ausgabeordner leeren' entfernen) ---"]
            lines += list(self.stale)
        lines += ["", "Hinweis: Das Ergebnis vor dem Senden selbst prüfen. Die Erkennung senkt das Risiko,",
                  "bietet aber keine 100-%-Garantie."]
        return "\n".join(lines) + "\n"

    def to_dict(self) -> dict:
        return {
            "input": self.input_name, "mode": self.mode, "started": self.started, "finished": self.finished,
            "aborted": self.aborted, "totals": self.totals(), "excluded": list(self.excluded),
            "stale": list(self.stale), "cleaned": self.cleaned,
            "files": [{"path": e.rel_path, "status": e.status, "reason": e.reason, "encoding": e.encoding,
                       "size_bytes": e.size_bytes, "counts": e.counts} for e in self.entries],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


def _now() -> str:
    return _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def safe_reason(exc: BaseException) -> str:
    """Allgemeine Fehlerbeschreibung OHNE str(exc) (könnte Inhalte enthalten)."""
    name = type(exc).__name__
    if isinstance(exc, PermissionError):
        return "keine Berechtigung"
    if isinstance(exc, FileNotFoundError):
        return "Datei nicht gefunden"
    if isinstance(exc, UnicodeError):
        return f"Kodierungsfehler ({name})"
    if isinstance(exc, MemoryError):
        return "zu wenig Arbeitsspeicher"
    if isinstance(exc, OSError):
        return f"Lese-/Schreibfehler ({name})"
    return f"interner Fehler ({name})"


# ----------------------------------------------------------------------
# Pfade
# ----------------------------------------------------------------------

def default_output_dir(input_path: Path) -> Path:
    """<eingabeordner>_sanitized neben dem Eingabeordner.
    Bei einer einzelnen Datei ist der Eingabeordner der Ordner der Datei."""
    input_path = Path(input_path).resolve()
    folder = input_path if input_path.is_dir() else input_path.parent
    if folder.parent == folder:  # Laufwerkswurzel wie C:\
        return folder / f"{APP_NAME}_sanitized"
    return folder.parent / f"{folder.name}_sanitized"


def resolve_output_dir(input_path: Path, settings: Settings, output_dir: str | Path | None = None) -> Path:
    chosen = output_dir or settings.output_dir
    out = Path(chosen).expanduser().resolve() if chosen else default_output_dir(input_path)
    input_path = Path(input_path).resolve()
    in_folder = input_path if input_path.is_dir() else input_path.parent
    if out == in_folder or out in in_folder.parents:
        raise RunError("Der Ausgabeordner darf nicht der Eingabeordner oder ein übergeordneter Ordner sein.")
    return out


def _is_within(path: Path, folder: Path) -> bool:
    try:
        path.relative_to(folder)
        return True
    except ValueError:
        return False


def is_excluded(rel_path: str, patterns) -> bool:
    """True, wenn Name oder relativer Pfad auf ein Ausschlussmuster passt
    (fnmatch, ohne Groß-/Kleinschreibung)."""
    rel = rel_path.lower()
    name = rel.rsplit("/", 1)[-1]
    return any(fnmatch.fnmatchcase(name, p) or fnmatch.fnmatchcase(rel, p) for p in (p.lower() for p in patterns))


def collect_files(input_path: Path, out_root: Path, exclude=(), skipped: list | None = None) -> list[tuple[Path, str]]:
    """(Quelldatei, relativer Pfad) für eine Datei oder alle Dateien eines Ordners.
    exclude: Ausschlussmuster (gelten nur für Ordnerläufe; eine einzeln gewählte
    Datei wird immer verarbeitet). Übersprungene relative Pfade landen in skipped."""
    input_path = Path(input_path).resolve()
    if input_path.is_file():
        return [(input_path, input_path.name)]
    if not input_path.is_dir():
        raise RunError("Eingabe nicht gefunden.")
    skipped = skipped if skipped is not None else []
    result = []
    for dirpath, dirnames, filenames in os.walk(input_path, followlinks=False):
        current = Path(dirpath)
        kept_dirs = []
        for d in sorted(dirnames):
            path = current / d
            # Ausgabeordner (falls innerhalb der Eingabe) nicht erneut verarbeiten
            if _is_within(path.resolve(), out_root) or path.is_symlink():
                continue
            rel = path.relative_to(input_path).as_posix()
            if exclude and is_excluded(rel, exclude):
                skipped.append(rel + "/")
                continue
            kept_dirs.append(d)
        dirnames[:] = kept_dirs
        for name in sorted(filenames):
            path = current / name
            if path.is_symlink() or not path.is_file():
                continue
            rel = path.relative_to(input_path).as_posix()
            if exclude and is_excluded(rel, exclude):
                skipped.append(rel)
                continue
            result.append((path, rel))
    return result


# ----------------------------------------------------------------------
# Lesen in Blöcken
# ----------------------------------------------------------------------

def sniff(path: Path) -> str | None:
    with open(path, "rb") as fh:
        return detect_encoding(fh.read(SAMPLE_SIZE))


def read_chunks(path: Path, encoding: str, chunk_size: int) -> Iterator[str]:
    """Liest Text blockweise; \\r\\n wird zu \\n (auch über Blockgrenzen)."""
    with open(path, "r", encoding=encoding, newline="") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                return
            if chunk.endswith("\r"):
                chunk += fh.read(1)
            yield chunk.replace("\r\n", "\n")


def file_newline(path: Path, encoding: str) -> str:
    with open(path, "r", encoding=encoding, newline="") as fh:
        return dominant_newline(fh.read(SAMPLE_SIZE))


def _choose_cut(buffer: str, chunk_size: int) -> int:
    idx = buffer.rfind("\n", 0, chunk_size)
    return idx + 1 if idx > 0 else chunk_size


def iter_segments(chunks: Iterator[str], chunk_size: int, overlap: int,
                  handler: Callable[[str, int], int], cancel: threading.Event | None = None) -> None:
    """Ruft handler(buffer, cut) für jeden Abschnitt auf. Der Handler
    verarbeitet buffer[:cut] (mit buffer[cut:] als Vorschau) und gibt den
    tatsächlich verwendeten Schnitt zurück (>= cut)."""
    buffer = ""
    for chunk in chunks:
        if cancel is not None and cancel.is_set():
            raise _Cancelled()
        buffer += chunk
        while len(buffer) >= chunk_size + overlap:
            cut = handler(buffer, _choose_cut(buffer, chunk_size))
            buffer = buffer[cut:]
    if buffer:
        handler(buffer, len(buffer))


class _Cancelled(Exception):
    pass


# ----------------------------------------------------------------------
# Lauf
# ----------------------------------------------------------------------

class FileRun:
    """Ein Lauf über eine Datei oder einen Ordner mit einem gemeinsamen Mapping."""

    def __init__(self, sanitizer, settings: Settings | None = None,
                 confirm_large: Callable[[str, float], bool] | None = None,
                 progress: Callable[[int, int, str], None] | None = None,
                 cancel: threading.Event | None = None, exclude=()) -> None:
        self.sanitizer = sanitizer
        self.settings = settings or sanitizer.settings
        self.confirm_large = confirm_large
        self.progress = progress
        self.cancel = cancel or threading.Event()
        self.exclude = tuple(exclude)

    def _report_progress(self, done: int, total: int, rel: str) -> None:
        if self.progress:
            self.progress(done, total, rel)

    def run(self, input_path, output_dir=None, write_report: bool = True,
            clean_output: bool = False, dry_run: bool = False) -> tuple[Report, Path]:
        """clean_output: Ausgabeordner vor dem Schreiben leeren (nur wenn er leer
        ist oder von einem früheren Lauf stammt, siehe clear_output_dir).
        dry_run: nur prüfen und zählen, nichts schreiben (auch keinen Bericht)."""
        input_path = Path(input_path)
        out_root = resolve_output_dir(input_path, self.settings, output_dir)
        report = Report(input_name=input_path.resolve().name or str(input_path), started=_now(),
                        mode=self.settings.mode)
        if dry_run:
            write_report = clean_output = False
        if clean_output:
            check_clearable(out_root)
        files = collect_files(input_path, out_root, self.settings.exclude_patterns, report.excluded)
        if len(files) > self.settings.max_files_per_run:
            raise RunError(f"Zu viele Dateien ({len(files)}), Limit max_files_per_run = "
                           f"{self.settings.max_files_per_run}.")
        limit = self.settings.max_file_size_mb * 1024 * 1024
        total = len(files)

        # --- Vorprüfung + Durchlauf 1 (lernen) ---
        todo: list[tuple[Path, str, FileEntry]] = []
        for i, (src, rel) in enumerate(files):
            if self.cancel.is_set():
                report.aborted = "vom Benutzer abgebrochen"
                break
            self._report_progress(i, total * 2, rel)
            entry = FileEntry(rel)
            report.entries.append(entry)
            try:
                entry.size_bytes = src.stat().st_size
                encoding = sniff(src)
                if encoding is None:
                    entry.status, entry.reason = "skipped", "Binärdatei"
                    continue
                entry.encoding = encoding
                if entry.size_bytes > limit:
                    size_mb = entry.size_bytes / 1024 / 1024
                    if not (self.confirm_large and self.confirm_large(rel, size_mb)):
                        entry.status = "skipped"
                        entry.reason = f"größer als {self.settings.max_file_size_mb:g} MB (max_file_size_mb)"
                        continue
                entry.encoding = self._learn_file(src, encoding)
                todo.append((src, rel, entry))
            except _Cancelled:
                report.aborted = "vom Benutzer abgebrochen"
                entry.status, entry.reason = "skipped", "abgebrochen"
                break
            except Exception as exc:  # noqa: BLE001 - jeder Fehler wird ohne Inhalt berichtet
                entry.status, entry.reason = "failed", safe_reason(exc)

        # Zielnamen (bei sanitize_filenames bereinigt; das Mapping kennt jetzt alle Werte)
        dest_rels = self._dest_names(report) if self.settings.sanitize_filenames else {}

        # --- Durchlauf 2 (ersetzen + schreiben) ---
        written: set = set()     # geschriebene Zielpfade (relativ)
        done: set = set()        # fertig bearbeitete Quellpfade (relativ)
        if not report.aborted and clean_output:
            clear_output_dir(out_root)
            report.cleaned = True
        if not report.aborted:
            for i, (src, rel, entry) in enumerate(todo):
                if self.cancel.is_set():
                    report.aborted = "vom Benutzer abgebrochen"
                    break
                self._report_progress(total + i, total * 2, rel)
                try:
                    dest_rel = dest_rels.get(rel, rel)
                    if dry_run:
                        entry.counts = self._process_file(src, entry.encoding, report, None)
                    else:
                        entry.counts = self._write_file(src, out_root / dest_rel, entry.encoding, report)
                    written.add(dest_rel)
                    done.add(rel)
                except _Cancelled:
                    report.aborted = "vom Benutzer abgebrochen"
                    entry.status, entry.reason = "skipped", "abgebrochen"
                    break
                except Exception as exc:  # noqa: BLE001
                    entry.status, entry.reason = "failed", safe_reason(exc)
        if report.aborted:
            for _, rel, entry in todo:
                if entry.status == "processed" and rel not in done:
                    entry.status, entry.reason = "skipped", "abgebrochen"
        self._report_progress(total * 2, total * 2, "")
        if self.settings.sanitize_filenames:
            # Im Bericht nur die bereinigten Namen
            for entry in report.entries:
                entry.rel_path = dest_rels.get(entry.rel_path, entry.rel_path)
            report.excluded = [self._sanitize_rel(x) for x in report.excluded]
        if not dry_run:
            report.stale = find_stale(out_root, written)
        report.finished = _now()
        if write_report:
            out_root.mkdir(parents=True, exist_ok=True)
            _write_text_atomic(out_root / REPORT_NAME, report.to_text(), "utf-8", "\n")
        return report, out_root

    # ------------------------------------------------------------------
    def _sanitize_rel(self, rel: str) -> str:
        trailing = "/" if rel.endswith("/") else ""
        parts = [sanitize_path_part(self.sanitizer, part, self.exclude) for part in rel.rstrip("/").split("/")]
        return "/".join(parts) + trailing

    def _dest_names(self, report: Report) -> dict:
        """Relativer Quellpfad -> bereinigter Zielpfad, ohne Kollisionen."""
        names: dict = {}
        used: set = {REPORT_NAME.lower()}
        for entry in report.entries:
            dest = self._sanitize_rel(entry.rel_path)
            if dest.lower() in used:
                folder, _, name = dest.rpartition("/")
                stem, dot, suffix = name.rpartition(".") if "." in name.lstrip(".") else (name, "", "")
                n = 2
                while True:
                    candidate = f"{stem} ({n}){dot}{suffix}"
                    candidate = f"{folder}/{candidate}" if folder else candidate
                    if candidate.lower() not in used:
                        dest = candidate
                        break
                    n += 1
            used.add(dest.lower())
            names[entry.rel_path] = dest
        return names

    def _learn_file(self, src: Path, encoding: str) -> str:
        """Durchlauf 1. Gibt die tatsächlich verwendete Kodierung zurück
        (Wechsel auf cp1252, falls UTF-8 erst spät im File ungültig wird)."""
        s = self.settings

        def handler(buffer: str, cut: int) -> int:
            findings = self.sanitizer.learn(buffer, self.exclude)
            ends = [f.end for f in findings if f.start < cut]
            return max([cut] + ends)

        for enc in _encoding_candidates(encoding):
            try:
                iter_segments(read_chunks(src, enc, s.chunk_size), s.chunk_size, s.chunk_overlap, handler, self.cancel)
                return enc
            except UnicodeDecodeError:
                continue
        raise UnicodeError("keine passende Kodierung")

    def _write_file(self, src: Path, dest: Path, encoding: str, report: Report) -> dict:
        s = self.settings
        if dest.resolve() == src.resolve():
            raise RunError("Ausgabe würde Original überschreiben")  # pragma: no cover (durch resolve_output_dir verhindert)
        out_encoding = output_encoding_for(encoding, s.output_encoding)
        dest.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".tmp_", dir=str(dest.parent))
        try:
            with os.fdopen(fd, "w", encoding=out_encoding, newline="") as out:
                counts = self._process_file(src, encoding, report, out)
            os.replace(tmp, dest)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        return counts

    def _process_file(self, src: Path, encoding: str, report: Report, out) -> dict:
        """Durchlauf 2 für eine Datei: ersetzen, zählen und (wenn out gesetzt
        ist) bereinigt schreiben. Gibt die Ersetzungen je Kategorie zurück."""
        s = self.settings
        newline = file_newline(src, encoding)
        counts: dict = {}

        def handler(buffer: str, cut: int) -> int:
            findings = self.sanitizer.analyze(buffer, self.exclude)
            keep = [f for f in findings if f.start < cut]
            cut = max([cut] + [f.end for f in keep])
            result = apply_replacements(buffer[:cut], keep, self.sanitizer.mapping)
            for rep in result.replacements:
                counts[rep.category] = counts.get(rep.category, 0) + 1
            _collect_samples(result, report)
            if out is not None:
                out.write(restore_newlines(result.text, newline))
            return cut

        iter_segments(read_chunks(src, encoding, s.chunk_size), s.chunk_size, s.chunk_overlap, handler, self.cancel)
        return counts


def check_clearable(out_root: Path) -> None:
    """Darf der Ausgabeordner geleert werden? Nur wenn er fehlt, leer ist oder
    einen Bericht dieses Programms enthält (also von einem früheren Lauf stammt).
    So wird nie ein fremder Ordner gelöscht, der versehentlich gewählt wurde."""
    if not out_root.exists():
        return
    if not out_root.is_dir():
        raise RunError("Der Ausgabeordner ist eine Datei.")
    if any(out_root.iterdir()) and not (out_root / REPORT_NAME).is_file():
        raise RunError("Der Ausgabeordner wird nicht geleert: Er ist nicht leer und enthält keinen Bericht "
                       f"({REPORT_NAME}) eines früheren Laufs. Bitte einen anderen Ordner wählen.")


def clear_output_dir(out_root: Path) -> None:
    check_clearable(out_root)
    if not out_root.exists():
        return
    for child in out_root.iterdir():
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()


def find_stale(out_root: Path, written: set) -> list[str]:
    """Dateien im Ausgabeordner, die dieser Lauf nicht geschrieben hat."""
    if not out_root.is_dir():
        return []
    stale = []
    for path in sorted(out_root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(out_root).as_posix()
        if rel == REPORT_NAME or rel in written or path.name.startswith(".tmp_"):
            continue
        stale.append(rel)
    return stale


_INVALID_NAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize_path_part(sanitizer, part: str, exclude=()) -> str:
    """Bereinigt einen Datei- oder Ordnernamen mit dem Mapping der Sitzung.
    Zeichen, die unter Windows in Namen verboten sind, werden zu "_".

    In Dateinamen ist "_" meist ein Trenner (backup_db01.firma.local.log),
    für reguläre Ausdrücke aber ein Wortzeichen. Darum wird zusätzlich eine
    Variante mit Leerzeichen statt "_" geprüft (gleiche Länge, gleiche
    Positionen); der bessere Treffer gewinnt."""
    findings = sanitizer.analyze(part, exclude)
    if "_" in part:
        findings = merger.resolve_overlaps(findings + sanitizer.analyze(part.replace("_", " "), exclude))
    if not findings:
        return part
    cleaned = apply_replacements(part, findings, sanitizer.mapping).text
    cleaned = _INVALID_NAME_CHARS.sub("_", cleaned).rstrip(" .")
    return cleaned or "_"


def _encoding_candidates(encoding: str) -> list[str]:
    out = [encoding]
    for fb in ("cp1252", "latin-1"):
        if fb not in out:
            out.append(fb)
    return out


def _collect_samples(result, report: Report) -> None:
    if len(report.samples) >= MAX_SAMPLES or not result.replacements:
        return
    lines = result.text.split("\n")
    for rep in result.replacements:
        if len(report.samples) >= MAX_SAMPLES:
            break
        line_no = result.text.count("\n", 0, rep.out_start)
        line = lines[line_no]
        sample = line if len(line) <= 200 else line[:200] + " …"
        if sample not in report.samples:
            report.samples.append(sample)


def _write_text_atomic(path: Path, text: str, encoding: str, newline: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp_", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="") as fh:
            fh.write(restore_newlines(text, newline))
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ----------------------------------------------------------------------
# Einzeldatei für die Vorschau (GUI)
# ----------------------------------------------------------------------

@dataclass
class LoadedText:
    text: str          # mit \n-Zeilenenden
    encoding: str
    newline: str
    size_bytes: int


def load_text_file(path: Path) -> LoadedText:
    """Liest eine (kleine) Textdatei komplett für die Vorschau.
    Wirft RunError bei Binärdateien (Meldung ohne Inhalt)."""
    path = Path(path)
    data = path.read_bytes()
    encoding = detect_encoding(data[:SAMPLE_SIZE])
    if encoding is None:
        raise RunError("Binärdatei, wird nicht verarbeitet.")
    for enc in _encoding_candidates(encoding):
        try:
            raw = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    newline = dominant_newline(raw)
    return LoadedText(raw.replace("\r\n", "\n"), enc, newline, len(data))


def save_sanitized_text(src: Path, sanitized_text: str, loaded: LoadedText, settings: Settings,
                        output_dir=None, name: str | None = None) -> Path:
    """Speichert einen in der Vorschau bereinigten Text in den Ausgabeordner.
    name: Dateiname im Ausgabeordner (Standard: wie das Original)."""
    src = Path(src).resolve()
    out_root = resolve_output_dir(src, settings, output_dir)
    dest = out_root / (name or src.name)
    if dest.resolve() == src:
        raise RunError("Ausgabe würde Original überschreiben.")
    _write_text_atomic(dest, sanitized_text, output_encoding_for(loaded.encoding, settings.output_encoding),
                       loaded.newline)
    return dest
