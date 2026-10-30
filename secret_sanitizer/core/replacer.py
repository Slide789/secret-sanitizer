"""Platzhalter-Vergabe ([PASSWORD_1] ...) und Konsistenz-Propagation.

Das Mapping (Originalwert -> Platzhalter) liegt nur im Arbeitsspeicher und wird
nie auf die Festplatte geschrieben (v1). Derselbe Wert bekommt immer denselben
Platzhalter, auch in anderen Schreibweisen (Groß-/Kleinschreibung,
URL-codiert, JSON-/HTML-escaped).
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from urllib.parse import quote, quote_plus, unquote

from .models import Finding, Replacement, SanitizeResult

# Kürzere Werte werden nur an der gefundenen Stelle ersetzt, nicht überall,
# weil sonst z. B. "ab" mitten in normalen Wörtern ersetzt würde.
MIN_PROPAGATION_LENGTH = 4
MAX_TRIE_KEY_LENGTH = 200

PLACEHOLDER_RE = re.compile(r"\[[A-Z][A-Z0-9_]*_\d+\]")


def value_key(value: str) -> str:
    # lower() statt casefold(), damit die Länge zur Regex-Suche (IGNORECASE) passt
    return value.lower()


def value_variants(value: str) -> set[str]:
    """Andere Schreibweisen desselben Werts, nach denen ebenfalls gesucht wird."""
    variants = {value}
    decoded = unquote(value)
    variants.add(decoded)
    for base in (value, decoded):
        variants.add(quote(base, safe=""))
        variants.add(quote_plus(base, safe=""))
        variants.add(quote(base, safe="/:@"))
        variants.add(base.replace("\\", "\\\\").replace('"', '\\"'))  # JSON / C-String
        variants.add(html.escape(base, quote=True))
    return {v for v in variants if v}


@dataclass
class RestoreResult:
    """Ergebnis der Rückübersetzung. spans: (start, end, Kategorie) der
    eingesetzten Originalwerte im Ergebnistext (für die farbige Anzeige)."""

    text: str
    spans: list = field(default_factory=list)
    unknown: list = field(default_factory=list)

    def __repr__(self) -> str:  # bewusst ohne Werte
        return f"RestoreResult({len(self.spans)} ersetzt, {len(self.unknown)} unbekannt)"


class PlaceholderMapping:
    """Wert -> Platzhalter, mit Zähler je Kategorie."""

    def __init__(self, style: str = "[{CATEGORY}_{N}]") -> None:
        self.style = style
        self._by_key: dict[str, tuple[str, str]] = {}   # key -> (Platzhalter, Kategorie)
        # Platzhalter -> (Originalwert in der zuerst gesehenen Schreibweise, Kategorie),
        # für die Rückübersetzung von KI-Antworten (restore)
        self._originals: dict[str, tuple[str, str]] = {}
        self._counters: dict[str, int] = {}
        self._matchers: list | None = None
        self._dirty = False

    def __len__(self) -> int:
        return len({p for p, _ in self._by_key.values()})

    def __repr__(self) -> str:  # bewusst ohne Werte
        return f"PlaceholderMapping({len(self)} Platzhalter)"

    def clear(self) -> None:
        self._by_key.clear()
        self._originals.clear()
        self._counters.clear()
        self._matchers = None

    def _format(self, category: str, number: int) -> str:
        return self.style.replace("{CATEGORY}", category).replace("{N}", str(number))

    def get(self, value: str) -> str | None:
        hit = self._by_key.get(value_key(value))
        return hit[0] if hit else None

    def placeholder_for(self, value: str, category: str) -> str:
        """Liefert den Platzhalter für einen Wert und vergibt bei Bedarf einen neuen."""
        hit = self._by_key.get(value_key(value))
        if hit:
            return hit[0]
        number = self._counters.get(category, 0) + 1
        self._counters[category] = number
        placeholder = self._format(category, number)
        self._originals[placeholder] = (value, category)
        for variant in value_variants(value):
            self._by_key.setdefault(value_key(variant), (placeholder, category))
        self._dirty = True
        return placeholder

    def placeholders(self) -> list[str]:
        return sorted({p for p, _ in self._by_key.values()})

    def restore(self, text: str) -> RestoreResult:
        """Rückübersetzung: ersetzt bekannte Platzhalter (z. B. in einer
        KI-Antwort) wieder durch die Originalwerte. Platzhalter im
        Standardformat, die diese Sitzung nicht vergeben hat, werden gezählt."""
        result = RestoreResult(text)
        if not text:
            return result
        known = sorted(self._originals, key=len, reverse=True)
        out: list[str] = []
        pos = 0
        out_len = 0
        if known:
            pattern = re.compile("|".join(re.escape(p) for p in known))
            for m in pattern.finditer(text):
                value, category = self._originals[m.group()]
                out.append(text[pos:m.start()])
                out_len += m.start() - pos
                out.append(value)
                result.spans.append((out_len, out_len + len(value), category))
                out_len += len(value)
                pos = m.end()
        out.append(text[pos:])
        result.text = "".join(out)
        result.unknown = sorted({m.group() for m in PLACEHOLDER_RE.finditer(text) if m.group() not in self._originals})
        return result

    # ------------------------------------------------------------------
    def _build_matchers(self) -> list:
        """Baut die Suchmuster für die Propagation.

        Die Werte werden als Trie-Regex (gemeinsame Präfixe zusammengefasst)
        kompiliert, getrennt nach Art der Wortgrenze. Das ist bei tausenden
        Werten um Größenordnungen schneller als eine flache Alternation.
        Sehr lange Werte (z. B. PEM-Blöcke) werden per str.find gesucht."""
        groups: dict[tuple[bool, bool], list[str]] = {}
        long_keys = []
        for key in self._by_key:
            if len(key) < MIN_PROPAGATION_LENGTH:
                continue
            if len(key) > MAX_TRIE_KEY_LENGTH:
                long_keys.append(key)
                continue
            groups.setdefault((_is_word(key[0]), _is_word(key[-1])), []).append(key)
        matchers = []
        for (word_start, word_end), keys in groups.items():
            body = _trie_pattern(keys)
            pattern = ("(?<!\\w)" if word_start else "") + body + ("(?!\\w)" if word_end else "")
            matchers.append(re.compile(pattern, re.IGNORECASE))
        return matchers + sorted(long_keys, key=len, reverse=True)

    def find_propagated(self, text: str) -> list[Finding]:
        """Findet alle bekannten Werte (und Varianten) im Text."""
        if self._dirty or self._matchers is None:
            self._matchers = self._build_matchers()
            self._dirty = False
        findings = []
        lowered = None
        for matcher in self._matchers:
            if isinstance(matcher, str):
                if lowered is None:
                    lowered = text.lower()
                    if len(lowered) != len(text):  # exotische Zeichen ändern die Länge
                        lowered = text
                start = lowered.find(matcher)
                while start != -1:
                    end = start + len(matcher)
                    hit = self._by_key[matcher]
                    findings.append(Finding(start, end, hit[1], 1.0, "propagation"))
                    start = lowered.find(matcher, end)
                continue
            for m in matcher.finditer(text):
                hit = self._by_key.get(value_key(m.group()))
                if hit is not None:
                    findings.append(Finding(m.start(), m.end(), hit[1], 1.0, "propagation"))
        return findings


def _is_word(ch: str) -> bool:
    return ch.isalnum() or ch == "_"


def _trie_pattern(keys: list[str]) -> str:
    """Regex aus einem Trie: ["abc", "abd", "ab"] -> ab(?:c|d)?"""
    trie: dict = {}
    for key in keys:
        node = trie
        for ch in key:
            node = node.setdefault(ch, {})
        node[""] = {}

    def build(node: dict) -> str:
        parts = []
        # Ketten ohne Verzweigung direkt als Literal (vermeidet tiefe Rekursion)
        while len(node) == 1 and "" not in node:
            (ch, child), = node.items()
            parts.append(re.escape(ch))
            node = child
        if not node or list(node) == [""]:
            return "".join(parts)
        alternatives = [re.escape(ch) + build(child) for ch, child in sorted(node.items()) if ch]
        group = "(?:" + "|".join(alternatives) + ")" if len(alternatives) > 1 else alternatives[0]
        if "" in node:
            group = (group if len(alternatives) > 1 else "(?:" + group + ")") + "?"
        return "".join(parts) + group

    return build(trie)


def apply_replacements(text: str, findings: list[Finding], mapping: PlaceholderMapping) -> SanitizeResult:
    """Ersetzt die (bereits überlappungsfreien) Treffer durch Platzhalter."""
    out: list[str] = []
    replacements: list[Replacement] = []
    pos = 0
    out_len = 0
    for f in sorted(findings, key=lambda x: x.start):
        if f.start < pos:
            continue  # Sicherheitsnetz, sollte nach dem Merger nicht vorkommen
        chunk = text[pos:f.start]
        out.append(chunk)
        out_len += len(chunk)
        placeholder = mapping.placeholder_for(text[f.start:f.end], f.category)
        out.append(placeholder)
        replacements.append(Replacement(f.start, f.end, out_len, out_len + len(placeholder),
                                        f.category, placeholder, f.confidence, f.detector, f.rule_id))
        out_len += len(placeholder)
        pos = f.end
    out.append(text[pos:])
    return SanitizeResult("".join(out), replacements)
