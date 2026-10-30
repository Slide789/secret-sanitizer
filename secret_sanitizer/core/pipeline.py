"""Ablauf: Eingabe -> Normalisierung -> alle Detektoren -> Zusammenführen ->
Konsistenz-Propagation -> Ersetzen.

Ein Sanitizer-Objekt entspricht einer "Sitzung": Das Mapping bleibt über
mehrere Texte/Blöcke hinweg erhalten (wichtig für große Dateien), liegt aber
nur im Arbeitsspeicher.
"""

from __future__ import annotations

from ..config import Settings, default_rules_path, load_settings, user_rules_path
from ..detectors import build_detectors
from . import merger
from .encoding import normalize_newlines, restore_newlines
from .models import DetectContext, Finding, SanitizeResult
from .replacer import PlaceholderMapping, apply_replacements, value_key
from .rules import RuleSet, load_ruleset


def load_default_ruleset(include_user_rules: bool = True) -> RuleSet:
    return load_ruleset(default_rules_path(), user_rules_path() if include_user_rules else None)


class Sanitizer:
    def __init__(self, settings: Settings | None = None, ruleset: RuleSet | None = None) -> None:
        self.settings = settings or Settings()
        self.ruleset = ruleset if ruleset is not None else load_default_ruleset(include_user_rules=False)
        self.detectors = build_detectors(self.ruleset, self.settings)
        self.mapping = PlaceholderMapping(self.settings.placeholder_style)

    @classmethod
    def from_config(cls) -> "Sanitizer":
        """Einstellungen und Regeln (inkl. eigener Regeln) aus dem Konfigurationsordner."""
        return cls(load_settings(), load_default_ruleset(include_user_rules=True))

    def reset(self) -> None:
        """Vergisst das Mapping (neue Sitzung, Nummerierung beginnt bei 1)."""
        self.mapping.clear()

    # ------------------------------------------------------------------
    def detect_raw(self, text: str) -> list[Finding]:
        """Alle Treffer aller Detektoren, ungefiltert (für Tests und Regel-Editor)."""
        ctx = DetectContext(self.settings)
        findings: list[Finding] = []
        for detector in self.detectors:
            findings.extend(detector.detect(text, ctx))
        return findings

    @staticmethod
    def _exclude_keys(exclude) -> frozenset:
        return frozenset(value_key(v) for v in (exclude or ()))

    def learn(self, text: str, exclude=()) -> list[Finding]:
        """Erkennt Treffer und trägt die Werte ins Mapping ein (ohne zu ersetzen).
        Wird bei Dateien als erster Durchlauf genutzt, damit ein Wert auch an
        Stellen ersetzt wird, die VOR seinem ersten Erkennen liegen."""
        keys = self._exclude_keys(exclude)
        primary = merger.merge(self.detect_raw(text), text, self.settings, self.ruleset, keys)
        for f in sorted(primary, key=lambda x: x.start):
            self.mapping.placeholder_for(text[f.start:f.end], f.category)
        return primary

    def analyze(self, text: str, exclude=()) -> list[Finding]:
        """Endgültige, überlappungsfreie Treffer inkl. Propagation."""
        keys = self._exclude_keys(exclude)
        prepared = merger.prepare(self.detect_raw(text), text, self.settings, self.ruleset, keys)
        for f in sorted(merger.resolve_overlaps(prepared), key=lambda x: x.start):
            self.mapping.placeholder_for(text[f.start:f.end], f.category)
        propagated = merger.prepare_propagated(self.mapping.find_propagated(text), text, self.settings,
                                               self.ruleset, keys)
        return merger.resolve_overlaps(prepared, propagated)

    def sanitize(self, text: str, exclude=()) -> SanitizeResult:
        """Bereinigt einen Text.

        exclude: Werte, die der Nutzer per "doch nicht ersetzen" ausgenommen hat.
        Bei Windows-Zeilenenden beziehen sich die Positionen im Ergebnis auf den
        Text mit \\n-Zeilenenden; der Ergebnistext hat wieder das Original-Zeilenende."""
        normalized, newline = normalize_newlines(text)
        findings = self.analyze(normalized, exclude)
        result = apply_replacements(normalized, findings, self.mapping)
        result.text = restore_newlines(result.text, newline)
        return result


def sanitize_text(text: str, settings: Settings | None = None, ruleset: RuleSet | None = None) -> str:
    """Bequeme Kurzform für einmalige Aufrufe."""
    return Sanitizer(settings, ruleset).sanitize(text).text
