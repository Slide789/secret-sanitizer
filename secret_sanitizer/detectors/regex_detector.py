"""Regex-Detektor: bekannte Formate aus default_rules.json und eigenen Regeln.

Enthält ein Muster die benannte Gruppe "value", wird nur dieser Teil als
Treffer gemeldet. Umschließende Anführungszeichen werden entfernt.
"""

from __future__ import annotations

from ..core.models import DetectContext, Finding
from .validators import apply_validator

QUOTES = ("\"", "'", "`")


def strip_quotes(text: str, start: int, end: int) -> tuple[int, int]:
    if end - start >= 2 and text[start] in QUOTES and text[end - 1] == text[start]:
        return start + 1, end - 1
    return start, end


class RegexDetector:
    name = "regex"
    rule_detector = "regex"

    def __init__(self, ruleset) -> None:
        self.rules = ruleset.enabled_rules(self.rule_detector)

    def detect(self, text: str, ctx: DetectContext) -> list[Finding]:
        findings: list[Finding] = []
        lowered = None
        for rule in self.rules:
            if rule.hint:
                if lowered is None:
                    lowered = text.lower()
                if not any(h in lowered for h in rule.hint):
                    continue
            pattern = rule.compiled
            has_value_group = "value" in pattern.groupindex
            for m in pattern.finditer(text):
                if has_value_group and m.group("value") is not None:
                    start, end = m.span("value")
                else:
                    start, end = m.span()
                start, end = strip_quotes(text, start, end)
                if end <= start:
                    continue
                confidence = apply_validator(rule.validator, text[start:end], rule.confidence)
                findings.append(Finding(start, end, rule.category, confidence, self.name, rule.id))
        return findings
