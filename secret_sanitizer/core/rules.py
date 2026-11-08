"""Regelformat: Laden, Prüfen und Speichern von Regeln, Wortlisten und Allowlist.

Format einer Regel (JSON):
    {
      "id": "aws_access_key",          eindeutige Kennung
      "name": "AWS Access Key",        Anzeigename
      "description": "...",            Erklärung (JSON kennt keine Kommentare)
      "category": "API_KEY",           Kategorie aus models.CATEGORIES
      "detector": "regex",             "regex" oder "cmdline"
      "pattern": "...",                regulärer Ausdruck (Python-Syntax)
      "flags": ["IGNORECASE"],         optional: IGNORECASE, MULTILINE, DOTALL
      "confidence": 0.95,              Konfidenz 0..1
      "validator": "luhn",             optional: luhn, iban, ipv4, ipv6, phone
      "hint": ["akia"],                optional: Regel nur prüfen, wenn mindestens
                                       einer dieser Texte vorkommt (Tempo)
      "enabled": true
    }
Enthält das Muster eine benannte Gruppe "value", wird nur dieser Teil ersetzt
(z. B. nur das Passwort hinter "password=").
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..i18n import has_key, t
from .models import CATEGORIES

ALLOWED_FLAGS = {"IGNORECASE": re.IGNORECASE, "MULTILINE": re.MULTILINE, "DOTALL": re.DOTALL}
ALLOWED_DETECTORS = ("regex", "cmdline")
ALLOWED_VALIDATORS = ("luhn", "iban", "ipv4", "ipv6", "phone")


class RuleError(ValueError):
    """Fehler in einer Regel. Die Meldung enthält nie Textinhalte, nur die
    Regel-ID und die Art des Fehlers."""


@dataclass
class Rule:
    id: str
    name: str
    category: str
    pattern: str
    description: str = ""
    detector: str = "regex"
    flags: list = field(default_factory=list)
    confidence: float = 0.8
    validator: str | None = None
    enabled: bool = True
    hint: list = field(default_factory=list)

    def __post_init__(self) -> None:
        self._compiled: re.Pattern | None = None
        self.hint = [str(h).lower() for h in (self.hint or []) if str(h)]

    @property
    def compiled(self) -> re.Pattern:
        if self._compiled is None:
            self._compiled = compile_pattern(self.pattern, self.flags, self.id)
        return self._compiled

    def to_dict(self) -> dict:
        data = asdict(self)
        if not data.get("validator"):
            data.pop("validator", None)
        if not data.get("flags"):
            data.pop("flags", None)
        if not data.get("hint"):
            data.pop("hint", None)
        return data


@dataclass
class Wordlist:
    id: str
    name: str
    category: str
    words: list = field(default_factory=list)
    description: str = ""
    ignore_case: bool = True
    enabled: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AllowEntry:
    """Ein Eintrag der Allowlist: wird nie ersetzt.
    regex=False: exakter Vergleich (ohne Groß-/Kleinschreibung)."""

    value: str
    regex: bool = False
    description: str = ""

    def __post_init__(self) -> None:
        self._compiled = None

    @property
    def compiled(self) -> re.Pattern:
        if self._compiled is None:
            self._compiled = compile_pattern(self.value, ["IGNORECASE"], "allowlist")
        return self._compiled

    def matches(self, candidate: str) -> bool:
        if self.regex:
            return self.compiled.fullmatch(candidate) is not None
        return candidate.casefold() == self.value.casefold()

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ContextKeywords:
    """Schlüsselwörter für die Kontext-Heuristik (key=value)."""

    category: str
    keywords: list
    confidence: float = 0.85
    description: str = ""


def compile_pattern(pattern: str, flags, rule_id: str) -> re.Pattern:
    value = 0
    for name in flags or []:
        if name not in ALLOWED_FLAGS:
            raise RuleError(t("ruleerr.unknown_flag", id=rule_id, flag=name))
        value |= ALLOWED_FLAGS[name]
    try:
        return re.compile(pattern, value)
    except re.error as exc:
        # exc.msg enthält nur die Fehlerart, nicht den untersuchten Text.
        raise RuleError(t("ruleerr.bad_regex", id=rule_id, msg=exc.msg, pos=exc.pos)) from None


def _sre_parse(pattern: str):
    try:
        from re import _parser as sre_parse   # Python 3.11+
    except ImportError:                       # pragma: no cover - Python 3.10
        import sre_parse
    return sre_parse.parse(pattern)


def _flat_items(seq):
    """Elemente einer Sequenz; Gruppen (...) werden aufgelöst."""
    for op, av in seq:
        if str(op) == "SUBPATTERN":
            yield from _flat_items(av[-1])
        else:
            yield op, av


def _is_unbounded_repeat(op, av) -> bool:
    return str(op) in ("MAX_REPEAT", "MIN_REPEAT") and av[1] > 1000


def _children(op, av):
    """Untersequenzen eines Elements (für die rekursive Suche)."""
    name = str(op)
    if name in ("MAX_REPEAT", "MIN_REPEAT", "POSSESSIVE_REPEAT"):
        return [av[2]]
    if name == "SUBPATTERN":
        return [av[-1]]
    if name == "BRANCH":
        return list(av[1])
    if name in ("ASSERT", "ASSERT_NOT", "ATOMIC_GROUP"):
        return [av[-1]]
    return []


def _risky(seq) -> bool:
    for op, av in seq:
        if _is_unbounded_repeat(op, av):
            items = list(_flat_items(av[2]))
            inner = [i for i in items if _is_unbounded_repeat(*i)]
            others_mandatory = any(
                (str(o) in ("MAX_REPEAT", "MIN_REPEAT", "POSSESSIVE_REPEAT") and a[0] >= 1
                 and not _is_unbounded_repeat(o, a))
                or str(o) in ("LITERAL", "NOT_LITERAL", "IN", "ANY", "BRANCH")
                or (_is_unbounded_repeat(o, a) and a[0] >= 1 and a is not inner[0][1])
                for o, a in items) if inner else True
            if inner and not others_mandatory:
                return True
        for child in _children(op, av):
            if _risky(child):
                return True
    return False


def redos_risk(pattern: str) -> bool:
    """True, wenn das Muster verschachtelte Wiederholungen ohne festen Trenner
    enthält, z. B. (a+)+ oder (\\w+\\s?)+. Solche Muster können bei passenden
    Texten exponentiell lange brauchen ("catastrophic backtracking") und das
    Programm einfrieren. Eine Heuristik: findet die typischen Fälle, nicht alle."""
    try:
        return _risky(_sre_parse(pattern))
    except Exception:  # noqa: BLE001 - ungültige Muster prüft compile_pattern
        return False


def slow_pattern_warnings(ruleset) -> list[str]:
    """Warnungen (ohne Textinhalte) für aktive Regeln und Allowlist-Einträge,
    die laut redos_risk sehr langsam werden können."""
    warnings = [t("ruleerr.slow_rule", id=r.id)
                for r in ruleset.rules if r.enabled and redos_risk(r.pattern)]
    warnings += [t("ruleerr.slow_allow")
                 for a in ruleset.allowlist if a.regex and redos_risk(a.value)]
    return warnings


def rule_from_dict(data: dict) -> Rule:
    if not isinstance(data, dict):
        raise RuleError(t("ruleerr.not_object"))
    rule_id = str(data.get("id") or "").strip()
    if not rule_id:
        raise RuleError(t("ruleerr.no_id"))
    category = str(data.get("category") or "CUSTOM")
    if category not in CATEGORIES:
        raise RuleError(t("ruleerr.unknown_category", id=rule_id, category=category))
    detector = str(data.get("detector") or "regex")
    if detector not in ALLOWED_DETECTORS:
        raise RuleError(t("ruleerr.unknown_detector", id=rule_id, detector=detector))
    validator = data.get("validator") or None
    if validator is not None and validator not in ALLOWED_VALIDATORS:
        raise RuleError(t("ruleerr.unknown_validator", id=rule_id, validator=validator))
    try:
        confidence = float(data.get("confidence", 0.8))
    except (TypeError, ValueError):
        raise RuleError(t("ruleerr.confidence_nan", id=rule_id)) from None
    if not 0.0 <= confidence <= 1.0:
        raise RuleError(t("ruleerr.confidence_range", id=rule_id))
    pattern = data.get("pattern")
    if not isinstance(pattern, str) or not pattern:
        raise RuleError(t("ruleerr.pattern_missing", id=rule_id))
    rule = Rule(
        id=rule_id,
        name=str(data.get("name") or rule_id),
        description=str(data.get("description") or ""),
        category=category,
        detector=detector,
        pattern=pattern,
        flags=list(data.get("flags") or []),
        confidence=confidence,
        validator=validator,
        enabled=bool(data.get("enabled", True)),
        hint=list(data.get("hint") or []),
    )
    rule.compiled  # prüft das Muster sofort
    if rule.compiled.match(""):
        raise RuleError(t("ruleerr.pattern_empty_match", id=rule_id))
    return rule


def wordlist_from_dict(data: dict) -> Wordlist:
    wl_id = str(data.get("id") or "").strip()
    if not wl_id:
        raise RuleError(t("ruleerr.wordlist_no_id"))
    category = str(data.get("category") or "CUSTOM")
    if category not in CATEGORIES:
        raise RuleError(t("ruleerr.wordlist_unknown_category", id=wl_id, category=category))
    words = [str(w).strip() for w in (data.get("words") or []) if str(w).strip()]
    return Wordlist(
        id=wl_id,
        name=str(data.get("name") or wl_id),
        description=str(data.get("description") or ""),
        category=category,
        words=words,
        ignore_case=bool(data.get("ignore_case", True)),
        enabled=bool(data.get("enabled", True)),
    )


def allow_from_dict(data) -> AllowEntry:
    if isinstance(data, str):
        return AllowEntry(value=data)
    entry = AllowEntry(value=str(data.get("value") or ""), regex=bool(data.get("regex", False)),
                       description=str(data.get("description") or ""))
    if not entry.value:
        raise RuleError(t("ruleerr.allow_no_value"))
    if entry.regex:
        compile_pattern(entry.value, [], "allowlist")
    return entry


@dataclass
class RuleSet:
    """Alle Regeln zusammen: mitgelieferte + eigene."""

    rules: list = field(default_factory=list)
    wordlists: list = field(default_factory=list)
    allowlist: list = field(default_factory=list)
    context_keywords: list = field(default_factory=list)
    context_key_excludes: list = field(default_factory=list)
    errors: list = field(default_factory=list)

    def enabled_rules(self, detector: str) -> list:
        return [r for r in self.rules if r.enabled and r.detector == detector]

    def is_allowed(self, value: str) -> bool:
        exact, matchers = self._allow_matchers()
        if value.lower() in exact:
            return True
        return any(m.fullmatch(value) is not None for m in matchers)

    def _allow_matchers(self):
        """Exakte Einträge als Menge, Regex-Einträge möglichst als ein
        kombiniertes Muster (zwischengespeichert, wird bei Änderung der
        Allowlist neu gebaut). Lassen sich die Einträge nicht kombinieren
        (z. B. "(?i)" mitten im Muster oder doppelte Gruppennamen), wird jeder
        einzeln geprüft."""
        signature = (id(self.allowlist), len(self.allowlist))
        cached = getattr(self, "_allow_cache", None)
        if cached is None or cached[0] != signature:
            exact = {a.value.lower() for a in self.allowlist if not a.regex}
            entries = [a for a in self.allowlist if a.regex]
            matchers: list = []
            if entries:
                try:
                    matchers = [re.compile("|".join(f"(?:{a.value})" for a in entries), re.IGNORECASE)]
                except re.error:
                    matchers = [a.compiled for a in entries]
            cached = (signature, exact, matchers)
            self._allow_cache = cached
        return cached[1], cached[2]


@dataclass
class UserRules:
    """Inhalt von user_rules.json (wird von der GUI verwaltet)."""

    rules: list = field(default_factory=list)
    wordlists: list = field(default_factory=list)
    allowlist: list = field(default_factory=list)
    errors: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "version": 1,
            "description": "Eigene Regeln, Wortlisten und Allowlist. Wird von der GUI verwaltet.",
            "rules": [r.to_dict() for r in self.rules],
            "wordlists": [w.to_dict() for w in self.wordlists],
            "allowlist": [a.to_dict() for a in self.allowlist],
        }


def _read_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8-sig") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise RuleError(t("ruleerr.not_json_object", name=Path(path).name))
    return data


def _parse_entries(items, parser, errors: list) -> list:
    out = []
    for item in items or []:
        try:
            out.append(parser(item))
        except RuleError as exc:
            errors.append(str(exc))
    return out


def load_user_rules(path: Path) -> UserRules:
    path = Path(path)
    if not path.exists():
        return UserRules()
    try:
        data = _read_json(path)
    except (OSError, ValueError) as exc:
        return UserRules(errors=[t("ruleerr.unreadable_file", name=path.name, error=type(exc).__name__)])
    errors: list = []
    return UserRules(
        rules=_parse_entries(data.get("rules"), rule_from_dict, errors),
        wordlists=_parse_entries(data.get("wordlists"), wordlist_from_dict, errors),
        allowlist=_parse_entries(data.get("allowlist"), allow_from_dict, errors),
        errors=errors,
    )


def save_user_rules(user_rules: UserRules, path: Path) -> None:
    from ..config import write_json_atomic

    write_json_atomic(Path(path), user_rules.to_dict())


def load_ruleset(default_path: Path, user_path: Path | None = None) -> RuleSet:
    data = _read_json(Path(default_path))
    errors: list = []
    ruleset = RuleSet(
        rules=_parse_entries(data.get("rules"), rule_from_dict, errors),
        wordlists=_parse_entries(data.get("wordlists"), wordlist_from_dict, errors),
        allowlist=_parse_entries(data.get("allowlist"), allow_from_dict, errors),
        context_keywords=[ContextKeywords(**ck) for ck in data.get("context_keywords", [])],
        context_key_excludes=list(data.get("context_key_excludes", [])),
        errors=errors,
    )
    # Anzeigetexte der mitgelieferten Regeln aus dem Sprachkatalog (vor dem Zusammenführen,
    # eigene Regeln bleiben unangetastet)
    for rule in ruleset.rules:
        if has_key(f"rule.{rule.id}.name"):
            rule.name = t(f"rule.{rule.id}.name")
        if has_key(f"rule.{rule.id}.description"):
            rule.description = t(f"rule.{rule.id}.description")
    if user_path is not None:
        user = load_user_rules(Path(user_path))
        merge_user_rules(ruleset, user)
    return ruleset


def merge_user_rules(ruleset: RuleSet, user: UserRules) -> RuleSet:
    """Hängt eigene Regeln an. Eine eigene Regel mit gleicher ID ersetzt
    die mitgelieferte (so lassen sich Standardregeln abschalten)."""
    user_ids = {r.id for r in user.rules}
    ruleset.rules = [r for r in ruleset.rules if r.id not in user_ids] + list(user.rules)
    ruleset.wordlists = list(ruleset.wordlists) + list(user.wordlists)
    ruleset.allowlist = list(ruleset.allowlist) + list(user.allowlist)
    ruleset.errors = list(ruleset.errors) + list(user.errors)
    return ruleset
