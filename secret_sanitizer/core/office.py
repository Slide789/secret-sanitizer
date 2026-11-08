"""Word, Excel, PowerPoint (.docx, .xlsx, .pptx) bereinigen.

Diese Dateien sind ZIP-Archive mit XML-Teilen. Bereinigt werden die Texte
(Fließtext, Tabellen, Kopf-/Fußzeilen, Fußnoten, Textfelder, Zellen,
Formeln, Folien, Notizen, Diagrammbeschriftungen, Kommentare), Alternativtexte
von Grafiken, externe Link-Ziele und die Metadaten. Layout und Formatierung
bleiben erhalten.

Sicherheit:
  - Das XML wird auf Textebene bearbeitet, ohne XML-Parser: es werden keine
    Entitäten expandiert ("Billion Laughs"), und alles, was nicht geändert
    wird, bleibt Byte für Byte erhalten. Teile mit DOCTYPE werden abgelehnt.
  - Nachverfolgte Änderungen werden angenommen: gelöschter Text steckt sonst
    weiter in der Datei.
  - Autorennamen (Dokument, Kommentare, Änderungen) werden geleert.
  - Bilder, eingebettete Objekte, ActiveX und die Vorschau-Miniatur werden
    standardmäßig entfernt (sie könnten Text enthalten, der nicht geprüft
    werden kann, z. B. ein Screenshot mit einem Passwort).
  - Makro-Dateien (.docm, .xlsm, .pptm) werden nicht verarbeitet.
  - Größenlimits wie bei Archiven (Schutz vor Zip-Bomben).
Text in Word ist oft in mehrere Stücke ("Runs") zerlegt. Darum wird jeder
XML-Teil als Ganzes geprüft (Absätze durch Zeilenumbrüche getrennt), und die
Ersetzungen werden zurück auf die Stücke verteilt.
"""

from __future__ import annotations

import html
import posixpath
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from ..i18n import t
from .replacer import PLACEHOLDER_RE, apply_replacements

OFFICE_KINDS = {".docx": "docx", ".xlsx": "xlsx", ".pptx": "pptx"}
MACRO_SUFFIXES = (".docm", ".dotm", ".xlsm", ".xltm", ".xlam", ".pptm", ".potm", ".ppsm")

_TAG_RE = re.compile(r"<(?:[^>\"']|\"[^\"]*\"|'[^']*')*>")
_NAME_RE = re.compile(r"<\s*/?\s*([\w:.\-]+)")
_ATTR_RE = re.compile(r"""(\s)([\w:.\-]+)(\s*=\s*)(["'])(.*?)\4""", re.S)
_RID_RE = re.compile(r"""\sr:(?:id|embed|link|pict|dm|lo|qs|cs)\s*=\s*["']([^"']+)["']""")

# Elemente, deren Text geprüft wird (Name -> Bedingung über den Eltern-Stapel)
TEXT_TAGS = {"w:t", "w:instrText", "a:t", "t", "text", "p:text", "vt:lpstr", "vt:lpwstr",
             "dc:title", "dc:subject", "dc:description", "cp:keywords", "cp:category"}
# Text wird geleert (Personennamen in Metadaten und Kommentar-Autoren)
BLANK_TEXT_TAGS = {"dc:creator", "cp:lastModifiedBy", "Company", "Manager", "author"}
PARA_TAGS = {"w:p", "a:p", "si", "is", "c", "definedName", "sheet"}
# Excel-Formeln (Zellen, benannte Bereiche/Druckbereiche, Diagrammreihen, Gültigkeit,
# bedingte Formatierung): enthalten Blattnamen, die zum umbenannten Blatt passen müssen
FORMULA_TAGS = {"f", "c:f", "definedName", "formula", "formula1", "formula2"}
_QUOTED_SHEET_REF = re.compile(r"'((?:[^']|'')*)'!")
_UNQUOTED_SHEET_REF = re.compile(r"((?:[\w.]|\[[A-Z][A-Z0-9_]*_\d+\])+)!")
# Nachverfolgte Änderungen: entfernen (gelöscht) bzw. auspacken (eingefügt)
DROP_TAGS = {"w:del", "w:moveFrom", "w:rPrChange", "w:pPrChange", "w:sectPrChange", "w:tblPrChange",
             "w:trPrChange", "w:tcPrChange", "w:tblGridChange", "w:numberingChange"}
UNWRAP_TAGS = {"w:ins", "w:moveTo"}
# Grafik-Container, die entfernt werden, wenn sie auf ein entferntes Bild/Objekt zeigen
MEDIA_CONTAINERS = {"w:drawing", "w:pict", "w:object", "p:pic", "p:graphicFrame", "xdr:twoCellAnchor",
                    "xdr:oneCellAnchor", "xdr:absoluteAnchor", "mc:AlternateContent", "c:externalData"}
# Falls ein Verweis außerhalb dieser Container steht (Hintergrund, Bildfüllung,
# VML): das erste passende umgebende Element entfernen, in dieser Rangfolge
FALLBACK_CONTAINERS = ("p:bg", "a:blipFill", "picture", "v:fill", "v:imagedata", "o:OLEObject", "a:blip")
# Attribute mit Personennamen: leeren (None = an jedem Element)
BLANK_ATTRS = {(None, "w:author"), (None, "w:initials"), ("w15:person", "w15:author"),
               ("w15:presenceInfo", "w15:userId"), ("w15:presenceInfo", "w15:providerId"),
               ("p:cmAuthor", "name"), ("p:cmAuthor", "initials"), ("p188:author", "name"),
               ("p188:author", "initials"), ("p188:author", "userId"), ("person", "displayName"),
               ("person", "userId"), ("person", "providerId")}
# Attribute mit freiem Text: bereinigen
TEXT_ATTRS = {("w:fldSimple", "w:instr"), ("worksheetSource", "sheet"), ("wp:docPr", "descr"), ("wp:docPr", "title"), ("wp:docPr", "name"),
              ("pic:cNvPr", "descr"), ("pic:cNvPr", "title"), ("pic:cNvPr", "name"), ("p:cNvPr", "descr"),
              ("p:cNvPr", "title"), ("p:cNvPr", "name"), ("xdr:cNvPr", "descr"), ("xdr:cNvPr", "title"),
              ("xdr:cNvPr", "name"), ("w:hyperlink", "w:tooltip"), ("hyperlink", "display"),
              ("hyperlink", "tooltip"), ("sheet", "name")}
SHEET_NAME_FORBIDDEN = re.compile(r"[\[\]:*?/\\]")


def sheet_name_form(name: str) -> str:
    """Excel-taugliche Schreibweise eines bereinigten Blattnamens:
    [HOSTNAME_1] -> (HOSTNAME_1), sonstige verbotene Zeichen -> _, max. 31 Zeichen."""
    return SHEET_NAME_FORBIDDEN.sub(lambda m: {"[": "(", "]": ")"}.get(m.group(), "_"), name)[:31]


def fix_sheet_refs(formula: str) -> str:
    """Blattverweise in einer bereinigten Formel an die Schreibweise der
    umbenannten Blätter anpassen ('[HOSTNAME_1]'!B1 -> '(HOSTNAME_1)'!B1).
    Externe Verweise wie [1]Blatt!A1 bleiben unverändert."""
    def quoted(m):
        inner = m.group(1)
        if not PLACEHOLDER_RE.search(inner):
            return m.group()
        return "'" + PLACEHOLDER_RE.sub(lambda p: "(" + p.group()[1:-1] + ")", inner) + "'!"

    def unquoted(m):
        inner = m.group(1)
        if not PLACEHOLDER_RE.search(inner):
            return m.group()
        return "'" + PLACEHOLDER_RE.sub(lambda p: "(" + p.group()[1:-1] + ")", inner) + "'!"

    return _UNQUOTED_SHEET_REF.sub(unquoted, _QUOTED_SHEET_REF.sub(quoted, formula))


class OfficeError(Exception):
    """Dokument kann nicht verarbeitet werden. Meldung ohne Inhalte."""


def office_kind(name: str) -> str | None:
    return OFFICE_KINDS.get(Path(name).suffix.lower())


def is_macro_document(name: str) -> bool:
    return name.lower().endswith(MACRO_SUFFIXES)


@dataclass
class OfficeResult:
    counts: dict = field(default_factory=dict)
    removed_media: int = 0
    samples: list = field(default_factory=list)

    @property
    def note(self) -> str:
        return t("office.removed_media", n=self.removed_media) if self.removed_media else ""


# ----------------------------------------------------------------------
# XML auf Textebene
# ----------------------------------------------------------------------

@dataclass
class _Tok:
    raw: str
    tag: bool
    name: str = ""
    kind: str = ""   # start, end, empty, other (Deklaration, Kommentar)


def _tokenize(xml: str) -> list[_Tok]:
    if "<!DOCTYPE" in xml or "<!ENTITY" in xml:
        raise OfficeError(t("office.doctype"))
    toks: list[_Tok] = []
    pos = 0
    for m in _TAG_RE.finditer(xml):
        if m.start() > pos:
            toks.append(_Tok(xml[pos:m.start()], False))
        raw = m.group()
        if raw.startswith(("<?", "<!")):
            toks.append(_Tok(raw, True, "", "other"))
        else:
            name_match = _NAME_RE.match(raw)
            name = name_match.group(1) if name_match else ""
            kind = "end" if raw.startswith("</") else ("empty" if raw.endswith("/>") else "start")
            toks.append(_Tok(raw, True, name, kind))
        pos = m.end()
    if pos < len(xml):
        toks.append(_Tok(xml[pos:], False))
    return toks


def _spans(toks: list[_Tok]) -> dict[int, int]:
    """Start-Index -> End-Index jedes Elements (bei leeren Elementen gleich)."""
    spans: dict[int, int] = {}
    stack: list[int] = []
    for i, t in enumerate(toks):
        if not t.tag:
            continue
        if t.kind == "start":
            stack.append(i)
        elif t.kind == "end":
            if not stack:
                raise OfficeError(t("office.xml_malformed"))
            spans[stack.pop()] = i
        elif t.kind == "empty":
            spans[i] = i
    if stack:
        raise OfficeError(t("office.xml_malformed"))
    return spans


def _restructure(toks: list[_Tok], removed_rids: set) -> list[_Tok]:
    """Nimmt nachverfolgte Änderungen an und entfernt Grafiken, die auf
    entfernte Bilder/Objekte zeigen. Bleibt danach ein solcher Verweis übrig,
    wird abgebrochen: lieber keine Ausgabe als ein beschädigtes Dokument."""
    spans = _spans(toks)
    skip = [False] * len(toks)

    def drop(i: int) -> None:
        for k in range(i, spans[i] + 1):
            skip[k] = True

    def refers_removed(i: int) -> bool:
        inner = "".join(x.raw for x in toks[i:spans[i] + 1] if x.tag)
        return any(rid in removed_rids for rid in _RID_RE.findall(inner))

    for i, t in enumerate(toks):
        if skip[i] or not t.tag or t.kind not in ("start", "empty"):
            continue
        if t.name in DROP_TAGS or (t.name in MEDIA_CONTAINERS and removed_rids and refers_removed(i)):
            drop(i)
        elif t.name in UNWRAP_TAGS:
            skip[i] = skip[spans[i]] = True

    if removed_rids:
        # Verweise außerhalb der bekannten Container (Hintergründe, Füllungen, VML)
        stack: list[int] = []
        for i, t in enumerate(toks):
            if not t.tag:
                continue
            if t.kind == "end":
                if stack:
                    stack.pop()
                continue
            if t.kind == "start":
                stack.append(i)
            if skip[i] or not any(rid in removed_rids for rid in _RID_RE.findall(t.raw)):
                continue
            chain = stack if t.kind == "start" else stack + [i]
            for name in FALLBACK_CONTAINERS:
                owner = next((k for k in chain if toks[k].name == name and not skip[k]), None)
                if owner is not None:
                    drop(owner)
                    break
        remaining = [rid for k, t in enumerate(toks) if t.tag and not skip[k]
                     for rid in _RID_RE.findall(t.raw) if rid in removed_rids]
        if remaining:
            raise OfficeError(t("office.dangling_reference"))
    return [t for k, t in enumerate(toks) if not skip[k]]


def _unescape(text: str) -> str:
    return html.unescape(text)


def _escape_text(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _escape_attr(text: str) -> str:
    return _escape_text(text).replace('"', "&quot;").replace("'", "&apos;")


def _attr_value(raw: str, attr: str) -> str | None:
    for m in _ATTR_RE.finditer(raw):
        if m.group(2) == attr:
            return _unescape(m.group(5))
    return None


class _PartProcessor:
    """Bearbeitet einen XML-Teil: sammelt Texte (lernen) oder ersetzt sie."""

    def __init__(self, sanitizer, exclude, counts: dict | None, samples: list | None, sheet_names: set | None):
        self.all_text = False   # customXml: jeder Text zählt (Elementnamen frei wählbar)
        self.sanitizer = sanitizer
        self.exclude = exclude
        self.counts = counts
        self.samples = samples
        self.sheet_names = sheet_names if sheet_names is not None else set()

    # -- ein Text (Attribut, Link-Ziel): lernen oder ersetzen --
    def text(self, value: str, learn: bool) -> str:
        if not value.strip():
            return value
        if learn:
            self.sanitizer.learn(value, self.exclude)
            return value
        findings = self.sanitizer.analyze(value, self.exclude)
        if not findings:
            return value
        result = apply_replacements(value, findings, self.sanitizer.mapping)
        self._count(result)
        return result.text

    def _count(self, result) -> None:
        if self.counts is None:
            return
        for rep in result.replacements:
            self.counts[rep.category] = self.counts.get(rep.category, 0) + 1
        if self.samples is not None and result.replacements and len(self.samples) < 12:
            for line in result.text.split("\n"):
                if "[" in line and line.strip() and line not in self.samples:
                    self.samples.append(line[:200])
                    break

    def _attrs(self, tok: _Tok, learn: bool) -> None:
        def repl(m):
            name, value = m.group(2), _unescape(m.group(5))
            if (None, name) in BLANK_ATTRS or (tok.name, name) in BLANK_ATTRS:
                new = ""
            elif (tok.name, name) in TEXT_ATTRS:
                new = self.text(value, learn)
                if tok.name == "sheet" and new != value:
                    new = self._sheet_name(new)
                elif tok.name == "worksheetSource" and new != value:
                    new = sheet_name_form(new)
            elif tok.name == "Relationship" and name == "Target" and "External" in (_attr_value(tok.raw, "TargetMode") or ""):
                new = self.text(value, learn)
            else:
                return m.group()
            if learn or new == value:
                return m.group()
            return f"{m.group(1)}{name}{m.group(3)}{m.group(4)}{_escape_attr(new)}{m.group(4)}"

        if tok.tag and tok.kind in ("start", "empty") and "=" in tok.raw:
            new_raw = _ATTR_RE.sub(repl, tok.raw)
            if new_raw != tok.raw:
                tok.raw = new_raw

    def _sheet_name(self, name: str) -> str:
        """Gültiger, eindeutiger Excel-Blattname (max. 31 Zeichen, ohne []:*?/\\)."""
        name = sheet_name_form(name).strip("'")
        base, n = name or "Blatt", 2
        while name.casefold() in self.sheet_names:
            suffix = f" {n}"
            name, n = base[:31 - len(suffix)] + suffix, n + 1
        self.sheet_names.add(name.casefold())
        return name

    # -- ganzer Teil --
    def process(self, toks: list[_Tok], learn: bool) -> list[_Tok]:
        stack: list[_Tok] = []
        nodes: list[tuple[int, int, bool]] = []   # (Token-Index, Absatz-Nr., ist Formel)
        blank: list[int] = []
        para = 0
        for i, t in enumerate(toks):
            if t.tag:
                self._attrs(t, learn)
                if t.kind == "start":
                    stack.append(t)
                    if t.name in PARA_TAGS:
                        para += 1
                elif t.kind == "end" and stack:
                    stack.pop()
                    if t.name in PARA_TAGS:
                        para += 1
                continue
            if not stack or not t.raw:
                continue
            parent = stack[-1].name
            if parent in BLANK_TEXT_TAGS:
                blank.append(i)
            elif parent in FORMULA_TAGS:
                para += 1   # jede Formel für sich
                nodes.append((i, para, True))
                para += 1
            elif self.all_text or self._is_text(parent, stack):
                nodes.append((i, para, False))
        if not learn:
            for i in blank:
                toks[i].raw = ""
        if nodes:
            self._texts(toks, nodes, learn)
        return toks

    @staticmethod
    def _is_text(parent: str, stack: list[_Tok]) -> bool:
        if parent in TEXT_TAGS:
            if parent == "t":   # Excel: nur in Zeichenketten (si, is, Kommentar-Text)
                return any(s.name in ("si", "is", "text") for s in stack)
            return True
        if parent == "v":       # Excel: zwischengespeichertes Formelergebnis vom Typ Text
            cell = next((s for s in reversed(stack) if s.name == "c"), None)
            return cell is not None and _attr_value(cell.raw, "t") == "str"
        if parent == "c:v":     # Diagramm: Beschriftungen und Kategorien
            return any(s.name in ("c:strCache", "c:strLit") for s in stack)
        return False

    def _texts(self, toks: list[_Tok], nodes, learn: bool) -> None:
        # Alle Texte des Teils zusammensetzen, Absätze durch \n getrennt
        parts, offsets = [], []
        pos, last_para = 0, None
        formulas = {i for i, _para, is_formula in nodes if is_formula}
        for i, para, _is_formula in nodes:
            if last_para is not None and para != last_para:
                parts.append("\n")
                pos += 1
            value = _unescape(toks[i].raw)
            offsets.append((i, pos, value))
            parts.append(value)
            pos += len(value)
            last_para = para
        joined = "".join(parts)
        if learn:
            self.sanitizer.learn(joined, self.exclude)
            return
        findings = self.sanitizer.analyze(joined, self.exclude)
        if not findings:
            return
        result = apply_replacements(joined, findings, self.sanitizer.mapping)
        self._count(result)
        new_values = {i: list(value) for i, _start, value in offsets}
        for rep in result.replacements:
            placed = False
            for i, start, value in offsets:
                lo, hi = max(rep.start, start), min(rep.end, start + len(value))
                if lo >= hi:
                    continue
                chars = new_values[i]
                for k in range(lo - start, hi - start):
                    chars[k] = ""
                if not placed:   # Platzhalter in das erste betroffene Textstück
                    chars[lo - start] = rep.placeholder
                    placed = True
        for i, _start, value in offsets:
            new = "".join(new_values[i])
            if i in formulas and new != value:
                new = fix_sheet_refs(new)
            if new != value:
                toks[i].raw = _escape_text(new)


# ----------------------------------------------------------------------
# Dokument
# ----------------------------------------------------------------------

def _removable(name: str) -> bool:
    lower = name.lower()
    return ("/media/" in f"/{lower}" or "/embeddings/" in f"/{lower}" or "/activex/" in f"/{lower}"
            or lower.startswith("docprops/thumbnail") or lower.endswith(".bin"))


def _rels_source(rels_name: str) -> str:
    """word/_rels/document.xml.rels -> word/document.xml"""
    folder, _, base = rels_name.rpartition("_rels/")
    return folder + base[:-len(".rels")]


def _resolve(source_part: str, target: str) -> str:
    if target.startswith("/"):
        return target.lstrip("/")
    return posixpath.normpath(posixpath.join(posixpath.dirname(source_part), target))


def _read_parts(src: Path, max_total: int, max_part: int) -> list[tuple[zipfile.ZipInfo, bytes]]:
    try:
        with zipfile.ZipFile(src) as zf:
            infos = zf.infolist()
            if sum(i.file_size for i in infos) > max_total:
                raise OfficeError(t("office.too_large"))
            parts = []
            for info in infos:
                if info.file_size > max_part:
                    raise OfficeError(t("office.part_too_large"))
                if info.flag_bits & 0x1:
                    raise OfficeError(t("office.encrypted"))
                parts.append((info, zf.read(info)))
            return parts
    except zipfile.BadZipFile:
        raise OfficeError(t("office.invalid_or_encrypted")) from None


def _decode(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            return data.decode("utf-16")
        except UnicodeDecodeError:
            raise OfficeError(t("office.xml_encoding")) from None


def _is_xml(name: str) -> bool:
    return name.lower().endswith((".xml", ".rels", ".vml"))


def process_document(sanitizer, src: Path, settings, exclude=(), dest: Path | None = None,
                     learn: bool = False) -> OfficeResult:
    """Lernen (learn=True), nur zählen (dest=None) oder bereinigt nach dest schreiben."""
    max_part = int(settings.max_file_size_mb * 1024 * 1024)
    max_total = int(settings.max_archive_mb * 1024 * 1024)
    parts = _read_parts(Path(src), max_total, max_part)
    names = {info.filename for info, _ in parts}
    if "[Content_Types].xml" not in names:
        raise OfficeError(t("office.invalid"))
    remove_media = getattr(settings, "office_remove_media", True)
    removed_parts = {n for n in names if remove_media and _removable(n)}

    # Beziehungen zu entfernten Teilen: rId je Quell-Teil
    removed_rids: dict[str, set] = {}
    for info, data in parts:
        if info.filename.endswith(".rels") and removed_parts:
            source = _rels_source(info.filename)
            for m in re.finditer(r"<Relationship\b[^>]*>", _decode(data)):
                rid, target = _attr_value(m.group(), "Id"), _attr_value(m.group(), "Target") or ""
                mode = _attr_value(m.group(), "TargetMode") or ""
                if rid and mode != "External" and _resolve(source, target) in removed_parts:
                    removed_rids.setdefault(source, set()).add(rid)

    result = OfficeResult(counts={} if not learn else None, samples=[] if not learn else None)
    sheet_names: set = set()
    processor = _PartProcessor(sanitizer, tuple(exclude), result.counts, result.samples, sheet_names)
    output: list[tuple[zipfile.ZipInfo, bytes]] = []
    for info, data in parts:
        name = info.filename
        if name in removed_parts:
            continue
        if not _is_xml(name):
            output.append((info, data))
            continue
        toks = _tokenize(_decode(data))
        if name.endswith(".rels"):
            toks = _drop_relationships(toks, removed_rids.get(_rels_source(name), set()))
        elif name == "[Content_Types].xml":
            toks = _drop_overrides(toks, removed_parts)
        else:
            toks = _restructure(toks, removed_rids.get(name, set()))
        processor.all_text = name.lower().startswith("customxml/item")
        toks = processor.process(toks, learn)
        if not learn:
            output.append((info, "".join(t.raw for t in toks).encode("utf-8")))
    if not learn:
        result.removed_media = len([n for n in removed_parts if "printersettings" not in n.lower()])
    if dest is not None and not learn:
        _write_zip(output, Path(dest))
    return result


def _drop_relationships(toks: list[_Tok], rids: set) -> list[_Tok]:
    if not rids:
        return toks
    return [t for t in toks if not (t.tag and t.name == "Relationship" and _attr_value(t.raw, "Id") in rids)]


def _drop_overrides(toks: list[_Tok], removed_parts: set) -> list[_Tok]:
    if not removed_parts:
        return toks
    return [t for t in toks if not (t.tag and t.name == "Override"
                                    and (_attr_value(t.raw, "PartName") or "").lstrip("/") in removed_parts)]


def _write_zip(parts, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".tmp_office")
    try:
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for info, data in parts:
                new = zipfile.ZipInfo(info.filename, date_time=info.date_time)
                new.compress_type = zipfile.ZIP_DEFLATED
                new.external_attr = info.external_attr
                zf.writestr(new, data)
        tmp.replace(dest)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
