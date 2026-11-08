"""Regel-Profile: eigene Regeln, Wortlisten und Allowlist (optional mit Modus
und Kategorien) als JSON-Datei speichern, weitergeben und wieder laden.

Ein Profil enthält nur Daten: keine Pfade, keine Befehle, nichts Ausführbares.
Beim Laden wird alles streng geprüft (Größe, Typkennung, Formatversion, jede
Regel und jeder reguläre Ausdruck). Wortlisten enthalten oft echte Firmen- und
Personennamen im Klartext; sie werden darum nur auf ausdrücklichen Wunsch
exportiert.
"""

from __future__ import annotations

import datetime as _dt
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from ..config import APP_NAME, MODES, config_dir, write_json_atomic
from ..i18n import t
from .models import CATEGORIES
from .rules import (RuleError, UserRules, allow_from_dict, redos_risk, rule_from_dict, wordlist_from_dict)

PROFILE_TYPE = f"{APP_NAME}_profile"
FORMAT_VERSION = 1
MAX_PROFILE_BYTES = 5 * 1024 * 1024
_NAME_RE = re.compile(r"^[\w\- .]{1,60}$")
_KNOWN_KEYS = {"type", "version", "name", "description", "created", "rules", "wordlists", "allowlist", "settings"}


class ProfileError(ValueError):
    """Profil ungültig oder nicht lesbar. Meldung ohne Inhalte der Datei."""


@dataclass
class Profile:
    name: str
    rules: UserRules
    # Nur "mode" und "enabled_categories"; None = Profil ändert die Einstellungen nicht
    settings: dict | None = None
    warnings: list = field(default_factory=list)


def profiles_dir() -> Path:
    return config_dir() / "profiles"


_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}


def valid_profile_name(name: str) -> bool:
    """Name ist als Dateiname sicher (auch unter Windows)."""
    stripped = name.strip(" .")
    return (bool(_NAME_RE.match(name)) and stripped != "" and ".." not in name
            and stripped.split(".")[0].casefold() not in _RESERVED)


def profile_path(name: str) -> Path:
    if not valid_profile_name(name):
        raise ProfileError(t("profile.invalid_name"))
    return profiles_dir() / f"{name.strip()}.json"


def list_profiles() -> list[str]:
    folder = profiles_dir()
    if not folder.is_dir():
        return []
    return sorted((p.stem for p in folder.glob("*.json") if valid_profile_name(p.stem)), key=str.casefold)


# ----------------------------------------------------------------------
# Export
# ----------------------------------------------------------------------

def profile_to_dict(user_rules: UserRules, name: str, settings=None, include_wordlists: bool = False) -> dict:
    data = {
        "type": PROFILE_TYPE,
        "version": FORMAT_VERSION,
        "name": name,
        "created": _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "rules": [r.to_dict() for r in user_rules.rules],
        "allowlist": [a.to_dict() for a in user_rules.allowlist],
    }
    if include_wordlists:
        data["wordlists"] = [w.to_dict() for w in user_rules.wordlists if w.words]
    if settings is not None:
        data["settings"] = {"mode": settings.mode, "enabled_categories": dict(settings.enabled_categories)}
    return data


def export_profile(path: Path, user_rules: UserRules, name: str, settings=None,
                   include_wordlists: bool = False) -> Path:
    write_json_atomic(Path(path), profile_to_dict(user_rules, name, settings, include_wordlists))
    return Path(path)


def save_named_profile(name: str, user_rules: UserRules, settings=None, include_wordlists: bool = True) -> Path:
    """Speichert ein Profil im Konfigurationsordner. Lokal gespeicherte Profile
    enthalten die Wortlisten (sie verlassen den Rechner nicht)."""
    return export_profile(profile_path(name), user_rules, name.strip(), settings, include_wordlists)


# ----------------------------------------------------------------------
# Import
# ----------------------------------------------------------------------

def load_profile(path: Path) -> Profile:
    """Liest und prüft ein Profil. Ungültige Einträge werden nicht übernommen,
    sondern als Warnung gemeldet; eine Datei, die kein Profil ist, wird abgelehnt."""
    path = Path(path)
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise ProfileError(t("profile.unreadable", name=type(exc).__name__)) from None
    if size > MAX_PROFILE_BYTES:
        raise ProfileError(t("profile.too_large", mb=MAX_PROFILE_BYTES // (1024 * 1024)))
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        raise ProfileError(t("profile.bad_json", name=type(exc).__name__)) from None
    if not isinstance(data, dict) or data.get("type") != PROFILE_TYPE:
        raise ProfileError(t("profile.not_a_profile"))
    version = data.get("version")
    if not isinstance(version, int) or version < 1:
        raise ProfileError(t("profile.no_version"))
    if version > FORMAT_VERSION:
        raise ProfileError(t("profile.newer_version", version=version))

    warnings: list = []
    unknown = sorted(set(data) - _KNOWN_KEYS)
    if unknown:
        warnings.append(t("profile.unknown_fields", fields=", ".join(unknown[:10])))
    for key in ("rules", "wordlists", "allowlist"):
        if key in data and not isinstance(data[key], list):
            raise ProfileError(t("profile.not_a_list", field=key))

    def parse(items, parser):
        out = []
        for item in items or []:
            try:
                out.append(parser(item))
            except (RuleError, AttributeError, TypeError) as exc:
                warnings.append(str(exc) if isinstance(exc, RuleError) else t("profile.invalid_entry"))
        return out

    rules = UserRules(rules=parse(data.get("rules"), rule_from_dict),
                      wordlists=parse(data.get("wordlists"), wordlist_from_dict),
                      allowlist=parse(data.get("allowlist"), allow_from_dict))
    for rule in rules.rules:
        if redos_risk(rule.pattern):
            warnings.append(t("ruleerr.slow_rule", id=rule.id))
    for entry in rules.allowlist:
        if entry.regex and redos_risk(entry.value):
            warnings.append(t("profile.slow_allow"))

    settings = None
    raw_settings = data.get("settings")
    if isinstance(raw_settings, dict):
        settings = {}
        if raw_settings.get("mode") in MODES:
            settings["mode"] = raw_settings["mode"]
        cats = raw_settings.get("enabled_categories")
        if isinstance(cats, dict):
            settings["enabled_categories"] = {k: bool(v) for k, v in cats.items() if k in CATEGORIES}
        settings = settings or None

    name = data.get("name") if isinstance(data.get("name"), str) else path.stem
    return Profile(name=name[:60], rules=rules, settings=settings, warnings=warnings)


def load_named_profile(name: str) -> Profile:
    return load_profile(profile_path(name))


# ----------------------------------------------------------------------
# Zusammenführen
# ----------------------------------------------------------------------

def summarize(current: UserRules, incoming: UserRules) -> dict:
    """Was ein Import ändern würde (nur Zähler, keine Inhalte)."""
    current_rules = {r.id: r.to_dict() for r in current.rules}
    new_rules = [r for r in incoming.rules if r.id not in current_rules]
    changed = [r for r in incoming.rules if r.id in current_rules and current_rules[r.id] != r.to_dict()]
    current_words = {(w.category, x.casefold()) for w in current.wordlists for x in w.words}
    new_words = {(w.category, x.casefold()) for w in incoming.wordlists for x in w.words} - current_words
    current_allow = {(a.value.casefold(), a.regex) for a in current.allowlist}
    new_allow = [a for a in incoming.allowlist if (a.value.casefold(), a.regex) not in current_allow]
    return {"new_rules": len(new_rules), "changed_rules": len(changed), "new_words": len(new_words),
            "new_allow": len(new_allow)}


def merge(current: UserRules, incoming: UserRules) -> UserRules:
    """Zusammenführen: Regeln mit gleicher ID werden durch die importierten
    ersetzt, Wortlisten (je Kategorie) und Allowlist werden vereinigt."""
    incoming_ids = {r.id for r in incoming.rules}
    rules = [r for r in current.rules if r.id not in incoming_ids] + list(incoming.rules)

    wordlists = [_copy_wordlist(w) for w in current.wordlists]
    for wl in incoming.wordlists:
        target = next((w for w in wordlists if w.category == wl.category and w.id == f"user_{wl.category.lower()}"),
                      None)
        if target is None:
            target = next((w for w in wordlists if w.id == wl.id), None)
        if target is None:
            wordlists.append(_copy_wordlist(wl))
            continue
        known = {x.casefold() for x in target.words}
        target.words += [x for x in wl.words if x.casefold() not in known]

    allowlist = list(current.allowlist)
    known_allow = {(a.value.casefold(), a.regex) for a in allowlist}
    for entry in incoming.allowlist:
        if (entry.value.casefold(), entry.regex) not in known_allow:
            allowlist.append(entry)
            known_allow.add((entry.value.casefold(), entry.regex))
    return UserRules(rules=rules, wordlists=wordlists, allowlist=allowlist)


def _copy_wordlist(wl):
    from .rules import Wordlist

    return Wordlist(id=wl.id, name=wl.name, category=wl.category, words=list(wl.words),
                    description=wl.description, ignore_case=wl.ignore_case, enabled=wl.enabled)
