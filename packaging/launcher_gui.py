"""Einstieg für die GUI-.exe (PyInstaller)."""

import sys

from secret_sanitizer.gui import launch

if __name__ == "__main__":
    sys.exit(launch())
