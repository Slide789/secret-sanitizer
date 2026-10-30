"""Einstieg für die Kommandozeilen-.exe (PyInstaller)."""

import sys

from secret_sanitizer.cli import main

if __name__ == "__main__":
    sys.exit(main())
