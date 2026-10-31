"""Tests für PDF -> bereinigte .txt (pdf.py). Braucht das Paket pypdf."""

import multiprocessing
import sys
import time
import unittest
import zlib
from pathlib import Path

from tests.helpers import SECRETS, SecretAssertions, TempDirTestCase, make_sanitizer

from secret_sanitizer.core import pdf
from secret_sanitizer.core.files import FileRun

S = SECRETS


def make_pdf(path: Path, lines: list[str]) -> Path:
    """Minimale, gültige PDF mit einer Seite Text (Helvetica)."""
    def esc(text):
        return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    stream = "BT /F1 11 Tf 50 780 Td " + " ".join(f"({esc(line)}) Tj 0 -16 Td" for line in lines) + " ET"
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 5 0 R >> >> "
        "/Contents 4 0 R >>",
        f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = "%PDF-1.4\n"
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out.encode("latin-1")))
        out += f"{number} 0 obj\n{body}\nendobj\n"
    xref = len(out.encode("latin-1"))
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n"
    out += "".join(f"{o:010d} 00000 n \n" for o in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n"
    path.write_bytes(out.encode("latin-1"))
    return path


def _allocate(conn) -> None:
    """Kindprozess für den Job-Objekt-Test: wartet auf das Signal, belegt dann 300 MB."""
    conn.recv()
    try:
        block = bytearray(300 * 1024 * 1024)
        conn.send(f"ok {len(block)}")
    except MemoryError:
        conn.send("MemoryError")


@unittest.skipUnless(pdf.available(), "pypdf nicht installiert")
class PdfTests(SecretAssertions, TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.input = self.tmp / "eingabe"
        self.input.mkdir()

    def run_folder(self, **kwargs):
        return FileRun(make_sanitizer(**kwargs)).run(self.input, output_dir=self.tmp / "aus")

    def test_pdf_to_sanitized_text(self):
        make_pdf(self.input / "bericht.pdf", [f"Server {S['hostname']}", f"password={S['db_password']}",
                                              f"Kontakt {S['email']}"])
        (self.input / "bericht.txt").write_text(f"auch {S['hostname']}\n", encoding="utf-8")
        report, out = self.run_folder()
        entry = next(e for e in report.entries if e.rel_path == "bericht.pdf")
        self.assertEqual((entry.status, entry.encoding), ("processed", "pdf"), entry.reason)
        self.assertEqual(entry.counts, {"EMAIL": 1, "HOSTNAME": 1, "PASSWORD": 1})
        text = (out / "bericht.pdf.txt").read_text(encoding="utf-8")
        self.assertNoSecrets(text)
        self.assertIn("password=[PASSWORD_1]", text)
        self.assertFalse((out / "bericht.pdf").exists())     # die PDF selbst wird nicht ausgegeben
        # gleicher Platzhalter wie in der Textdatei daneben
        self.assertIn("auch [HOSTNAME_1]", (out / "bericht.txt").read_text(encoding="utf-8"))
        self.assertEqual(report.stale, [])

    def test_skipped_and_failed(self):
        make_pdf(self.input / "leer.pdf", [])
        (self.input / "kaputt.pdf").write_bytes(b"%PDF-1.4\nkein echtes pdf")
        from pypdf import PdfReader, PdfWriter
        writer = PdfWriter()
        writer.append(PdfReader(make_pdf(self.tmp / "offen.pdf", [f"password={S['db_password']}"])))
        writer.encrypt(user_password="geheim", algorithm="RC4-128")
        with open(self.input / "verschluesselt.pdf", "wb") as fh:
            writer.write(fh)
        report, out = self.run_folder()
        status = {e.rel_path: (e.status, e.reason) for e in report.entries}
        self.assertEqual(status["leer.pdf"], ("skipped", "kein Text in der PDF (gescannt?)"))
        self.assertEqual(status["verschluesselt.pdf"], ("skipped", "PDF ist mit Kennwort verschlüsselt"))
        self.assertEqual(status["kaputt.pdf"][0], "failed")
        self.assertIn("PDF beschädigt", status["kaputt.pdf"][1])
        self.assertFalse(list(out.glob("*.pdf.txt")))

    def test_timeout(self):
        path = make_pdf(self.input / "a.pdf", [f"password={S['db_password']}"])
        settings = make_sanitizer().settings
        settings.pdf_timeout_s = 0.001   # unter jedem sinnvollen Wert, nur für den Test
        with self.assertRaises(pdf.PdfError) as ctx:
            pdf.extract_text(path, settings)
        self.assertIn("Zeitlimit", str(ctx.exception))

    def test_decompression_bomb_fails_safely(self):
        # Winziger Datenstrom, der entpackt 300 MB groß wäre
        bomb = zlib.compress(b"0" * 300_000_000, 9)
        path = self.input / "bombe.pdf"
        head = ("%PDF-1.4\n1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
                "2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n"
                "3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R >> endobj\n"
                f"4 0 obj << /Length {len(bomb)} /Filter /FlateDecode >>\nstream\n").encode()
        path.write_bytes(head + bomb + b"\nendstream endobj\ntrailer << /Root 1 0 R >>\n%%EOF\n")
        start = time.time()
        report, out = self.run_folder(pdf_max_memory_mb=150)
        self.assertEqual(report.entries[0].status, "failed", report.entries[0].reason)
        self.assertLess(time.time() - start, 30)
        self.assertFalse(list(out.glob("bombe*")))

    @unittest.skipUnless(sys.platform.startswith("win"), "Job-Objekte gibt es nur unter Windows")
    def test_windows_job_memory_limit(self):
        ctx = multiprocessing.get_context("spawn")
        parent, child = ctx.Pipe()
        process = ctx.Process(target=_allocate, args=(child,))
        process.start()
        job = pdf._windows_job(process.pid, 100 * 1024 * 1024)
        try:
            self.assertIsNotNone(job)
            parent.send("los")
            self.assertTrue(parent.poll(30))
            self.assertEqual(parent.recv(), "MemoryError")
        finally:
            process.join(10)
            pdf._close_job(job)

    def test_check_mode_and_option_off(self):
        make_pdf(self.input / "bericht.pdf", [f"password={S['db_password']}"])
        report, _ = FileRun(make_sanitizer()).run(self.input, output_dir=self.tmp / "nie", dry_run=True)
        self.assertEqual(report.entries[0].counts, {"PASSWORD": 1})
        self.assertFalse((self.tmp / "nie").exists())
        report, out = self.run_folder(process_pdf=False)
        self.assertEqual(report.entries[0].reason, "PDF (Verarbeitung ausgeschaltet)")
        self.assertFalse(list(out.glob("bericht.pdf*")))


if __name__ == "__main__":
    unittest.main()
