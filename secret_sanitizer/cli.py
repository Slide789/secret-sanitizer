"""Kommandozeile (nur Standardbibliothek).

Beispiele:
    python -m secret_sanitizer logs/                 Ordner -> logs_sanitized/
    python -m secret_sanitizer app.log -o bereinigt  Datei -> bereinigt/app.log
    type log.txt | python -m secret_sanitizer -      stdin -> stdout
    python -m secret_sanitizer --mode normal --no-personal datei.txt

Ausgaben auf stderr enthalten nur Zähler und relative Pfade, nie Originalwerte.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import APP_NAME, APP_TITLE, APP_VERSION, MODES, load_settings, user_rules_path
from .core.encoding import decode_bytes
from .core.files import FileRun, RunError
from .core.models import CATEGORIES, GROUPS, PERSONAL_CATEGORIES
from .core.pipeline import Sanitizer, load_default_ruleset
from .core.rules import load_ruleset, load_user_rules, merge_user_rules
from .config import default_rules_path

EXIT_OK = 0
EXIT_FILE_ERRORS = 1
EXIT_USAGE = 2

HINWEIS = ("Hinweis: Ergebnis vor dem Senden selbst prüfen. Das Tool senkt das Risiko, "
           "bietet aber keine 100-%-Garantie. Interne Richtlinien zur KI-Nutzung beachten.")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog=f"python -m {APP_NAME}",
        description=f"{APP_TITLE}: ersetzt Passwörter, Tokens, IPs usw. durch Platzhalter wie [PASSWORD_1]. "
                    "Ohne Argumente startet die GUI.",
        epilog=HINWEIS,
    )
    p.add_argument("inputs", nargs="*", metavar="PFAD",
                   help="Datei(en) oder Ordner. '-' liest von stdin und schreibt nach stdout.")
    p.add_argument("-o", "--output", metavar="ORDNER",
                   help="Ausgabeordner (Standard: <eingabeordner>_sanitized neben der Eingabe).")
    p.add_argument("-m", "--mode", choices=MODES, help="Modus: strict (Standard), normal, loose.")
    p.add_argument("--no-personal", action="store_true",
                   help="Personenbezogene Daten (E-Mail, Namen) NICHT ersetzen.")
    p.add_argument("--disable", metavar="KAT[,KAT]", default="",
                   help="Kategorien abschalten, z. B. --disable IP,HOSTNAME.")
    p.add_argument("--enable", metavar="KAT[,KAT]", default="",
                   help="Kategorien einschalten (überschreibt die Config).")
    p.add_argument("--config", metavar="DATEI", help="Andere config.json verwenden.")
    p.add_argument("--rules", metavar="DATEI", help="Andere user_rules.json verwenden.")
    p.add_argument("--no-user-rules", action="store_true", help="Nur mitgelieferte Regeln verwenden.")
    p.add_argument("--output-encoding", metavar="KODIERUNG",
                   help="Kodierung der Ausgabedateien (Standard utf-8, 'same' = wie Eingabe).")
    p.add_argument("--exclude", metavar="MUSTER", action="append", default=[],
                   help="Ordner/Dateien im Ordnerlauf überspringen, z. B. --exclude \"*.bak\" (mehrfach möglich, "
                        "zusätzlich zu den Standardmustern wie .git, node_modules).")
    p.add_argument("--no-exclude", action="store_true",
                   help="Keine Ausschlussmuster verwenden (auch nicht die Standardmuster).")
    p.add_argument("-y", "--yes", action="store_true",
                   help="Große Dateien ohne Rückfrage verarbeiten.")
    p.add_argument("--no-report", action="store_true", help="Keine Berichtsdatei in den Ausgabeordner schreiben.")
    p.add_argument("-q", "--quiet", action="store_true", help="Weniger Ausgaben auf stderr.")
    p.add_argument("--list-categories", action="store_true", help="Kategorien anzeigen und beenden.")
    p.add_argument("--gui", action="store_true", help="GUI starten.")
    p.add_argument("--version", action="version", version=f"{APP_TITLE} {APP_VERSION}")
    return p


def _split_categories(value: str, parser) -> list[str]:
    cats = [c.strip().upper() for c in value.split(",") if c.strip()]
    unknown = [c for c in cats if c not in CATEGORIES]
    if unknown:
        parser.error(f"Unbekannte Kategorie(n): {', '.join(unknown)} (siehe --list-categories)")
    return cats


def _err(msg: str) -> None:
    print(msg, file=sys.stderr)


def list_categories() -> None:
    for group, label in GROUPS.items():
        print(f"{label}:")
        for cat in CATEGORIES.values():
            if cat.group == group:
                print(f"  {cat.id:<14} {cat.description}")


def make_sanitizer_from_args(args, parser) -> Sanitizer:
    settings = load_settings(Path(args.config) if args.config else None)
    if args.mode:
        settings.mode = args.mode
    if args.output_encoding:
        try:
            "".encode(args.output_encoding)
        except LookupError:
            parser.error("Unbekannte Kodierung für --output-encoding")
        settings.output_encoding = args.output_encoding
    if args.no_exclude:
        settings.exclude_patterns = []
    settings.exclude_patterns = settings.exclude_patterns + [p for p in args.exclude if p.strip()]
    cats = dict(settings.enabled_categories)
    if args.no_personal:
        for c in PERSONAL_CATEGORIES:
            cats[c] = False
    for c in _split_categories(args.disable, parser):
        cats[c] = False
    for c in _split_categories(args.enable, parser):
        cats[c] = True
    settings.enabled_categories = cats

    if args.no_user_rules:
        ruleset = load_default_ruleset(include_user_rules=False)
    elif args.rules:
        ruleset = load_ruleset(default_rules_path())
        merge_user_rules(ruleset, load_user_rules(Path(args.rules)))
    else:
        ruleset = load_ruleset(default_rules_path(), user_rules_path())
    for error in ruleset.errors:
        _err(f"Warnung: {error}")
    return Sanitizer(settings, ruleset)


def _format_counts(counts: dict) -> str:
    return ", ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "keine Treffer"


def run_stdin(sanitizer: Sanitizer, quiet: bool) -> int:
    data = sys.stdin.buffer.read()
    try:
        text, _ = decode_bytes(data)
    except ValueError:
        _err("Fehler: Eingabe ist keine Textdatei (Binärdaten).")
        return EXIT_USAGE
    result = sanitizer.sanitize(text)
    sys.stdout.buffer.write(result.text.encode("utf-8"))
    sys.stdout.buffer.flush()
    if not quiet:
        _err(f"Ersetzt: {_format_counts(result.counts_by_category())}")
        _err(HINWEIS)
    return EXIT_OK


def run_paths(sanitizer: Sanitizer, args) -> int:
    def confirm_large(rel: str, size_mb: float) -> bool:
        if args.yes:
            return True
        if not sys.stdin.isatty():
            _err(f"Übersprungen (zu groß, {size_mb:.0f} MB): {rel}  -> mit --yes trotzdem verarbeiten")
            return False
        answer = input(f"{rel} ist {size_mb:.0f} MB groß. Trotzdem verarbeiten? [j/N] ")
        return answer.strip().lower() in ("j", "ja", "y", "yes")

    def progress(done: int, total: int, rel: str) -> None:
        if not args.quiet and rel:
            _err(f"[{done * 100 // max(total, 1):3d} %] {rel}")

    exit_code = EXIT_OK
    inputs = [Path(p) for p in args.inputs]
    for path in inputs:
        if not path.exists():
            _err(f"Fehler: Eingabe nicht gefunden: {path.name}")
            exit_code = EXIT_USAGE
            continue
        output = args.output
        if output and len(inputs) > 1:
            output = str(Path(output) / (path.resolve().name or "eingabe"))
        try:
            report, out_root = FileRun(sanitizer, confirm_large=confirm_large, progress=progress).run(
                path, output_dir=output, write_report=not args.no_report)
        except RunError as exc:
            _err(f"Fehler: {exc}")
            exit_code = EXIT_USAGE
            continue
        if not args.quiet:
            _err("")
            _err(report.to_text().rstrip())
            _err(f"Ausgabe: {out_root}")
        if report.by_status("failed") and exit_code == EXIT_OK:
            exit_code = EXIT_FILE_ERRORS
    return exit_code


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.list_categories:
        list_categories()
        return EXIT_OK
    if args.gui or not args.inputs:
        from .gui import launch
        return launch()
    sanitizer = make_sanitizer_from_args(args, parser)
    if args.inputs == ["-"]:
        return run_stdin(sanitizer, args.quiet)
    if "-" in args.inputs:
        parser.error("'-' (stdin) kann nicht mit Dateien kombiniert werden.")
    return run_paths(sanitizer, args)
