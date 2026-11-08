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

from .i18n import LANGUAGES, current_language, install_argparse, resolve_language, set_language, t
from .config import APP_NAME, APP_TITLE, APP_VERSION, MODES, load_settings, user_rules_path
from .core.encoding import decode_bytes
from .core.files import FileRun, RunError
from .core import profiles
from .core.models import CATEGORIES, GROUPS, PERSONAL_CATEGORIES, group_label
from .core.pipeline import Sanitizer, load_default_ruleset
from .core.rules import load_ruleset, load_user_rules, merge_user_rules, slow_pattern_warnings
from .config import default_rules_path

EXIT_OK = 0
EXIT_FILE_ERRORS = 1
EXIT_USAGE = 2
EXIT_FOUND = 3   # --check: mindestens ein Treffer


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog=f"python -m {APP_NAME}",
        description=t("cli.description", app=APP_TITLE),
        epilog=t("cli.hint"),
    )
    p.add_argument("inputs", nargs="*", metavar=t("cli.meta.path"), help=t("cli.help.inputs"))
    p.add_argument("-o", "--output", metavar=t("cli.meta.folder"), help=t("cli.help.output"))
    p.add_argument("-m", "--mode", choices=MODES, help=t("cli.help.mode"))
    p.add_argument("--no-personal", action="store_true", help=t("cli.help.no_personal"))
    p.add_argument("--disable", metavar=t("cli.meta.cats"), default="", help=t("cli.help.disable"))
    p.add_argument("--enable", metavar=t("cli.meta.cats"), default="", help=t("cli.help.enable"))
    p.add_argument("--config", metavar=t("cli.meta.file"), help=t("cli.help.config"))
    p.add_argument("--rules", metavar=t("cli.meta.file"), help=t("cli.help.rules"))
    p.add_argument("--no-user-rules", action="store_true", help=t("cli.help.no_user_rules"))
    p.add_argument("--profile", metavar=t("cli.meta.profile"), help=t("cli.help.profile"))
    p.add_argument("--export-profile", metavar=t("cli.meta.file"), help=t("cli.help.export_profile"))
    p.add_argument("--with-wordlists", action="store_true", help=t("cli.help.with_wordlists"))
    p.add_argument("--output-encoding", metavar=t("cli.meta.encoding"), help=t("cli.help.output_encoding"))
    p.add_argument("--exclude", metavar=t("cli.meta.pattern"), action="append", default=[],
                   help=t("cli.help.exclude"))
    p.add_argument("--sanitize-filenames", action="store_true", help=t("cli.help.sanitize_filenames"))
    p.add_argument("--no-office", action="store_true", help=t("cli.help.no_office"))
    p.add_argument("--keep-office-media", action="store_true", help=t("cli.help.keep_office_media"))
    p.add_argument("--no-pdf", action="store_true", help=t("cli.help.no_pdf"))
    p.add_argument("--no-archives", action="store_true", help=t("cli.help.no_archives"))
    p.add_argument("--workers", type=int, metavar="N", help=t("cli.help.workers"))
    p.add_argument("--no-exclude", action="store_true", help=t("cli.help.no_exclude"))
    p.add_argument("-y", "--yes", action="store_true", help=t("cli.help.yes"))
    p.add_argument("--no-report", action="store_true", help=t("cli.help.no_report"))
    p.add_argument("--clean", action="store_true", help=t("cli.help.clean"))
    p.add_argument("--check", action="store_true", help=t("cli.help.check", code=EXIT_FOUND))
    p.add_argument("-q", "--quiet", action="store_true", help=t("cli.help.quiet"))
    p.add_argument("--list-categories", action="store_true", help=t("cli.help.list_categories"))
    p.add_argument("--gui", action="store_true", help=t("cli.help.gui"))
    p.add_argument("--lang", choices=LANGUAGES, metavar="{de,en}", help=t("cli.help.lang"))
    p.add_argument("--version", action="version", version=f"{APP_TITLE} {APP_VERSION}")
    return p


class _PreParseError(Exception):
    pass


def _raise_preparse_error(message: str):
    raise _PreParseError(message)


def _preparse_lang(argv) -> tuple[str | None, str | None]:
    """Liest --lang und --config vorab (ohne Fehlermeldung), damit der eigentliche Parser
    schon in der richtigen Sprache gebaut wird."""
    pre = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    pre.add_argument("--lang")
    pre.add_argument("--config")
    pre.error = _raise_preparse_error   # type: ignore[method-assign]
    try:
        known, _rest = pre.parse_known_args(argv)
    except _PreParseError:
        return None, None
    return known.lang, known.config


def _split_categories(value: str, parser) -> list[str]:
    cats = [c.strip().upper() for c in value.split(",") if c.strip()]
    unknown = [c for c in cats if c not in CATEGORIES]
    if unknown:
        parser.error(t("cli.unknown_categories", cats=", ".join(unknown)))
    return cats


def _err(msg: str) -> None:
    print(msg, file=sys.stderr)


def list_categories() -> None:
    for group in GROUPS:
        print(f"{group_label(group)}:")
        for cat in CATEGORIES.values():
            if cat.group == group:
                print(f"  {cat.id:<14} {cat.description}")


def _load_profile_arg(value: str, parser):
    """--profile: Pfad zu einer Datei oder Name eines gespeicherten Profils."""
    try:
        path = Path(value)
        if path.suffix.lower() == ".json" or path.exists():
            return profiles.load_profile(path)
        return profiles.load_named_profile(value)
    except profiles.ProfileError as exc:
        parser.error(f"--profile: {exc}")


def make_sanitizer_from_args(args, parser) -> Sanitizer:
    settings = load_settings(Path(args.config) if args.config else None)
    profile = _load_profile_arg(args.profile, parser) if args.profile else None
    if profile and profile.settings:
        settings.mode = profile.settings.get("mode", settings.mode)
        settings.enabled_categories = {**settings.enabled_categories,
                                       **profile.settings.get("enabled_categories", {})}
    if args.mode:
        settings.mode = args.mode
    if args.output_encoding:
        try:
            "".encode(args.output_encoding)
        except LookupError:
            parser.error(t("cli.unknown_encoding"))
        settings.output_encoding = args.output_encoding
    if args.sanitize_filenames:
        settings.sanitize_filenames = True
    if args.no_archives:
        settings.process_archives = False
    if args.no_office:
        settings.process_office = False
    if args.no_pdf:
        settings.process_pdf = False
    if args.keep_office_media:
        settings.office_remove_media = False
    if args.workers is not None:
        if args.workers < 1:
            parser.error(t("cli.workers_min"))
        settings.workers = args.workers
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
    elif profile is not None:
        ruleset = merge_user_rules(load_ruleset(default_rules_path()), profile.rules)
        ruleset.errors = list(ruleset.errors) + list(profile.warnings)
    elif args.rules:
        ruleset = load_ruleset(default_rules_path())
        merge_user_rules(ruleset, load_user_rules(Path(args.rules)))
    else:
        ruleset = load_ruleset(default_rules_path(), user_rules_path())
    for error in ruleset.errors + slow_pattern_warnings(ruleset):
        _err(t("cli.warning", msg=error))
    return Sanitizer(settings, ruleset)


def _format_counts(counts: dict) -> str:
    return ", ".join(f"{k}={v}" for k, v in sorted(counts.items())) or t("cli.no_hits")


def run_stdin(sanitizer: Sanitizer, quiet: bool, check: bool = False) -> int:
    data = sys.stdin.buffer.read()
    try:
        text, _ = decode_bytes(data)
    except ValueError:
        _err(t("cli.error", msg=t("cli.binary_stdin")))
        return EXIT_USAGE
    result = sanitizer.sanitize(text)
    if check:
        counts = result.counts_by_category()
        if counts and not quiet:
            print(f"-: {_format_counts(counts)}")
        return EXIT_FOUND if counts else EXIT_OK
    sys.stdout.buffer.write(result.text.encode("utf-8"))
    sys.stdout.buffer.flush()
    if not quiet:
        _err(t("cli.replaced", counts=_format_counts(result.counts_by_category())))
        _err(t("cli.hint"))
    return EXIT_OK


def run_paths(sanitizer: Sanitizer, args) -> int:
    def confirm_large(rel: str, size_mb: float) -> bool:
        if args.yes:
            return True
        if not sys.stdin.isatty():
            _err(t("cli.skipped_large", size=f"{size_mb:.0f}", rel=rel))
            return False
        answer = input(t("cli.confirm_large", rel=rel, size=f"{size_mb:.0f}"))
        return answer.strip().lower() in ("j", "ja", "y", "yes")

    def progress(done: int, total: int, rel: str) -> None:
        if not args.quiet and not args.check and rel:
            _err(f"[{done * 100 // max(total, 1):3d} %] {rel}")

    exit_code = EXIT_OK
    found = 0
    inputs = [Path(p) for p in args.inputs]
    for path in inputs:
        if not path.exists():
            _err(t("cli.error", msg=t("cli.input_not_found", name=path.name)))
            exit_code = EXIT_USAGE
            continue
        output = args.output
        if output and len(inputs) > 1:
            output = str(Path(output) / (path.resolve().name or "input"))
        try:
            report, out_root = FileRun(sanitizer, confirm_large=confirm_large, progress=progress).run(
                path, output_dir=output, write_report=not args.no_report, clean_output=args.clean,
                dry_run=args.check)
        except RunError as exc:
            _err(t("cli.error", msg=exc))
            exit_code = EXIT_USAGE
            continue
        if args.check:
            prefix = path.as_posix() if path.is_dir() else ""
            for entry in report.entries:
                if entry.total:
                    found += 1
                    if not args.quiet:
                        name = f"{prefix}/{entry.rel_path}" if prefix else path.as_posix()
                        print(f"{name}: {_format_counts(entry.counts)}")
                elif entry.status == "failed" and not args.quiet:
                    _err(t("cli.error", msg=f"{entry.rel_path}: {entry.reason}"))
        elif not args.quiet:
            _err("")
            _err(report.to_text().rstrip())
            _err(t("cli.output_line", path=out_root))
        if report.by_status("failed") and exit_code == EXIT_OK:
            exit_code = EXIT_FILE_ERRORS
    if args.check:
        if not args.quiet:
            _err(t("cli.found_files", n=found) if found else t("cli.none_found"))
        if found and exit_code == EXIT_OK:
            exit_code = EXIT_FOUND
    return exit_code


def export_profile_cmd(args) -> int:
    user_rules = load_user_rules(Path(args.rules) if args.rules else user_rules_path())
    if user_rules.errors:
        for error in user_rules.errors:
            _err(t("cli.warning", msg=error))
    settings = load_settings(Path(args.config) if args.config else None)
    path = Path(args.export_profile)
    try:
        profiles.export_profile(path, user_rules, path.stem, settings, include_wordlists=args.with_wordlists)
    except OSError as exc:
        _err(t("cli.error", msg=t("cli.profile_write_failed", name=type(exc).__name__)))
        return EXIT_USAGE
    if not args.quiet:
        _err(t("cli.profile_exported", path=path,
               wordlists=t("cli.with_wordlists" if args.with_wordlists else "cli.without_wordlists")))
    return EXIT_OK


def main(argv=None) -> int:
    # Sprache zuerst festlegen (--lang > Umgebungsvariable > config.json > System), dann erst
    # den Parser bauen. Die Wahl bleibt aktiv, wenn danach die GUI startet.
    cli_lang, cli_config = _preparse_lang(argv)
    settings = load_settings(Path(cli_config) if cli_config else None)
    set_language(resolve_language(cli_lang, settings.language))
    install_argparse()
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.list_categories:
        list_categories()
        return EXIT_OK
    if args.export_profile:
        return export_profile_cmd(args)
    if args.gui or not args.inputs:
        from .gui import launch
        return launch(current_language())
    sanitizer = make_sanitizer_from_args(args, parser)
    if args.inputs == ["-"]:
        return run_stdin(sanitizer, args.quiet, args.check)
    if "-" in args.inputs:
        parser.error(t("cli.stdin_combo"))
    return run_paths(sanitizer, args)
