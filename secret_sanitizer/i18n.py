"""Übersetzungen (Deutsch/Englisch).

Die Texte stehen flach in ``locales/de.json`` und ``locales/en.json`` (Schlüssel
``bereich.element``). ``t(key)`` liefert den Text der aktiven Sprache. Ohne
Werte wird der Text unverändert zurückgegeben (so dürfen Texte wörtliche
geschweifte Klammern enthalten, z. B. ``[{CATEGORY}_{N}]``); mit Werten wird
``str.format`` angewendet.

Reihenfolge der Sprachwahl (siehe ``resolve_language``): Kommandozeile ->
Umgebungsvariable -> Einstellung -> Systemsprache.
"""

from __future__ import annotations

import json
import locale
import os
import sys
from pathlib import Path

LANGUAGES = ("de", "en")
LANG_ENV_VAR = "SECRET_SANITIZER_LANG"

# Wie rules/: relativ zum Paket, funktioniert auch in der PyInstaller-.exe.
_LOCALES_DIR = Path(__file__).parent / "locales"

_catalogs: dict[str, dict[str, str]] = {}
_language = "en"


def load_catalog(lang: str) -> dict[str, str]:
    """Lädt (und merkt sich) die Sprachdatei. Fehlt sie oder ist sie kaputt: leer."""
    if lang not in _catalogs:
        try:
            with open(_LOCALES_DIR / f"{lang}.json", "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            data = {}
        _catalogs[lang] = data if isinstance(data, dict) else {}
    return _catalogs[lang]


def t(key: str, **values) -> str:
    """Text zum Schlüssel in der aktiven Sprache; fehlt er: Englisch, sonst der Schlüssel."""
    text = load_catalog(_language).get(key)
    if not isinstance(text, str):
        text = load_catalog("en").get(key)
    if not isinstance(text, str):
        text = key
    return text.format(**values) if values else text


def has_key(key: str) -> bool:
    """Gibt es den Schlüssel in der aktiven Sprache?"""
    return isinstance(load_catalog(_language).get(key), str)


def set_language(lang: str) -> None:
    global _language
    if lang not in LANGUAGES:
        raise ValueError(f"Unbekannte Sprache: {lang!r}")
    _language = lang


def current_language() -> str:
    return _language


def _windows_ui_langid() -> int:
    """Sprachkennung der Windows-Oberfläche (wirft außerhalb von Windows)."""
    import ctypes
    return int(ctypes.windll.kernel32.GetUserDefaultUILanguage())


def detect_system_language() -> str:
    """Deutsch, wenn die Systemsprache Deutsch ist, sonst Englisch (auch bei jedem Fehler)."""
    try:
        if sys.platform.startswith("win"):
            return "de" if (_windows_ui_langid() & 0x3FF) == 0x07 else "en"
    except Exception:
        pass
    try:
        name = locale.getlocale()[0]
        if isinstance(name, str) and name.lower().startswith("de"):
            return "de"
    except Exception:
        pass
    return "en"


def resolve_language(cli: str | None, setting: str) -> str:
    """Kommandozeile -> Umgebungsvariable -> Einstellung -> Systemsprache."""
    if cli in LANGUAGES:
        return cli
    env = os.environ.get(LANG_ENV_VAR, "").strip().lower()
    if env in LANGUAGES:
        return env
    if setting in LANGUAGES:
        return setting
    return detect_system_language()


# Beim Import einmal die Startsprache setzen (Einstellung "auto").
set_language(resolve_language(None, "auto"))
