"""Einstieg für die Kommandozeilen-.exe (PyInstaller)."""

import multiprocessing
import sys

from secret_sanitizer.cli import main

if __name__ == "__main__":
    # Worker-Prozesse für mehrere CPU-Kerne: in der .exe startet jeder Worker die
    # .exe neu; freeze_support() erkennt das und führt nur den Worker aus.
    multiprocessing.freeze_support()
    sys.exit(main())
