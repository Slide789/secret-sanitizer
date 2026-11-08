"""GUI (customtkinter). Wird nur geladen, wenn die GUI gestartet wird, damit
Kern und CLI ohne Zusatzpakete laufen."""


def launch() -> int:
    try:
        import customtkinter  # noqa: F401
    except ImportError:
        import sys

        from ..i18n import t
        print(t("cli.gui_missing"), file=sys.stderr)
        return 2
    from .app import run

    return run()
