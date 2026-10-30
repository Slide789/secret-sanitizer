"""Eigene Listen (Wörterbuch): exakte Treffer für Firmennamen, interne
Hostnamen, Domains, Benutzernamen, Projektnamen, Personennamen.

Groß-/Kleinschreibung kann je Liste ignoriert werden. Leerzeichen in einem
Eintrag passen auch auf mehrere Leerzeichen/Zeilenumbrüche.
"""

from __future__ import annotations

import re

from ..core.models import DetectContext, Finding

WORDLIST_CONFIDENCE = 0.95


def _word_pattern(word: str) -> str:
    part = r"\s+".join(re.escape(p) for p in word.split())
    if word[0].isalnum() or word[0] == "_":
        part = r"(?<!\w)" + part
    if word[-1].isalnum() or word[-1] == "_":
        part = part + r"(?!\w)"
    return part


def compile_wordlist(words, ignore_case: bool) -> re.Pattern | None:
    words = sorted({w.strip() for w in words if w and w.strip()}, key=len, reverse=True)
    if not words:
        return None
    return re.compile("|".join(_word_pattern(w) for w in words), re.IGNORECASE if ignore_case else 0)


class WordlistDetector:
    name = "wordlist"

    def __init__(self, ruleset) -> None:
        self.lists = []
        for wl in ruleset.wordlists:
            if not wl.enabled:
                continue
            pattern = compile_wordlist(wl.words, wl.ignore_case)
            if pattern is not None:
                self.lists.append((pattern, wl.category, wl.id))

    def detect(self, text: str, ctx: DetectContext) -> list[Finding]:
        findings = []
        for pattern, category, wl_id in self.lists:
            for m in pattern.finditer(text):
                findings.append(Finding(m.start(), m.end(), category, WORDLIST_CONFIDENCE, self.name, wl_id))
        return findings
