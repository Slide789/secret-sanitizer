"""Detektoren. Jeder Detektor hat die gleiche Schnittstelle:
    name: str
    detect(text, ctx) -> list[Finding]
"""

from __future__ import annotations


def build_detectors(ruleset, settings) -> list:
    """Erzeugt alle Detektoren in fester Reihenfolge."""
    from .context_detector import CommandLineDetector, ContextDetector
    from .entropy_detector import EntropyDetector
    from .regex_detector import RegexDetector
    from .wordlist_detector import WordlistDetector

    detectors = [RegexDetector(ruleset), ContextDetector(ruleset), CommandLineDetector(ruleset),
                 WordlistDetector(ruleset), EntropyDetector(settings)]
    return detectors
