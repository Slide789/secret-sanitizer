"""Tests für Datei-/Ordnerlauf, blockweise Verarbeitung und Bericht."""

import copy
import hashlib
import shutil
import threading
import unittest
from pathlib import Path
from unittest import mock

from tests.helpers import FAKE_DIR, SECRETS, SecretAssertions, TempDirTestCase, default_ruleset, make_sanitizer

from secret_sanitizer.core import files as files_mod
from secret_sanitizer.core.files import (REPORT_NAME, FileRun, RunError, default_output_dir, load_text_file,
                                         save_sanitized_text)
from secret_sanitizer.core.rules import Wordlist

S = SECRETS


def ruleset_with_lists():
    rs = copy.copy(default_ruleset())
    rs.wordlists = [Wordlist("firma", "Firma", "COMPANY", [S["company"]]),
                    Wordlist("proj", "Projekte", "PROJECT", [S["project"]]),
                    Wordlist("namen", "Namen", "NAME", [S["person"]])]
    return rs


def tree_hashes(folder: Path) -> dict:
    return {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(folder.rglob("*")) if p.is_file()}


class FolderRunTests(SecretAssertions, TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.input = self.tmp / "eingabe"
        shutil.copytree(FAKE_DIR, self.input)
        self.before = tree_hashes(self.input)

    def run_folder(self, mode="strict", **kwargs):
        sanitizer = make_sanitizer(mode, ruleset=ruleset_with_lists(), **kwargs)
        return FileRun(sanitizer).run(self.input)

    def test_full_run(self):
        report, out = self.run_folder()
        self.assertEqual(out, self.tmp / "eingabe_sanitized")
        # Originale unverändert
        self.assertEqual(tree_hashes(self.input), self.before)
        # Gleiche Struktur
        expected = {k for k in self.before if not k.startswith("binary/")}
        produced = {k for k in tree_hashes(out) if k != REPORT_NAME}
        self.assertEqual(produced, expected)
        # Keine Secrets in irgendeiner Ausgabe
        for path in out.rglob("*"):
            if path.is_file():
                self.assertNoSecrets(path.read_text(encoding="utf-8"), msg=str(path.relative_to(out)))
        # Binärdatei übersprungen
        skipped = {e.rel_path: e.reason for e in report.by_status("skipped")}
        self.assertEqual(skipped, {"binary/fake_image.png": "Binärdatei"})
        self.assertEqual(report.by_status("failed"), [])

    def test_report_contains_no_secrets(self):
        report, out = self.run_folder()
        text = (out / REPORT_NAME).read_text(encoding="utf-8")
        self.assertIn("bearbeitet", text)
        self.assertIn("linux/auth.log", text)
        self.assertNoSecrets(text)
        self.assertNoSecrets(report.to_json())
        self.assertNotIn(str(self.tmp), text)  # keine absoluten Pfade

    def test_utf16_and_crlf(self):
        _, out = self.run_folder()
        ps = (out / "windows/powershell_utf16.txt").read_bytes()
        self.assertFalse(ps.startswith(b"\xff\xfe"))  # Ausgabe UTF-8
        text = ps.decode("utf-8")
        self.assertRegex(text, r"C:\\Users\\\[USERNAME_\d+\]\\Documents")
        self.assertIn("\r\n", text)
        dump = (out / "windows/secretsdump_crlf.txt").read_bytes()
        self.assertEqual(dump.count(b"\r\n"), 3)
        cp = (out / "windows/cmd_cp1252.txt").read_text(encoding="utf-8")
        self.assertIn("Grüße an Jürgen", cp)

    def test_output_encoding_same(self):
        _, out = self.run_folder(output_encoding="same")
        self.assertTrue((out / "windows/powershell_utf16.txt").read_bytes().startswith(b"\xff\xfe"))

    def test_consistency_across_files(self):
        _, out = self.run_folder()
        notes = (out / "mixed/notes.txt").read_text(encoding="utf-8")
        env = (out / "linux/env_export.sh").read_text(encoding="utf-8")
        # db_password steht nur URL-codiert/groß in notes.txt, wurde aber in anderen Dateien erkannt
        self.assertNotIn("Pa55w0rd", notes)
        self.assertNotIn("PA55W0RD", notes)
        auth = (out / "linux/auth.log").read_text(encoding="utf-8")
        ip_placeholder = [w for w in env.split() if w.startswith("[IP_")][0]
        self.assertIn(ip_placeholder, auth)

    def test_output_dir_rules(self):
        sanitizer = make_sanitizer()
        with self.assertRaises(RunError):
            FileRun(sanitizer).run(self.input, output_dir=self.input)
        with self.assertRaises(RunError):
            FileRun(sanitizer).run(self.input, output_dir=self.tmp)
        report, out = FileRun(sanitizer).run(self.input, output_dir=self.tmp / "anderswo")
        self.assertEqual(out, self.tmp / "anderswo")

    def test_output_inside_input_not_reprocessed(self):
        sanitizer = make_sanitizer()
        inner = self.input / "_out"
        FileRun(sanitizer).run(self.input, output_dir=inner)
        report, _ = FileRun(make_sanitizer()).run(self.input, output_dir=inner)
        self.assertFalse([e for e in report.entries if e.rel_path.startswith("_out")])

    def test_limits(self):
        sanitizer = make_sanitizer(max_files_per_run=3)
        with self.assertRaises(RunError):
            FileRun(sanitizer).run(self.input)
        tiny = make_sanitizer(max_file_size_mb=0.0001)
        report, _ = FileRun(tiny).run(self.input)
        self.assertTrue(all(e.status == "skipped" for e in report.entries))
        asked = []
        report, _ = FileRun(tiny, confirm_large=lambda rel, mb: asked.append(rel) or True).run(self.input)
        self.assertTrue(asked)
        self.assertTrue(report.by_status("processed"))

    def test_failure_reason_has_no_content(self):
        secret = S["db_password"]
        original = files_mod.FileRun._learn_file

        def boom(self, src, enc):
            if src.name == "notes.txt":
                raise ValueError(f"kaputt bei {secret}")
            return original(self, src, enc)

        with mock.patch.object(files_mod.FileRun, "_learn_file", boom):
            report, out = FileRun(make_sanitizer()).run(self.input)
        failed = report.by_status("failed")
        self.assertEqual([e.rel_path for e in failed], ["mixed/notes.txt"])
        self.assertNotIn(secret, failed[0].reason)
        self.assertNotIn(secret, (out / REPORT_NAME).read_text(encoding="utf-8"))

    def test_cancel(self):
        cancel = threading.Event()
        cancel.set()
        report, _ = FileRun(make_sanitizer(), cancel=cancel).run(self.input)
        self.assertTrue(report.aborted)

    def test_single_file(self):
        src = self.input / "linux" / "auth.log"
        report, out = FileRun(make_sanitizer()).run(src)
        self.assertEqual(out, self.input.parent / "linux_sanitized" if False else default_output_dir(src))
        self.assertEqual(out, self.input / "linux_sanitized")
        self.assertTrue((out / "auth.log").exists())


class ChunkingTests(SecretAssertions, TempDirTestCase):
    def test_chunked_equals_unchunked(self):
        pem = (f"-----BEGIN RSA PRIVATE KEY-----\n{S['private_key_body']}\n-----END RSA PRIVATE KEY-----\n")
        lines = []
        for i in range(3000):
            lines.append(f"Zeile {i}: Verbindung von 10.0.{i % 200}.{i % 250} ok\n")
            if i == 700:
                lines.append(pem)
            if i == 2500:
                lines.append(f"spät: password={S['db_password']}\n")
        lines.append(f"früh wiederholt? {S['db_password']}\n")
        content = "".join(lines)
        src_dir = self.tmp / "gross"
        src_dir.mkdir()
        (src_dir / "big.log").write_text(content, encoding="utf-8")
        # Erwartung: einmal komplett im Speicher
        expected = make_sanitizer().sanitize(content).text
        report, out = FileRun(make_sanitizer(chunk_size=10_000, chunk_overlap=2_000)).run(src_dir)
        produced = (out / "big.log").read_text(encoding="utf-8")
        self.assertEqual(produced, expected)
        self.assertNoSecrets(produced, keys=["db_password", "private_key_body"])
        self.assertIn("[PRIVATE_KEY_1]", produced)
        # Erste Zeile mit dem Passwort steht VOR der Erkennung im Text -> trotzdem ersetzt
        self.assertGreater(content.index("früh"), content.index("spät"))

    def test_pem_across_block_border(self):
        pem = f"-----BEGIN OPENSSH PRIVATE KEY-----\n{S['private_key_body']}\n-----END OPENSSH PRIVATE KEY-----\n"
        content = ("x" * 60 + "\n") * 160 + pem + "ende\n"  # PEM beginnt kurz vor der 10k-Grenze
        src_dir = self.tmp / "pem"
        src_dir.mkdir()
        (src_dir / "k.txt").write_text(content, encoding="utf-8")
        _, out = FileRun(make_sanitizer(chunk_size=10_000, chunk_overlap=5_000)).run(src_dir)
        produced = (out / "k.txt").read_text(encoding="utf-8")
        self.assertIn("[PRIVATE_KEY_1]\nende", produced)
        self.assertNoSecrets(produced, keys=["private_key_body"])

    def test_late_invalid_utf8_falls_back(self):
        src_dir = self.tmp / "enc"
        src_dir.mkdir()
        data = ("a" * 70_000 + "\n").encode() + "password=Grüß99\n".encode("cp1252")
        (src_dir / "x.txt").write_bytes(data)
        report, out = FileRun(make_sanitizer()).run(src_dir)
        self.assertEqual(report.entries[0].encoding, "cp1252")
        self.assertIn("password=[PASSWORD_1]", (out / "x.txt").read_text(encoding="utf-8"))


class PreviewFileTests(TempDirTestCase):
    def test_load_and_save(self):
        src = self.tmp / "in" / "ps.txt"
        src.parent.mkdir()
        src.write_bytes("password=geheim99\r\nok\r\n".encode("utf-16"))
        loaded = load_text_file(src)
        self.assertEqual(loaded.text, "password=geheim99\nok\n")
        self.assertEqual(loaded.newline, "\r\n")
        sanitizer = make_sanitizer()
        result = sanitizer.sanitize(loaded.text)
        dest = save_sanitized_text(src, result.text, loaded, sanitizer.settings)
        self.assertEqual(dest, self.tmp / "in_sanitized" / "ps.txt")
        self.assertEqual(dest.read_bytes(), b"password=[PASSWORD_1]\r\nok\r\n")
        self.assertEqual(src.read_bytes(), "password=geheim99\r\nok\r\n".encode("utf-16"))

    def test_binary_rejected(self):
        src = self.tmp / "b.bin"
        src.write_bytes(b"\x00\x01\x02\x89PNG\x00\x00")
        with self.assertRaises(RunError):
            load_text_file(src)


if __name__ == "__main__":
    unittest.main()
