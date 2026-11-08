"""GUI (customtkinter). Wird nur geladen, wenn die GUI gestartet wird, damit
Kern und CLI ohne Zusatzpakete laufen."""

from __future__ import annotations


def launch(lang: str | None = None) -> int:
    """lang: bereits gewählte Sprache (z. B. aus --lang); ohne Angabe wählt die GUI selbst."""
    try:
        import customtkinter  # noqa: F401
    except ImportError:
        import sys

        from ..i18n import t
        print(t("cli.gui_missing"), file=sys.stderr)
        return 2
    from .app import run

    return run(lang)
