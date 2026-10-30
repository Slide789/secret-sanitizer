# -*- mode: python ; coding: utf-8 -*-
# PyInstaller-Build. Aufruf aus dem Projektordner:
#     pyinstaller --noconfirm --clean packaging/secret_sanitizer.spec
# Ergebnis:
#     dist/<APP_NAME>.exe       GUI (ohne Konsolenfenster)
#     dist/<APP_NAME>_cli.exe   Kommandozeile (mit Konsole, ohne GUI-Pakete)
# Der exe-Name wird aus APP_NAME in secret_sanitizer/config.py gelesen.

import ast
import os

from PyInstaller.utils.hooks import collect_data_files

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
PKG = os.path.join(ROOT, "secret_sanitizer")


def read_app_name():
    with open(os.path.join(PKG, "config.py"), encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "APP_NAME" for t in node.targets):
            return node.value.value
    raise SystemExit("APP_NAME nicht gefunden")


APP_NAME = read_app_name()
RULES = [(os.path.join(PKG, "rules", name), os.path.join(APP_NAME, "rules"))
         for name in ("default_rules.json", "user_rules.json")]
# Nichts aus dem Netz, keine unnötigen Module
EXCLUDES = ["unittest", "pydoc", "xmlrpc", "ftplib", "smtplib", "http.server", "tests"]

gui = Analysis(
    [os.path.join(SPECPATH, "launcher_gui.py")],
    pathex=[ROOT],
    datas=RULES + collect_data_files("customtkinter"),
    hiddenimports=["secret_sanitizer.gui.app"],
    excludes=EXCLUDES,
    noarchive=False,
)
gui_pyz = PYZ(gui.pure)
gui_exe = EXE(
    gui_pyz, gui.scripts, gui.binaries, gui.datas, [],
    name=APP_NAME,
    console=False,          # GUI ohne schwarzes Konsolenfenster
    upx=False,              # UPX löst öfter Virenscanner-Fehlalarme aus
    debug=False,
    strip=False,
)

cli = Analysis(
    [os.path.join(SPECPATH, "launcher_cli.py")],
    pathex=[ROOT],
    datas=RULES,
    excludes=EXCLUDES + ["tkinter", "customtkinter", "_tkinter", "darkdetect", "PIL"],
    noarchive=False,
)
cli_pyz = PYZ(cli.pure)
cli_exe = EXE(
    cli_pyz, cli.scripts, cli.binaries, cli.datas, [],
    name=APP_NAME + "_cli",
    console=True,
    upx=False,
    debug=False,
    strip=False,
)
