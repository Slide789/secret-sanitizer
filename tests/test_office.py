"""Tests für Word, Excel und PowerPoint (office.py).

Die Testdokumente werden hier aus minimalem, gültigem OOXML gebaut (kein
Office nötig). Geprüft wird jeweils: keine Secrets mehr in irgendeinem Teil,
Bilder samt Verweisen entfernt, alle Verweise konsistent, XML wohlgeformt.
"""

import posixpath
import re
import unittest
import zipfile
from pathlib import Path
from xml.dom import minidom

from tests.helpers import SECRETS, SecretAssertions, TempDirTestCase, make_sanitizer

from secret_sanitizer.core import office
from secret_sanitizer.core.files import REPORT_NAME, FileRun

S = SECRETS
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
R = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
A = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
P = 'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG = '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{}</Relationships>'


def rel(rid, target, kind="officeDocument", external=False):
    mode = ' TargetMode="External"' if external else ""
    return f'<Relationship Id="{rid}" Type="{REL}/{kind}" Target="{target}"{mode}/>'


def content_types(*overrides):
    items = "".join(f'<Override PartName="/{p}" ContentType="application/xml"/>' for p in overrides)
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="xml" ContentType="application/xml"/><Default Extension="png" ContentType="image/png"/>'
            f'{items}</Types>')


def core_xml():
    return ('<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/">'
            f'<dc:title>Zugang {S["hostname"]}</dc:title><dc:creator>{S["person"]}</dc:creator>'
            f'<cp:lastModifiedBy>{S["person"]}</cp:lastModifiedBy></cp:coreProperties>')


def build(path: Path, parts: dict) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in parts.items():
            zf.writestr(name, data)
    return path


def docx_parts():
    pw = S["db_password"]
    body = (
        f'<w:p><w:r><w:t xml:space="preserve">Server {S["hostname"]}, Passwort: </w:t></w:r>'
        f'<w:r><w:rPr><w:b/></w:rPr><w:t>{pw[:5]}</w:t></w:r><w:r><w:t>{pw[5:]}</w:t></w:r></w:p>'
        f'<w:p><w:del w:id="1" w:author="{S["person"]}"><w:r><w:delText>alt: {S["github"]}</w:delText></w:r></w:del>'
        f'<w:ins w:id="2" w:author="{S["person"]}"><w:r><w:t>Kontakt {S["email"]}</w:t></w:r></w:ins></w:p>'
        '<w:p><w:r><w:drawing><wp:inline xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing">'
        f'<wp:docPr id="1" name="Bild" descr="Screenshot {S["hostname"]}"/><a:graphic {A}><a:graphicData>'
        '<a:blip r:embed="rId5"/></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>'
        '<w:p><w:hyperlink r:id="rId6"><w:r><w:t>Portal</w:t></w:r></w:hyperlink></w:p>'
        '<w:p><w:r><w:t>Tom &amp; Jerry &lt;ok&gt;</w:t></w:r></w:p>'
    )
    return {
        "[Content_Types].xml": content_types("word/document.xml", "word/comments.xml", "docProps/core.xml"),
        "_rels/.rels": PKG.format(rel("rId1", "word/document.xml") + rel("rId2", "docProps/core.xml", "core")
                                  + rel("rId3", "docProps/thumbnail.png", "thumbnail")),
        "word/document.xml": f'<?xml version="1.0"?><w:document {W} {R}><w:body>{body}</w:body></w:document>',
        "word/_rels/document.xml.rels": PKG.format(
            rel("rId5", "media/image1.png", "image")
            + rel("rId6", f"https://{S['hostname']}/x?token={S['github']}", "hyperlink", external=True)),
        "word/comments.xml": (f'<w:comments {W}><w:comment w:id="0" w:author="{S["person"]}" w:initials="EM">'
                              f'<w:p><w:r><w:t>Bitte {S["db_password"]} ändern</w:t></w:r></w:p></w:comment></w:comments>'),
        "word/media/image1.png": PNG,
        "docProps/core.xml": core_xml(),
        "docProps/thumbnail.png": PNG,
        "customXml/item1.xml": f"<daten><kennwort>{S['db_password']}</kennwort></daten>",
    }


def xlsx_parts():
    host = S["hostname"]
    return {
        "[Content_Types].xml": content_types("xl/workbook.xml", "xl/worksheets/sheet1.xml", "xl/sharedStrings.xml"),
        "_rels/.rels": PKG.format(rel("rId1", "xl/workbook.xml")),
        "xl/workbook.xml": (
            f'<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" {R}><sheets>'
            f'<sheet name="{host}" sheetId="1" r:id="rId1"/><sheet name="Normal" sheetId="2" r:id="rId2"/></sheets>'
            f"<definedNames><definedName name=\"_xlnm.Print_Area\" localSheetId=\"0\">'{host}'!$A$1:$B$2"
            "</definedName></definedNames></workbook>"),
        "xl/_rels/workbook.xml.rels": PKG.format(rel("rId1", "worksheets/sheet1.xml", "worksheet")
                                                 + rel("rId2", "worksheets/sheet2.xml", "worksheet")),
        "xl/sharedStrings.xml": (
            '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f'<si><t>{S["email"]}</t></si><si><r><t>password=</t></r><r><rPr><b/></rPr><t>{S["db_password"]}</t></r></si>'
            '</sst>'),
        "xl/worksheets/sheet1.xml": (
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
            '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c><c r="C1"><v>42</v></c></row>'
            f'<row r="2"><c r="A2" t="str"><f>"Token: {S["github"]}"</f><v>Token: {S["github"]}</v></c></row>'
            '</sheetData></worksheet>'),
        "xl/worksheets/sheet2.xml": (
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
            f"<row r=\"1\"><c r=\"A1\" t=\"str\"><f>'{host}'!B1&amp;\"x\"</f><v>y</v></c></row>"
            '</sheetData></worksheet>'),
        "xl/comments1.xml": (
            '<comments xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f'<authors><author>{S["person"]}</author></authors><commentList><comment ref="B1" authorId="0">'
            f'<text><r><t>Admin {S["email"]}</t></r></text></comment></commentList></comments>'),
    }


def pptx_parts():
    slide = (
        f'<p:sld {P} {A} {R}><p:cSld><p:bg><p:bgPr><a:blipFill><a:blip r:embed="rId3"/></a:blipFill></p:bgPr></p:bg>'
        f'<p:spTree><p:sp><p:txBody><a:p><a:r><a:t>Migration {S["hostname"]}</a:t></a:r></a:p>'
        f'<a:p><a:r><a:t>Passwort: {S["db_password"]}</a:t></a:r></a:p></p:txBody></p:sp>'
        '<p:pic><p:nvPicPr><p:cNvPr id="4" name="Bild"/></p:nvPicPr><p:blipFill><a:blip r:embed="rId2"/></p:blipFill></p:pic>'
        '</p:spTree></p:cSld></p:sld>')
    return {
        "[Content_Types].xml": content_types("ppt/slides/slide1.xml"),
        "_rels/.rels": PKG.format(rel("rId1", "ppt/presentation.xml")),
        "ppt/presentation.xml": f"<p:presentation {P}/>",
        "ppt/slides/slide1.xml": slide,
        "ppt/slides/_rels/slide1.xml.rels": PKG.format(rel("rId2", "../media/image1.png", "image")
                                                       + rel("rId3", "../media/image2.png", "image")),
        "ppt/media/image1.png": PNG,
        "ppt/media/image2.png": PNG,
        "ppt/commentAuthors.xml": f'<p:cmAuthorLst {P}><p:cmAuthor id="1" name="{S["person"]}" initials="EM"/></p:cmAuthorLst>',
    }


class OfficeTests(SecretAssertions, TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.input = self.tmp / "eingabe"
        self.input.mkdir()

    def run_folder(self, **kwargs):
        return FileRun(make_sanitizer(**kwargs)).run(self.input, output_dir=self.tmp / "aus")

    def assert_clean_package(self, path: Path, extra_needles=()):
        """Kein Secret in keinem Teil, keine Binärteile, alle Verweise gültig, XML wohlgeformt."""
        with zipfile.ZipFile(path) as zf:
            names = set(zf.namelist())
            for name in names:
                data = zf.read(name)
                self.assertFalse(name.endswith(".png"), f"Bild übrig: {name}")
                text = data.decode("utf-8")
                self.assertNoSecrets(text, msg=f"{path.name}:{name}")
                for needle in extra_needles:
                    self.assertNotIn(needle, text, f"{path.name}:{name}")
                if name.endswith((".xml", ".rels")):
                    minidom.parseString(data)
            for name in names:
                if not name.endswith(".rels"):
                    continue
                folder, _, base = name.rpartition("_rels/")
                source = folder + base[:-5]
                rels = zf.read(name).decode()
                for m in re.finditer(r"<Relationship [^>]*>", rels):
                    if "External" in m.group():
                        continue
                    target = re.search(r'Target="([^"]+)"', m.group()).group(1)
                    resolved = posixpath.normpath(posixpath.join(posixpath.dirname(source), target))
                    self.assertIn(resolved, names, f"{name}: Ziel fehlt")
                if source in names:
                    used = set(re.findall(r'\sr:(?:id|embed|link)="([^"]+)"', zf.read(source).decode()))
                    self.assertLessEqual(used, set(re.findall(r'Id="([^"]+)"', rels)), source)
            return {n: zf.read(n).decode("utf-8") for n in names}

    def test_docx(self):
        build(self.input / "bericht.docx", docx_parts())
        (self.input / "notiz.txt").write_text(f"Server {S['hostname']}\n", encoding="utf-8")
        report, out = self.run_folder()
        entry = next(e for e in report.entries if e.rel_path == "bericht.docx")
        self.assertEqual(entry.status, "processed", entry.reason)
        self.assertEqual(entry.note, "2 Bild(er)/Objekt(e) entfernt")
        parts = self.assert_clean_package(out / "bericht.docx", [S["person"], "EM\""])
        doc = parts["word/document.xml"]
        self.assertNotIn("w:del", doc)            # Änderungen angenommen: gelöschter Text ist weg
        self.assertNotIn("w:ins", doc)
        self.assertIn("Kontakt [EMAIL_1]", doc)   # eingefügter Text bleibt (bereinigt)
        self.assertNotIn("w:drawing", doc)
        # Passwort über zwei Runs (fett + normal): Platzhalter im ersten betroffenen Stück, das zweite leer
        self.assertIn("Passwort: </w:t></w:r><w:r><w:rPr><w:b/></w:rPr><w:t>[PASSWORD_1]</w:t></w:r>"
                      "<w:r><w:t></w:t></w:r>", doc)
        self.assertIn("Tom &amp; Jerry &lt;ok&gt;", doc)   # Escapes unverändert
        self.assertNotIn("thumbnail", parts["_rels/.rels"])
        self.assertIn('w:author=""', parts["word/comments.xml"])
        self.assertIn("<dc:creator></dc:creator>", parts["docProps/core.xml"])
        self.assertIn("[PASSWORD_", parts["customXml/item1.xml"])
        # gleicher Host in der Textdatei -> gleicher Platzhalter (gemeinsames Mapping)
        placeholder = re.search(r"Server (\[HOSTNAME_\d+\])", doc).group(1)
        self.assertIn(placeholder, (out / "notiz.txt").read_text(encoding="utf-8"))
        self.assertIn("Bild(er)/Objekt(e) entfernt", (out / REPORT_NAME).read_text(encoding="utf-8"))

    def test_xlsx_sheet_names_and_formulas(self):
        build(self.input / "tabelle.xlsx", xlsx_parts())
        report, out = self.run_folder()
        self.assertEqual(report.entries[0].status, "processed", report.entries[0].reason)
        parts = self.assert_clean_package(out / "tabelle.xlsx", [S["person"]])
        wb = parts["xl/workbook.xml"]
        sheet = re.search(r'<sheet name="([^"]+)" sheetId="1"', wb).group(1)
        self.assertRegex(sheet, r"^\(HOSTNAME_\d+\)$")             # gültiger Excel-Blattname
        self.assertIn(f"'{sheet}'!$A$1:$B$2", wb)                  # Druckbereich passt dazu
        self.assertIn(f"'{sheet}'!B1", parts["xl/worksheets/sheet2.xml"])   # Formel auf anderem Blatt
        self.assertIn("<v>42</v>", parts["xl/worksheets/sheet1.xml"])       # Zahlen unverändert
        self.assertIn("<author></author>", parts["xl/comments1.xml"])

    def test_pptx_background_and_pictures(self):
        build(self.input / "folien.pptx", pptx_parts())
        report, out = self.run_folder()
        self.assertEqual(report.entries[0].status, "processed", report.entries[0].reason)
        parts = self.assert_clean_package(out / "folien.pptx", [S["person"]])
        slide = parts["ppt/slides/slide1.xml"]
        self.assertNotIn("p:pic", slide)
        self.assertNotIn("p:bg", slide)
        self.assertIn("Migration [HOSTNAME_1]", slide)
        self.assertIn('name=""', parts["ppt/commentAuthors.xml"])

    def test_keep_media_option(self):
        build(self.input / "folien.pptx", pptx_parts())
        _, out = self.run_folder(office_remove_media=False)
        with zipfile.ZipFile(out / "folien.pptx") as zf:
            self.assertIn("ppt/media/image1.png", zf.namelist())
            self.assertIn("p:pic", zf.read("ppt/slides/slide1.xml").decode())

    def test_rejects_dangerous_and_broken_files(self):
        parts = docx_parts()
        parts["word/document.xml"] = '<!DOCTYPE x [<!ENTITY a "aaaa">]><w:document/>'
        build(self.input / "doctype.docx", parts)
        (self.input / "kaputt.docx").write_bytes(b"PK\x03\x04 kaputt")
        build(self.input / "makro.docm", docx_parts())
        report, out = self.run_folder()
        status = {e.rel_path: (e.status, e.reason) for e in report.entries}
        self.assertEqual(status["doctype.docx"], ("failed", "Dokument enthält eine DOCTYPE-Deklaration (nicht erlaubt)"))
        self.assertEqual(status["kaputt.docx"][0], "failed")
        self.assertEqual(status["makro.docm"], ("skipped", "Dokument mit Makros (nicht unterstützt)"))
        self.assertFalse((out / "doctype.docx").exists())
        self.assertFalse((out / "makro.docm").exists())

    def test_size_limit(self):
        parts = docx_parts()
        parts["word/media/gross.png"] = b"0" * 300_000
        build(self.input / "gross.docx", parts)
        report, _ = self.run_folder(max_archive_mb=0.2)
        self.assertIn("max_archive_mb", report.entries[0].reason)

    def test_office_off_and_check_mode(self):
        build(self.input / "bericht.docx", docx_parts())
        report, _ = self.run_folder(process_office=False)
        self.assertEqual(report.entries[0].reason, "Binärdatei")
        report, _ = FileRun(make_sanitizer()).run(self.input, output_dir=self.tmp / "nie", dry_run=True)
        self.assertTrue(report.entries[0].counts.get("PASSWORD"))
        self.assertFalse((self.tmp / "nie").exists())

    def test_fix_sheet_refs(self):
        f = office.fix_sheet_refs
        self.assertEqual(f("'[HOSTNAME_1]'!B1"), "'(HOSTNAME_1)'!B1")
        self.assertEqual(f("[HOSTNAME_1]!B1"), "'(HOSTNAME_1)'!B1")
        self.assertEqual(f("SUM('Server [IP_2]'!A1)+[1]Extern!A1"), "SUM('Server (IP_2)'!A1)+[1]Extern!A1")
        self.assertEqual(f('IF(A1="[PASSWORD_1]",1,0)'), 'IF(A1="[PASSWORD_1]",1,0)')


if __name__ == "__main__":
    unittest.main()
