"""Einstieg: ohne Argumente GUI, mit Argumenten Kommandozeile.

    python -m secret_sanitizer            -> GUI
    python -m secret_sanitizer --help     -> Hilfe zur Kommandozeile
"""

import sys

if __package__ in (None, ""):
    # Start als Skript (z. B. PyInstaller-Einstieg): Paket importierbar machen
    import os

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from secret_sanitizer.cli import main
else:
    from .cli import main

if __name__ == "__main__":
    sys.exit(main())
