"""Prüfsummen-Validierung. Das ist ein Filter, kein eigener Detektor:
Eine gültige Prüfsumme erhöht die Konfidenz eines Regex-Treffers, eine
ungültige senkt sie so stark, dass der Treffer in keinem Modus mehr ersetzt wird.
"""

from __future__ import annotations

import ipaddress
import re

VALID_BONUS = 0.35
INVALID_FACTOR = 0.2


def luhn_valid(value: str) -> bool:
    digits = re.sub(r"[ \-]", "", value)
    if not digits.isdigit() or not 12 <= len(digits) <= 19:
        return False
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0 and len(set(digits)) > 1


def iban_valid(value: str) -> bool:
    iban = value.replace(" ", "").upper()
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}", iban):
        return False
    rearranged = iban[4:] + iban[:4]
    numeric = "".join(str(int(ch, 36)) for ch in rearranged)
    return int(numeric) % 97 == 1


def ipv4_valid(value: str) -> bool:
    try:
        ipaddress.IPv4Network(value, strict=False)
        return True
    except ValueError:
        return False


def ipv6_valid(value: str) -> bool:
    candidate = value.split("%", 1)[0]
    if len(candidate) < 3 or candidate.count(":") < 2:
        return False
    try:
        ipaddress.IPv6Address(candidate)
        return True
    except ValueError:
        return False


def phone_valid(value: str) -> bool:
    """Plausible Telefonnummer: 7 bis 15 Ziffern (E.164), nicht alle gleich."""
    digits = re.sub(r"\D", "", value)
    return 7 <= len(digits) <= 15 and len(set(digits)) > 2


VALIDATORS = {
    "luhn": luhn_valid,
    "iban": iban_valid,
    "ipv4": ipv4_valid,
    "ipv6": ipv6_valid,
    "phone": phone_valid,
}


def apply_validator(name: str | None, value: str, confidence: float) -> float:
    """Passt die Konfidenz anhand der Prüfsumme an."""
    if not name:
        return confidence
    check = VALIDATORS.get(name)
    if check is None:
        return confidence
    if check(value):
        return min(1.0, confidence + VALID_BONUS)
    return confidence * INVALID_FACTOR
