"""Archive (.zip, .tar, .tar.gz/.tgz, .gz): entpacken, damit die enthaltenen
Textdateien wie normale Dateien bereinigt werden, und danach wieder einpacken.

Sicherheit:
  - Pfade im Archiv werden geprüft ("../", Laufwerksbuchstaben): nichts wird
    außerhalb des Temp-Ordners entpackt ("Zip Slip").
  - Limits gegen "Zip-Bomben": Größe je Eintrag (max_file_size_mb), Größe des
    ganzen Archivs (max_archive_mb) und Anzahl der Einträge (max_files_per_run).
  - Nur normale Dateien; Links, Geräte usw. werden übersprungen.
  - Beim Einpacken werden keine Benutzer-/Gruppennamen und beim .gz kein
    Original-Dateiname in die Kopfdaten geschrieben.
Meldungen enthalten nie Dateiinhalte.
"""

from __future__ import annotations

import gzip
import shutil
import tarfile
import zipfile
from pathlib import Path

from ..i18n import t

COPY_BLOCK = 1024 * 1024


class ArchiveError(Exception):
    """Archiv kann nicht (vollständig) verarbeitet werden. Meldung ohne Inhalte."""


def archive_kind(name: str) -> str | None:
    """'zip', 'tar', 'tgz', 'gz' oder None (kein unterstütztes Archiv)."""
    lower = name.lower()
    if lower.endswith((".tar.gz", ".tgz")):
        return "tgz"
    if lower.endswith(".tar"):
        return "tar"
    if lower.endswith(".zip"):
        return "zip"
    if lower.endswith(".gz"):
        return "gz"
    return None


def safe_member_name(name: str) -> str | None:
    """Relativer, ungefährlicher Pfad eines Archiv-Eintrags oder None."""
    parts = [p for p in name.replace("\\", "/").split("/") if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts) or ":" in parts[0]:
        return None
    return "/".join(parts)


def _gz_member_name(archive_name: str) -> str:
    base = Path(archive_name).name
    return base[:-3] if base.lower().endswith(".gz") and len(base) > 3 else base + ".txt"


class _Budget:
    def __init__(self, max_member: int, max_total: int, max_members: int) -> None:
        self.max_member = max_member
        self.max_total = max_total
        self.max_members = max_members
        self.total = 0
        self.members = 0

    def take(self, declared: int) -> None:
        self.members += 1
        if self.members > self.max_members:
            raise ArchiveError(t("archive.too_many_entries"))
        self.total += max(0, declared)
        if self.total > self.max_total:
            raise ArchiveError(t("archive.too_large"))


def _copy_limited(fin, target: Path, limit: int) -> bool:
    """Kopiert höchstens limit Bytes. False, wenn der Eintrag größer ist
    (z. B. falsche Größenangabe im Archiv); die Teildatei wird dann gelöscht."""
    written = 0
    with open(target, "wb") as fout:
        while True:
            block = fin.read(COPY_BLOCK)
            if not block:
                return True
            written += len(block)
            if written > limit:
                break
            fout.write(block)
    target.unlink()
    return False


def extract(src: Path, kind: str, target: Path, max_member: int, max_total: int,
            max_members: int) -> tuple[list[tuple[str, Path]], list[tuple[str, str]]]:
    """Entpackt ein Archiv nach target.

    Rückgabe: (entpackte Einträge [(relativer Name, Pfad)],
               übersprungene Einträge [(relativer Name, Grund)])."""
    target.mkdir(parents=True, exist_ok=True)
    budget = _Budget(max_member, max_total, max_members)
    extracted: list[tuple[str, Path]] = []
    skipped: list[tuple[str, str]] = []

    def place(name: str) -> Path:
        path = target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    try:
        if kind == "zip":
            with zipfile.ZipFile(src) as zf:
                for info in zf.infolist():
                    if info.is_dir():
                        continue
                    name = safe_member_name(info.filename)
                    if name is None:
                        skipped.append((info.filename.replace("\\", "/"), t("archive.unsafe_path")))
                        continue
                    if info.flag_bits & 0x1:
                        skipped.append((name, t("archive.encrypted")))
                        continue
                    if info.file_size > max_member:
                        skipped.append((name, t("archive.member_too_large")))
                        continue
                    budget.take(info.file_size)
                    with zf.open(info) as fin:
                        if _copy_limited(fin, place(name), max_member):
                            extracted.append((name, target / name))
                        else:
                            skipped.append((name, t("archive.member_too_large")))
        elif kind in ("tar", "tgz"):
            with tarfile.open(src, "r:*") as tf:
                for member in tf:
                    if member.isdir():
                        continue
                    name = safe_member_name(member.name)
                    if name is None:
                        skipped.append((member.name, t("archive.unsafe_path")))
                        continue
                    if not member.isfile():
                        skipped.append((name, t("archive.not_regular")))
                        continue
                    if member.size > max_member:
                        skipped.append((name, t("archive.member_too_large")))
                        continue
                    budget.take(member.size)
                    fin = tf.extractfile(member)
                    if fin is None:
                        skipped.append((name, t("archive.unreadable_member")))
                        continue
                    with fin:
                        if _copy_limited(fin, place(name), max_member):
                            extracted.append((name, target / name))
                        else:
                            skipped.append((name, t("archive.member_too_large")))
        elif kind == "gz":
            name = _gz_member_name(src.name)
            budget.take(0)
            with gzip.open(src, "rb") as fin:
                if _copy_limited(fin, place(name), min(max_member, max_total)):
                    extracted.append((name, target / name))
                else:
                    skipped.append((name, t("archive.member_too_large")))
        else:  # pragma: no cover
            raise ArchiveError(t("archive.unknown_type"))
    except ArchiveError:
        raise
    except (zipfile.BadZipFile, tarfile.TarError, gzip.BadGzipFile, EOFError) as exc:
        raise ArchiveError(t("archive.corrupt", name=type(exc).__name__)) from None
    except RuntimeError as exc:  # z. B. zipfile: "File is encrypted"
        raise ArchiveError(t("archive.unreadable", name=type(exc).__name__)) from None
    return extracted, skipped


def _tar_filter(info: tarfile.TarInfo) -> tarfile.TarInfo:
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    return info


def pack(kind: str, folder: Path, dest: Path) -> None:
    """Packt alle Dateien unter folder in ein Archiv dest (vom Typ kind).
    Schreibt erst in eine temporäre Datei neben dest."""
    files = sorted(p for p in folder.rglob("*") if p.is_file())
    tmp = dest.with_name(dest.name + ".tmp_pack")
    try:
        if kind == "zip":
            with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                for path in files:
                    zf.write(path, path.relative_to(folder).as_posix())
        elif kind in ("tar", "tgz"):
            with tarfile.open(tmp, "w:gz" if kind == "tgz" else "w") as tf:
                for path in files:
                    tf.add(path, arcname=path.relative_to(folder).as_posix(), filter=_tar_filter)
        elif kind == "gz":
            with open(tmp, "wb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as gz:
                for path in files[:1]:
                    with open(path, "rb") as fin:
                        shutil.copyfileobj(fin, gz, COPY_BLOCK)
        else:  # pragma: no cover
            raise ArchiveError(t("archive.unknown_type"))
        shutil.rmtree(folder)
        tmp.replace(dest)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
