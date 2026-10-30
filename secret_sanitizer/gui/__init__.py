"""GUI (customtkinter). Wird nur geladen, wenn die GUI gestartet wird, damit
Kern und CLI ohne Zusatzpakete laufen."""


def launch() -> int:
    try:
        import customtkinter  # noqa: F401
    except ImportError:
        import sys

        print("Die GUI benötigt das Paket customtkinter:\n"
              "    pip install -r requirements.txt\n"
              "Die Kommandozeile funktioniert auch ohne: python -m secret_sanitizer --help",
              file=sys.stderr)
        return 2
    from .app import run

    return run()
