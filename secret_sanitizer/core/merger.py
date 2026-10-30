"""Treffer zusammenführen: filtern, Konfidenz bewerten, Überlappungen auflösen.

Regeln:
1. Verworfen werden Treffer unterhalb der Modus-Schwelle, abgeschaltete
   Kategorien, Allowlist-Werte, vom Nutzer ausgenommene Werte und bereits
   vorhandene Platzhalter.
2. Finden mehrere Detektoren genau dieselbe Stelle, steigt die Konfidenz leicht.
3. Überlappen sich Treffer, gewinnt der mit der höchsten Konfidenz.
   Ausnahme: Ein Block-Treffer (ganzer PEM-Schlüssel/-Zertifikat), der die
   anderen komplett enthält, gewinnt, damit keine Teile eines Schlüssels
   übrig bleiben.
4. Propagations-Treffer füllen nur Lücken (sie verdrängen keine Detektor-Treffer).
5. Treffer abgeschalteter Kategorien werden nicht ersetzt, "belegen" aber ihre
   Stelle: Ist E-Mail aus, wird nicht stattdessen der Domain-Teil ersetzt.
"""

from __future__ import annotations

from array import array

from .models import Finding
from .replacer import PLACEHOLDER_RE, value_key

AGREEMENT_BONUS = 0.05
CONTAINER_MIN_CONFIDENCE = 0.8
BLOCK_CATEGORIES = frozenset({"PRIVATE_KEY", "CERTIFICATE"})


def filter_findings(findings, text, settings, ruleset, exclude_keys=frozenset()) -> list[Finding]:
    threshold = settings.threshold()
    kept = []
    for f in findings:
        if f.end <= f.start:
            continue
        if f.confidence < threshold:
            continue
        value = text[f.start:f.end]
        stripped = value.strip()
        if not stripped:
            continue
        if exclude_keys and value_key(value) in exclude_keys:
            continue
        if PLACEHOLDER_RE.fullmatch(stripped):
            continue
        if ruleset is not None and ruleset.is_allowed(stripped):
            continue
        kept.append(f)
    return kept


def _combine_same_span(findings: list[Finding]) -> list[Finding]:
    by_span: dict[tuple[int, int], list[Finding]] = {}
    for f in findings:
        by_span.setdefault((f.start, f.end), []).append(f)
    combined = []
    for group in by_span.values():
        best = max(group, key=lambda x: x.confidence)
        detectors = {g.detector for g in group}
        if len(detectors) > 1:
            bonus = AGREEMENT_BONUS * (len(detectors) - 1)
            best = Finding(best.start, best.end, best.category, min(1.0, best.confidence + bonus),
                           best.detector, best.rule_id)
        combined.append(best)
    return combined


class _IntervalSet:
    """Überlappungsfreie Intervalle. Belegte Zeichenpositionen werden in einem
    bytearray markiert; die Überlappungsprüfung läuft so in C-Geschwindigkeit,
    auch bei hunderttausenden Treffern pro Block."""

    def __init__(self, size: int = 0) -> None:
        self.occupied = bytearray(size)
        self.owner = array("q", bytes(8 * size))   # Startposition des belegenden Treffers
        self.by_start: dict[int, Finding] = {}

    def _ensure(self, end: int) -> None:
        if end > len(self.occupied):
            grow = end - len(self.occupied) + 1024
            self.occupied.extend(bytes(grow))
            self.owner.extend(array("q", bytes(8 * grow)))

    def overlapping(self, f: Finding) -> list[Finding]:
        self._ensure(f.end)
        if self.occupied.find(1, f.start, f.end) == -1:
            return []
        starts = {self.owner[i] for i in range(f.start, f.end) if self.occupied[i]}
        return [self.by_start[st] for st in sorted(starts)]

    def add(self, f: Finding) -> None:
        self._ensure(f.end)
        n = f.end - f.start
        self.occupied[f.start:f.end] = b"\x01" * n
        self.owner[f.start:f.end] = array("q", [f.start]) * n
        self.by_start[f.start] = f

    def remove(self, items: list[Finding]) -> None:
        for f in items:
            self.occupied[f.start:f.end] = bytes(f.end - f.start)
            del self.by_start[f.start]

    @property
    def items(self) -> list[Finding]:
        return [self.by_start[k] for k in sorted(self.by_start)]


def resolve_overlaps(primary: list[Finding], propagated: list[Finding] = ()) -> list[Finding]:
    size = max([f.end for f in primary] + [f.end for f in propagated] + [0])
    selected = _IntervalSet(size)
    ordered = sorted(_combine_same_span(primary), key=lambda f: (-f.confidence, -f.length, f.start))
    for f in ordered:
        hits = selected.overlapping(f)
        if not hits:
            selected.add(f)
            continue
        if (f.category in BLOCK_CATEGORIES and f.confidence >= CONTAINER_MIN_CONFIDENCE
                and all(f.contains(o) and f.length > o.length for o in hits)):
            selected.remove(hits)
            selected.add(f)
    for f in sorted(propagated, key=lambda x: (-x.length, x.start)):
        if not selected.overlapping(f):
            selected.add(f)
    return selected.items


def _drop_disabled(findings: list[Finding], settings) -> list[Finding]:
    """Entfernt Treffer abgeschalteter Kategorien sowie alle Treffer, die
    vollständig in einem siegreichen abgeschalteten Treffer liegen."""
    disabled = [f for f in resolve_overlaps(findings) if not settings.is_category_enabled(f.category)]
    if not disabled:
        return findings
    blockers = _IntervalSet(max(f.end for f in findings))
    for f in disabled:
        blockers.add(f)
    kept = []
    for f in findings:
        if not settings.is_category_enabled(f.category):
            continue
        if any(b.contains(f) for b in blockers.overlapping(f)):
            continue
        kept.append(f)
    return kept


def prepare(findings, text, settings, ruleset, exclude_keys=frozenset()) -> list[Finding]:
    """Filtert Detektor-Treffer (Schwelle, Allowlist, Ausnahmen, Kategorien)."""
    return _drop_disabled(filter_findings(findings, text, settings, ruleset, exclude_keys), settings)


def prepare_propagated(propagated, text, settings, ruleset, exclude_keys=frozenset()) -> list[Finding]:
    return [f for f in filter_findings(propagated, text, settings, ruleset, exclude_keys)
            if settings.is_category_enabled(f.category)]


def merge(findings, text, settings, ruleset, exclude_keys=frozenset(), propagated=()) -> list[Finding]:
    primary = prepare(findings, text, settings, ruleset, exclude_keys)
    extra = prepare_propagated(propagated, text, settings, ruleset, exclude_keys) if propagated else []
    return resolve_overlaps(primary, extra)
