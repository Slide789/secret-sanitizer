"""Kontext-Heuristik und Kommandozeilen-Argumente.

ContextDetector: einfacher, toleranter key=value / key: value / <key>value</key>
Parser. Ist der Schlüsselname verdächtig (password, token, api_key, ...), wird
der Wert ersetzt. So werden auch simple Passwörter wie "hunter2" erkannt, die
weder Muster noch hohe Entropie haben.

CommandLineDetector: Spezialfall mit eigenen Regeln (detector="cmdline" in
default_rules.json), z. B. -p geheim, --password=..., mysql -pSECRET, curl -u.
"""

from __future__ import annotations

import re

from ..core.models import DetectContext, Finding
from .regex_detector import RegexDetector, strip_quotes

# key = value | key: value | "key": "value" | key => value | key := value
_KV_RE = re.compile(
    r"""(?P<q>["']?)(?P<key>[A-Za-z_][\w.\-]{0,63}(?:[ ][A-Za-z_][\w.\-]{0,30}){0,2})(?P=q)\]?"""
    r"""[ \t]*(?:=>|:=|=|:)[ \t]*"""
    r"""(?P<value>"(?:[^"\\\n]|\\.)*"|'[^'\n]*'|[^\s;&"'<>][^\s;&<>]*)"""
)
# YAML-Blockwert: "password: |" bzw. ">-", der Wert steht in den eingerückten Folgezeilen
_YAML_BLOCK_RE = re.compile(
    r"""^(?P<indent>[ ]*)(?:-[ ]+)?(?P<q>["']?)(?P<key>[A-Za-z_][\w.\-]{0,63})(?P=q)[ \t]*:[ \t]*"""
    r"""[|>][-+1-9]{0,2}[ \t]*$""", re.MULTILINE)
_BLOCK_INDICATOR_RE = re.compile(r"[|>][-+1-9]{0,2}")
# Weiteres Wort einer Passphrase in derselben Zeile
_PHRASE_WORD_RE = re.compile(r"[ \t]+([^\s;&<>]+)")
MAX_PHRASE_CHARS = 200
PHRASE_PENALTY = 0.01
QUOTE_CHARS = "\"'`"
# <password>wert</password>
_XML_RE = re.compile(r"<(?P<key>[A-Za-z_][\w:.\-]{0,63})(?:\s[^<>]*)?>(?P<value>[^<\n]{1,500})</(?P=key)>")
# XML-Attribut: password="wert"
_ATTR_RE = re.compile(r"""\s(?P<key>[A-Za-z_][\w:.\-]{0,63})\s*=\s*(?P<value>"[^"\n]*"|'[^'\n]*')""")

_AUTH_SCHEMES = {"bearer", "basic", "token", "digest", "ntlm", "negotiate", "bot", "apikey"}
_CAMEL_RE = re.compile(r"([a-z0-9])([A-Z])")
_SPLIT_RE = re.compile(r"[_\-.\s:]+")
_REFERENCE_RE = re.compile(r"^(?:\$\{?[A-Za-z_]\w*\}?|%[A-Za-z_]\w*%|\{\{.*\}\}|\$\(.*\)|\$env:\w+)$")
_PATH_RE = re.compile(r"^(?:/|~/|\.\.?/|[A-Za-z]:[\\/]|\\\\)")
_TRAILING = ",)]}"
_CALL_RE = re.compile(r"^[A-Za-z_][\w.]*\(")
# PowerShell-Cmdlets (Verb-Nomen) mit gängigen Verben, z. B. $pw = Read-Host
_CMDLET_RE = re.compile(
    r"^(?:Get|Set|New|Remove|Add|ConvertTo|ConvertFrom|Invoke|Start|Stop|Import|Export|Read|Write|Test"
    r"|Connect|Out|Select|Where|Format|Join|Split|Resolve|Enable|Disable|Install|Update|Register|Clear"
    r"|Copy|Move|Rename|Restart|Unprotect|Protect)-[A-Z][A-Za-z]+$")

# Kategorien, bei denen reine (kurze) Zahlen kein Geheimnis sind.
_NUMERIC_IRRELEVANT = {"TOKEN", "API_KEY", "SECRET", "HOSTNAME", "USERNAME", "PASSWORD_HASH"}


def key_tokens(key: str) -> list[str]:
    """'dbPassword' -> ['db', 'password'], 'AWS_SECRET-KEY' -> ['aws', 'secret', 'key']"""
    key = _CAMEL_RE.sub(r"\1_\2", key)
    return [t for t in _SPLIT_RE.split(key.lower()) if t]


class _KeywordMatcher:
    def __init__(self, ruleset) -> None:
        self.entries = []  # (kw_tokens, kw_joined, category, confidence)
        for group in ruleset.context_keywords:
            for kw in group.keywords:
                tokens = key_tokens(kw)
                self.entries.append((tokens, "".join(tokens), group.category, group.confidence))
        self.excludes = [e.lower() for e in ruleset.context_key_excludes]
        self._cache: dict = {}

    def _excluded(self, tokens: list[str]) -> bool:
        for tok in tokens:
            for ex in self.excludes:
                if tok == ex or (len(ex) >= 5 and tok.startswith(ex)):
                    return True
        return False

    def match(self, key: str):
        """Liefert (Kategorie, Konfidenz) oder None. Der längste passende
        Schlüsselbegriff gewinnt (password_hash schlägt password)."""
        try:
            return self._cache[key]
        except KeyError:
            pass
        result = self._match(key)
        if len(self._cache) > 50_000:
            self._cache.clear()
        self._cache[key] = result
        return result

    def _match(self, key: str):
        tokens = key_tokens(key)
        if len(tokens) > 3:
            tokens = tokens[-3:]  # bei Fließtext nur die letzten Wörter
        if not tokens or self._excluded(tokens):
            return None
        joined = "".join(tokens)
        best = None
        for kw_tokens, kw_joined, category, confidence in self.entries:
            n = len(kw_tokens)
            hit = any(tokens[i:i + n] == kw_tokens for i in range(len(tokens) - n + 1))
            if not hit and len(kw_joined) >= 4 and joined.endswith(kw_joined):
                hit = True
            if hit and (best is None or len(kw_joined) > best[0]):
                best = (len(kw_joined), category, confidence)
        return (best[1], best[2]) if best else None


def plausible_value(value: str, category: str, quoted: bool = False) -> bool:
    """Filtert Werte, die offensichtlich kein Geheimnis sind."""
    v = value.strip()
    if len(v) < 2:
        return False
    if _REFERENCE_RE.match(v):          # $VAR, ${VAR}, %VAR%, {{ template }}
        return False
    if _PATH_RE.match(v):               # password_file=/run/secret ...
        return False
    if len(set(v)) == 1:                # ******** oder xxxxxxxx
        return False
    if category in _NUMERIC_IRRELEVANT and v.isdigit() and len(v) < 8:
        return False
    if v.startswith(("[", "{", "(")) and category != "PASSWORD":
        return False
    if not quoted and (_CALL_RE.search(v) or _CMDLET_RE.match(v)):
        return False                    # get_password(...) oder ConvertTo-SecureString
    if not quoted and _BLOCK_INDICATOR_RE.fullmatch(v):
        return False                    # YAML "|-": der Wert steht in den Folgezeilen
    return True


def extend_phrase(text: str, end: int) -> int:
    """Passphrasen mit Leerzeichen ("password: correct horse battery"): hängt
    weitere Wörter derselben Zeile an. Schluss ist bei einem Trenner (",", ";",
    "&", "<"), einem Kommentar, einer Option (-x) oder dem nächsten key=value."""
    limit = end + MAX_PHRASE_CHARS
    while text[end - 1] not in ",;":
        m = _PHRASE_WORD_RE.match(text, end)
        if not m or m.end() > limit:
            break
        word = m.group(1)
        if "=" in word or word.endswith(":") or word.startswith(("-", "#", "//")):
            break
        end = m.end()
    return end


def yaml_block_span(text: str, line_end: int, key_indent: int) -> tuple[int, int] | None:
    """Bereich der eingerückten Folgezeilen eines YAML-Blockwerts (ohne die
    Einrückung der ersten Zeile und ohne abschließende Leerzeichen)."""
    start = end = None
    pos = line_end + 1
    while pos < len(text):
        nl = text.find("\n", pos)
        if nl == -1:
            nl = len(text)
        line = text[pos:nl]
        if line.strip():
            indent = len(line) - len(line.lstrip(" \t"))
            if indent <= key_indent:
                break
            if start is None:
                start = pos + indent
            end = pos + len(line.rstrip())
        pos = nl + 1
    return (start, end) if start is not None else None


class ContextDetector:
    name = "context"

    def __init__(self, ruleset) -> None:
        self.matcher = _KeywordMatcher(ruleset)

    def _emit(self, text, key, start, end, findings, phrase: bool = False) -> int | None:
        """Prüft Schlüssel und Wert. Gibt das Ende des gemeldeten Treffers
        zurück oder None, wenn nichts gemeldet wurde.
        phrase: unquotierte Passwörter dürfen Leerzeichen enthalten (key=value-Zeilen)."""
        match = self.matcher.match(key)
        if match is None:
            return None
        category, confidence = match
        quoted = (start, end) != strip_quotes(text, start, end)
        start, end = strip_quotes(text, start, end)
        if not quoted:
            # Ein schließendes Anführungszeichen ohne öffnendes gehört nicht zum Wert
            # (z. B. "--password=geheim" in Anführungszeichen).
            while end > start and text[end - 1] in QUOTE_CHARS and text.count(text[end - 1], start, end) == 1:
                end -= 1
        # Unquotierte Werte: abschließende Klammern/Kommas gehören meist nicht dazu.
        while end > start and text[end - 1] in _TRAILING:
            end -= 1
        if end <= start:
            return None
        if text[start:end].lower() in _AUTH_SCHEMES:
            nxt = re.compile(r"[ \t]+(\S+)").match(text, end)
            if not nxt:
                return None
            start, end = nxt.span(1)
            category = "TOKEN" if category in ("TOKEN", "SECRET", "API_KEY") else category
        if not plausible_value(text[start:end], category, quoted):
            return None
        phrase_end = end
        if phrase and not quoted and category == "PASSWORD":
            phrase_end = extend_phrase(text, end)
            while phrase_end > end and text[phrase_end - 1] in _TRAILING:
                phrase_end -= 1
        if phrase_end == end:
            findings.append(Finding(start, end, category, confidence, self.name, "kv"))
            return end
        # Passphrase mit Leerzeichen: zwei Treffer. Die ganze Phrase gewinnt,
        # wenn nichts anderes in ihr liegt. Liegt dahinter ein eigener Treffer
        # gleicher Sicherheit (IP, E-Mail ...), verliert sie knapp, und der
        # Grundtreffer ersetzt das erste Wort; der Rest bleibt eigenständig erkannt.
        findings.append(Finding(start, phrase_end, category, confidence - PHRASE_PENALTY, self.name, "kv_phrase"))
        findings.append(Finding(start, end, category, confidence - 2 * PHRASE_PENALTY, self.name, "kv"))
        return phrase_end

    def _emit_yaml_blocks(self, text, findings) -> None:
        for m in _YAML_BLOCK_RE.finditer(text):
            match = self.matcher.match(m.group("key"))
            if match is None:
                continue
            span = yaml_block_span(text, m.end(), len(m.group("indent")))
            if span is None or not plausible_value(text[span[0]:span[1]], match[0], quoted=True):
                continue
            findings.append(Finding(span[0], span[1], match[0], match[1], self.name, "yaml_block"))

    def detect(self, text: str, ctx: DetectContext) -> list[Finding]:
        findings: list[Finding] = []
        pos = 0
        while True:
            m = _KV_RE.search(text, pos)
            if m is None:
                break
            # "https://..." ist kein key=value. Wurde nichts gemeldet, wird im
            # Wert weitergesucht, damit z. B. "?token=..." in URLs oder
            # "options: password=x" nicht übersehen wird.
            end = None
            if not text.startswith("//", m.start("value")):
                end = self._emit(text, m.group("key"), *m.span("value"), findings, phrase=True)
            if end is not None:
                pos = max(m.end(), end)
            else:
                pos = m.start("value")
                if pos <= m.start():
                    pos = m.start() + 1
        for regex in (_XML_RE, _ATTR_RE):
            for m in regex.finditer(text):
                self._emit(text, m.group("key"), *m.span("value"), findings)
        self._emit_yaml_blocks(text, findings)
        return findings


class CommandLineDetector(RegexDetector):
    """Kommandozeilen-Argumente: Regeln mit "detector": "cmdline"."""

    name = "cmdline"
    rule_detector = "cmdline"
