"""Datenmodelle: Kategorien, Treffer und Ergebnis einer Bereinigung.

Wichtig: Ein Treffer (Finding) speichert bewusst NICHT den Originalwert,
sondern nur die Position im Text. Dadurch kann ein Treffer gefahrlos geloggt
oder in Berichten verwendet werden; der Wert steckt nur im Text selbst.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from ..i18n import t


@dataclass(frozen=True)
class Category:
    id: str
    group: str
    color: str

    @property
    def label(self) -> str:
        return t(f"category.{self.id}.label")

    @property
    def description(self) -> str:
        return t(f"category.{self.id}.description")


# Gruppen für die Anzeige in GUI und CLI. "personal" = personenbezogene Daten.
GROUPS = ("secrets", "network", "identity", "personal", "finance", "custom")


def group_label(group: str) -> str:
    return t(f"group.{group}")


_CATEGORY_LIST = [
    Category("PASSWORD", "secrets", "#e74c3c"),
    Category("SECRET", "secrets", "#c0392b"),
    Category("TOKEN", "secrets", "#d35400"),
    Category("API_KEY", "secrets", "#e67e22"),
    Category("JWT", "secrets", "#f39c12"),
    Category("PRIVATE_KEY", "secrets", "#8e44ad"),
    Category("CERTIFICATE", "secrets", "#9b59b6"),
    Category("PASSWORD_HASH", "secrets", "#a04000"),
    Category("SSH_KEY", "secrets", "#6c3483"),
    Category("IP", "network", "#2980b9"),
    Category("MAC", "network", "#3498db"),
    Category("HOSTNAME", "network", "#16a085"),
    Category("DOMAIN", "network", "#1abc9c"),
    Category("UNC_PATH", "network", "#117a65"),
    Category("USERNAME", "identity", "#27ae60"),
    Category("SID", "identity", "#229954"),
    Category("EMAIL", "personal", "#2e86c1"),
    Category("NAME", "personal", "#5dade2"),
    Category("PHONE", "personal", "#85c1e9"),
    Category("CREDIT_CARD", "finance", "#b7950b"),
    Category("IBAN", "finance", "#d4ac0d"),
    Category("COMPANY", "custom", "#7f8c8d"),
    Category("PROJECT", "custom", "#95a5a6"),
    Category("CUSTOM", "custom", "#566573"),
]

CATEGORIES: dict[str, Category] = {c.id: c for c in _CATEGORY_LIST}
PERSONAL_CATEGORIES = tuple(c.id for c in _CATEGORY_LIST if c.group == "personal")


def category_color(category: str) -> str:
    cat = CATEGORIES.get(category)
    return cat.color if cat else "#7f8c8d"


@dataclass(frozen=True)
class Finding:
    """Ein Treffer im Text: Position [start, end), Kategorie, Konfidenz (0..1)
    und welcher Detektor/welche Regel ihn gefunden hat."""

    start: int
    end: int
    category: str
    confidence: float
    detector: str
    rule_id: str = ""

    @property
    def length(self) -> int:
        return self.end - self.start

    def value_in(self, text: str) -> str:
        return text[self.start:self.end]

    def overlaps(self, other: "Finding") -> bool:
        return self.start < other.end and other.start < self.end

    def contains(self, other: "Finding") -> bool:
        return self.start <= other.start and other.end <= self.end

    def __repr__(self) -> str:  # bewusst ohne Wert
        return (f"Finding({self.start}-{self.end}, {self.category}, "
                f"{self.confidence:.2f}, {self.detector}:{self.rule_id})")


@dataclass(frozen=True)
class Replacement:
    """Ein tatsächlich durchgeführter Ersatz.

    start/end beziehen sich auf den Originaltext, out_start/out_end auf den
    bereinigten Text (für die farbige Vorschau)."""

    start: int
    end: int
    out_start: int
    out_end: int
    category: str
    placeholder: str
    confidence: float
    detector: str
    rule_id: str = ""

    def __repr__(self) -> str:  # bewusst ohne Wert
        return f"Replacement({self.start}-{self.end} -> {self.placeholder}, {self.detector})"


@dataclass
class SanitizeResult:
    text: str
    replacements: list[Replacement] = field(default_factory=list)

    def counts_by_category(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for rep in self.replacements:
            counts[rep.category] = counts.get(rep.category, 0) + 1
        return counts


class DetectContext:
    """Was ein Detektor zur Laufzeit wissen muss (Modus, Einstellungen)."""

    def __init__(self, settings) -> None:
        self.settings = settings
        self.mode = settings.mode


class Detector(Protocol):
    """Gemeinsame Schnittstelle aller Detektoren."""

    name: str

    def detect(self, text: str, ctx: DetectContext) -> list[Finding]:
        ...
