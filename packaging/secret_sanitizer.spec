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


def read_constant(name):
    """Liest eine Konstante (APP_NAME, APP_TITLE, APP_VERSION) aus config.py."""
    with open(os.path.join(PKG, "config.py"), encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            return node.value.value
    raise SystemExit(f"{name} nicht gefunden")


APP_NAME = read_constant("APP_NAME")
APP_TITLE = read_constant("APP_TITLE")
APP_VERSION = read_constant("APP_VERSION")


def write_version_file(exe_name, description):
    """Windows-Versionsinfo (Eigenschaften -> Details) aus APP_VERSION."""
    numbers = [int(x) for x in APP_VERSION.split(".") if x.isdigit()][:4]
    numbers += [0] * (4 - len(numbers))
    text = f'''VSVersionInfo(
  ffi=FixedFileInfo(filevers={tuple(numbers)}, prodvers={tuple(numbers)}, mask=0x3f, flags=0x0,
                    OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040704B0', [
      StringStruct('FileDescription', {description!r}),
      StringStruct('FileVersion', {APP_VERSION!r}),
      StringStruct('InternalName', {exe_name!r}),
      StringStruct('OriginalFilename', {exe_name + ".exe"!r}),
      StringStruct('ProductName', {APP_TITLE!r}),
      StringStruct('ProductVersion', {APP_VERSION!r})])]),
    VarFileInfo([VarStruct('Translation', [0x0407, 1200])])
  ]
)
'''
    path = os.path.join(workpath, f"version_{exe_name}.txt")
    os.makedirs(workpath, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path
RULES = [(os.path.join(PKG, "rules", name), os.path.join(APP_NAME, "rules"))
         for name in ("default_rules.json", "user_rules.json")]
LOCALES = [(os.path.join(PKG, "locales", name), os.path.join(APP_NAME, "locales"))
           for name in ("de.json", "en.json")]
THEME = [(os.path.join(PKG, "gui", "theme.json"), os.path.join(APP_NAME, "gui"))]
# Nichts aus dem Netz, keine unnötigen Module
EXCLUDES = ["unittest", "pydoc", "xmlrpc", "ftplib", "smtplib", "http.server", "tests"]

gui = Analysis(
    [os.path.join(SPECPATH, "launcher_gui.py")],
    pathex=[ROOT],
    datas=RULES + LOCALES + THEME + collect_data_files("customtkinter"),
    hiddenimports=["secret_sanitizer.gui.app"],
    excludes=EXCLUDES,
    noarchive=False,
)
gui_pyz = PYZ(gui.pure)
gui_exe = EXE(
    gui_pyz, gui.scripts, gui.binaries, gui.datas, [],
    name=APP_NAME,
    version=write_version_file(APP_NAME, f"{APP_TITLE} (Oberfläche)"),
    console=False,          # GUI ohne schwarzes Konsolenfenster
    upx=False,              # UPX löst öfter Virenscanner-Fehlalarme aus
    debug=False,
    strip=False,
)

cli = Analysis(
    [os.path.join(SPECPATH, "launcher_cli.py")],
    pathex=[ROOT],
    datas=RULES + LOCALES,
    excludes=EXCLUDES + ["tkinter", "customtkinter", "_tkinter", "darkdetect", "PIL", "tkinterdnd2"],
    noarchive=False,
)
cli_pyz = PYZ(cli.pure)
cli_exe = EXE(
    cli_pyz, cli.scripts, cli.binaries, cli.datas, [],
    name=APP_NAME + "_cli",
    version=write_version_file(APP_NAME + "_cli", f"{APP_TITLE} (Kommandozeile)"),
    console=True,
    upx=False,
    debug=False,
    strip=False,
)
