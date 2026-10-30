"""Datenmodelle: Kategorien, Treffer und Ergebnis einer Bereinigung.

Wichtig: Ein Treffer (Finding) speichert bewusst NICHT den Originalwert,
sondern nur die Position im Text. Dadurch kann ein Treffer gefahrlos geloggt
oder in Berichten verwendet werden; der Wert steckt nur im Text selbst.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class Category:
    id: str
    label: str
    group: str
    color: str
    description: str


# Gruppen für die Anzeige in GUI und CLI. "personal" = personenbezogene Daten.
GROUPS = {
    "secrets": "Zugangsdaten & Schlüssel",
    "network": "Netzwerk & Systeme",
    "identity": "Konten & Pfade",
    "personal": "Personenbezogene Daten",
    "finance": "Finanzdaten",
    "custom": "Eigene Listen",
}

_CATEGORY_LIST = [
    Category("PASSWORD", "Passwörter", "secrets", "#e74c3c", "Passwörter und Kennwörter"),
    Category("SECRET", "Geheimnisse", "secrets", "#c0392b", "Unbekannte Secrets (z. B. per Entropie erkannt)"),
    Category("TOKEN", "Tokens", "secrets", "#d35400", "Zugriffstokens, Bearer-Tokens, Session-Cookies"),
    Category("API_KEY", "API-Keys", "secrets", "#e67e22", "API- und Cloud-Schlüssel"),
    Category("JWT", "JWT", "secrets", "#f39c12", "JSON Web Tokens"),
    Category("PRIVATE_KEY", "Private Schlüssel", "secrets", "#8e44ad", "PEM-Blöcke mit privaten Schlüsseln"),
    Category("CERTIFICATE", "Zertifikate", "secrets", "#9b59b6", "PEM-Zertifikate und andere PEM-Blöcke"),
    Category("PASSWORD_HASH", "Passwort-Hashes", "secrets", "#a04000", "NTLM, bcrypt, $6$, MD5-crypt usw."),
    Category("SSH_KEY", "SSH-Schlüssel", "secrets", "#6c3483", "Öffentliche SSH-Schlüssel (identifizierend)"),
    Category("IP", "IP-Adressen", "network", "#2980b9", "IPv4 und IPv6, auch private Adressen"),
    Category("MAC", "MAC-Adressen", "network", "#3498db", "Hardware-Adressen"),
    Category("HOSTNAME", "Hostnamen", "network", "#16a085", "Rechner- und Servernamen, FQDNs"),
    Category("DOMAIN", "Domains", "network", "#1abc9c", "Domains (v. a. aus eigenen Listen)"),
    Category("UNC_PATH", "UNC-Pfade", "network", "#117a65", "Windows-Freigaben \\\\server\\share"),
    Category("USERNAME", "Benutzernamen", "identity", "#27ae60", "Benutzernamen, z. B. aus C:\\Users\\... oder /home/..."),
    Category("SID", "Windows-SIDs", "identity", "#229954", "Sicherheits-IDs S-1-5-21-..."),
    Category("EMAIL", "E-Mail-Adressen", "personal", "#2e86c1", "E-Mail-Adressen (personenbezogen)"),
    Category("NAME", "Personennamen", "personal", "#5dade2", "Namen aus eigenen Listen (personenbezogen)"),
    Category("CREDIT_CARD", "Kreditkarten", "finance", "#b7950b", "Kartennummern mit gültiger Luhn-Prüfsumme"),
    Category("IBAN", "IBAN", "finance", "#d4ac0d", "IBANs mit gültiger Prüfsumme"),
    Category("COMPANY", "Firmennamen", "custom", "#7f8c8d", "Firmennamen aus eigenen Listen"),
    Category("PROJECT", "Projektnamen", "custom", "#95a5a6", "Projektnamen aus eigenen Listen"),
    Category("CUSTOM", "Sonstiges", "custom", "#566573", "Eigene Regeln ohne passende Kategorie"),
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
