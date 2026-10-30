"""Entropie-Analyse für unbekannte Secrets (ohne bekanntes Format oder Schlüsselwort).

Vorgehen:
1. Kandidaten: zusammenhängende Zeichenfolgen aus Base64/Hex-Zeichen ab einer
   Mindestlänge (je nach Modus).
2. Zeichensatz bestimmen: hex, base64 oder gemischt. Jede Klasse hat eigene
   Schwellen, weil Hex-Text höchstens 4 Bit/Zeichen erreichen kann.
3. Ausnahmen: Hashes typischer Länge (MD5/SHA-1/SHA-256 ...), GUIDs, Pfade,
   Bezeichner wie "test_user_account_2024", reine Wörter oder Zahlen.
4. Shannon-Entropie >= Schwelle -> Treffer der Kategorie SECRET.
"""

from __future__ import annotations

import math
import re
from collections import Counter

from ..core.models import DetectContext, Finding

_CANDIDATE_RE = re.compile(r"(?<![A-Za-z0-9+/=_\-])[A-Za-z0-9+/_\-]{8,}={0,2}(?![A-Za-z0-9+/=_\-])")
_HEX_RE = re.compile(r"[0-9a-fA-F]+")
_GUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_HASH_LENGTHS = {32, 40, 56, 64, 96, 128}
_SEGMENT_SPLIT = re.compile(r"[_\-./+=]+")
_SHORT_ALNUM_PART = re.compile(r"[a-z]{1,3}\d{1,3}|\d{1,3}[a-z]{1,3}|[A-Z]{1,3}\d{1,3}")
_PATH_SEGMENT = re.compile(r"[A-Za-z0-9._\-]+")
# Direkt davor stehende Hinweise, dass es eine Prüfsumme ist (kein Geheimnis).
_HASH_HINT_RE = re.compile(r"(?i)(?:sha\d*|md5|sha-\d+|checksum|digest|commit|hash|etag|crc\d*)[\s:=\"'@]*$")

BASE_CONFIDENCE = 0.45


def shannon_entropy(value: str) -> float:
    if not value:
        return 0.0
    counts = Counter(value)
    n = len(value)
    return -sum(c / n * math.log2(c / n) for c in counts.values())


def charset_of(value: str) -> str:
    if _HEX_RE.fullmatch(value):
        return "hex"
    if re.fullmatch(r"[A-Za-z0-9+/]+={0,2}", value) or re.fullmatch(r"[A-Za-z0-9_\-]+={0,2}", value):
        return "base64"
    return "mixed"


def _looks_like_identifier(value: str) -> bool:
    """Bezeichner aus Wörtern und Zahlen, z. B. test_user_account_2024 oder my-app-v2."""
    parts = [p for p in _SEGMENT_SPLIT.split(value) if p]
    if len(parts) < 2:
        return False
    for p in parts:
        if p.isdigit():
            continue
        if p.isalpha() and (p.islower() or p.isupper() or p.istitle()):
            continue
        if _SHORT_ALNUM_PART.fullmatch(p):  # v2, x86, 64bit
            continue
        return False
    return True


def _looks_like_path(value: str) -> bool:
    if "/" not in value:
        return False
    segments = [s for s in value.split("/") if s]
    if len(segments) < 2:
        return False
    for seg in segments:
        if not _PATH_SEGMENT.fullmatch(seg):
            return False
        letters = [c for c in seg if c.isalpha()]
        mixed_case = any(c.islower() for c in letters) and any(c.isupper() for c in letters)
        has_digit = any(c.isdigit() for c in seg)
        # Zufällige Base64-Segmente mischen Groß/klein und Ziffern.
        if mixed_case and has_digit and not seg.istitle():
            return False
    return True


class EntropyDetector:
    name = "entropy"

    def __init__(self, settings) -> None:
        self.settings = settings

    def _thresholds(self, mode: str):
        thresholds = self.settings.entropy_thresholds.get(mode) or self.settings.entropy_thresholds.get("strict")
        min_len = int(self.settings.entropy_min_length.get(mode, 16))
        return thresholds, min_len

    def evaluate(self, value: str, mode: str) -> float | None:
        """Konfidenz für einen Kandidaten oder None, wenn er kein Secret ist."""
        thresholds, min_len = self._thresholds(mode)
        core = value.rstrip("=")
        if len(core) < min_len:
            return None
        has_digit = any(c.isdigit() for c in core)
        has_lower = any(c.islower() for c in core)
        has_upper = any(c.isupper() for c in core)
        if not has_digit or not (has_lower or has_upper):
            return None  # reine Wörter oder reine Zahlen
        charset = charset_of(core)
        if charset == "hex":
            if len(core) in _HASH_LENGTHS:
                return None  # vermutlich Datei-/Commit-Hash
        if _GUID_RE.search(core) or _looks_like_identifier(core) or _looks_like_path(core):
            return None
        entropy = shannon_entropy(core)
        threshold = float(thresholds.get(charset, thresholds.get("mixed", 3.5)))
        if entropy < threshold:
            return None
        confidence = BASE_CONFIDENCE
        if len(core) >= 32:
            confidence += 0.1
        if entropy - threshold >= 0.5:
            confidence += 0.1
        if len(core) >= 40 and has_lower and has_upper and has_digit:
            confidence += 0.15
        return min(confidence, 0.8)

    def detect(self, text: str, ctx: DetectContext) -> list[Finding]:
        findings = []
        mode = ctx.mode
        for m in _CANDIDATE_RE.finditer(text):
            value = m.group()
            confidence = self.evaluate(value, mode)
            if confidence is None:
                continue
            if _HASH_HINT_RE.search(text, max(0, m.start() - 20), m.start()):
                continue
            findings.append(Finding(m.start(), m.end(), "SECRET", confidence, self.name, charset_of(value.rstrip("="))))
        return findings
