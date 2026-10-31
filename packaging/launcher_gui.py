"""Einstieg für die GUI-.exe (PyInstaller)."""

import multiprocessing
import sys

from secret_sanitizer.gui import launch

if __name__ == "__main__":
    # Worker-Prozesse für mehrere CPU-Kerne: in der .exe startet jeder Worker die
    # .exe neu; freeze_support() erkennt das und führt nur den Worker aus
    # (sonst öffnete jeder Worker ein neues Fenster).
    multiprocessing.freeze_support()
    sys.exit(launch())
