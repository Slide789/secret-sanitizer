"""Kodierungserkennung, Binär-Erkennung und Zeilenenden.

PowerShell schreibt oft UTF-16 mit BOM, Linux-Logs sind meist UTF-8, ältere
Windows-Dateien cp1252/Latin-1. Ohne Erkennung würde in UTF-16-Dateien nichts
gefunden, weil zwischen jedem Zeichen ein Nullbyte steht.
"""

from __future__ import annotations

import codecs

SAMPLE_SIZE = 64 * 1024

_BOMS = (
    # UTF-32 zuerst prüfen: der UTF-32-LE-BOM beginnt wie der UTF-16-LE-BOM.
    (codecs.BOM_UTF32_LE, "utf-32"),
    (codecs.BOM_UTF32_BE, "utf-32"),
    (codecs.BOM_UTF8, "utf-8-sig"),
    (codecs.BOM_UTF16_LE, "utf-16"),
    (codecs.BOM_UTF16_BE, "utf-16"),
)


def detect_encoding(sample: bytes) -> str | None:
    """Ermittelt die Kodierung anhand der ersten Bytes.

    Rückgabe None bedeutet: Binärdatei (soll übersprungen werden)."""
    for bom, name in _BOMS:
        if sample.startswith(bom):
            return name
    if not sample:
        return "utf-8"
    if b"\x00" in sample:
        return _guess_utf16_without_bom(sample)
    try:
        # final=False: ein am Probenende abgeschnittenes Mehrbytezeichen ist ok.
        codecs.getincrementaldecoder("utf-8")().decode(sample, final=False)
        return "utf-8"
    except UnicodeDecodeError:
        pass
    try:
        sample.decode("cp1252")
        return "cp1252"
    except UnicodeDecodeError:
        return "latin-1"


def _guess_utf16_without_bom(sample: bytes) -> str | None:
    """UTF-16 ohne BOM: bei ASCII-lastigem Text ist jedes zweite Byte 0."""
    even = sample[0::2]
    odd = sample[1::2]
    n = max(1, len(sample) // 2)
    even_nulls = even.count(0) / n
    odd_nulls = odd.count(0) / n
    if odd_nulls > 0.4 and even_nulls < 0.05:
        return "utf-16-le"
    if even_nulls > 0.4 and odd_nulls < 0.05:
        return "utf-16-be"
    return None


def is_binary(sample: bytes) -> bool:
    return detect_encoding(sample) is None


def decode_bytes(data: bytes) -> tuple[str, str]:
    """Dekodiert komplette Bytes (z. B. stdin oder kleine Dateien).

    Rückgabe: (Text, Kodierung). Wirft ValueError bei Binärdaten."""
    encoding = detect_encoding(data[:SAMPLE_SIZE])
    if encoding is None:
        raise ValueError("Binärdaten erkannt")
    try:
        return data.decode(encoding), encoding
    except UnicodeDecodeError:
        # Die Probe war gültiges UTF-8, der Rest nicht: auf cp1252/Latin-1 ausweichen.
        for fallback in ("cp1252", "latin-1"):
            try:
                return data.decode(fallback), fallback
            except UnicodeDecodeError:
                continue
    raise ValueError("Kodierung nicht erkannt")  # pragma: no cover (latin-1 scheitert nie)


def dominant_newline(text: str) -> str:
    """'\\r\\n', wenn die Mehrheit der Zeilenenden Windows-Stil ist, sonst '\\n'."""
    crlf = text.count("\r\n")
    lf = text.count("\n") - crlf
    return "\r\n" if crlf > lf else "\n"


def normalize_newlines(text: str) -> tuple[str, str]:
    """Wandelt \\r\\n in \\n um. Rückgabe: (normalisierter Text, ursprüngliches Zeilenende)."""
    newline = dominant_newline(text)
    if "\r\n" in text:
        text = text.replace("\r\n", "\n")
    return text, newline


def restore_newlines(text: str, newline: str) -> str:
    if newline == "\n":
        return text
    return text.replace("\n", newline)


def output_encoding_for(input_encoding: str, configured: str) -> str:
    """Ausgabekodierung: Standard aus der Config (utf-8). Mit 'same' wird die
    Eingabekodierung beibehalten."""
    if configured.lower() in ("same", "gleich", "original"):
        return input_encoding
    return configured
