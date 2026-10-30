"""Tests für Datei-/Ordnerlauf, blockweise Verarbeitung und Bericht."""

import copy
import gzip
import hashlib
import tarfile
import threading
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from tests.helpers import SECRETS, SecretAssertions, TempDirTestCase, copy_fake_data, default_ruleset, make_sanitizer

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
        copy_fake_data(self.input)
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

    def test_exclude_patterns(self):
        (self.input / ".git").mkdir()
        (self.input / ".git" / "config").write_text(f"password={S['db_password']}\n", encoding="utf-8")
        (self.input / "alt_sanitized").mkdir()
        (self.input / "alt_sanitized" / "x.txt").write_text("x\n", encoding="utf-8")
        (self.input / "linux" / "notiz.bak").write_text("x\n", encoding="utf-8")
        sanitizer = make_sanitizer(exclude_patterns=[".git", "*_sanitized", "*.BAK"])
        report, out = FileRun(sanitizer).run(self.input)
        self.assertEqual(sorted(report.excluded), [".git/", "alt_sanitized/", "linux/notiz.bak"])
        self.assertFalse((out / ".git").exists())
        self.assertFalse((out / "linux" / "notiz.bak").exists())
        self.assertFalse([e for e in report.entries if e.rel_path.startswith((".git", "alt_"))])
        self.assertIn("Ausgeschlossen (Ausschlussmuster): 3", (out / REPORT_NAME).read_text(encoding="utf-8"))
        # Pfadmuster und abgeschaltete Muster
        report, _ = FileRun(make_sanitizer(exclude_patterns=["linux/*.log"])).run(self.input, output_dir=self.tmp / "b")
        self.assertIn("linux/auth.log", report.excluded)
        self.assertIn("linux/env_export.sh", [e.rel_path for e in report.entries])
        report, _ = FileRun(make_sanitizer(exclude_patterns=[])).run(self.input, output_dir=self.tmp / "c")
        self.assertEqual(report.excluded, [])

    def test_stale_files_reported(self):
        out = self.tmp / "aus"
        FileRun(make_sanitizer()).run(self.input, output_dir=out)
        (self.input / "linux" / "auth.log").unlink()
        report, _ = FileRun(make_sanitizer()).run(self.input, output_dir=out)
        self.assertEqual(report.stale, ["linux/auth.log"])
        self.assertIn("veraltet", (out / REPORT_NAME).read_text(encoding="utf-8"))

    def test_clean_output(self):
        out = self.tmp / "aus"
        FileRun(make_sanitizer()).run(self.input, output_dir=out)
        (self.input / "linux" / "auth.log").unlink()
        report, _ = FileRun(make_sanitizer()).run(self.input, output_dir=out, clean_output=True)
        self.assertTrue(report.cleaned)
        self.assertEqual(report.stale, [])
        self.assertFalse((out / "linux" / "auth.log").exists())
        self.assertTrue((out / "linux" / "env_export.sh").exists())

    def test_clean_refuses_foreign_folder(self):
        fremd = self.tmp / "fremd"
        fremd.mkdir()
        (fremd / "wichtig.txt").write_text("bitte behalten\n", encoding="utf-8")
        with self.assertRaises(RunError):
            FileRun(make_sanitizer()).run(self.input, output_dir=fremd, clean_output=True)
        self.assertTrue((fremd / "wichtig.txt").exists())

    def test_sanitize_filenames(self):
        host = S["hostname"]
        (self.input / f"sicherung_{host}").mkdir()
        (self.input / f"sicherung_{host}" / f"{host}.log").write_text(f"verbunden mit {host}\n", encoding="utf-8")
        (self.input / f"{host}.log").write_text("x\n", encoding="utf-8")
        (self.input / "binary" / f"{host}.png").write_bytes(b"\x89PNG\x00\x00")
        sanitizer = make_sanitizer(sanitize_filenames=True)
        report, out = FileRun(sanitizer).run(self.input)
        placeholder = sanitizer.mapping.get(host)
        self.assertTrue(placeholder)
        self.assertTrue((out / f"sicherung_{placeholder}" / f"{placeholder}.log").exists())
        self.assertTrue((out / f"{placeholder}.log").exists())
        for path in out.rglob("*"):
            self.assertNotIn(host.lower(), path.name.lower())
        text = (out / REPORT_NAME).read_text(encoding="utf-8")
        self.assertNotIn(host.lower(), text.lower())   # auch nicht bei übersprungenen Dateien
        self.assertIn(f"binary/{placeholder}.png", text)
        self.assertEqual(report.stale, [])

    def test_hostname_only_in_filename(self):
        # Hostname steht nur im Namen, nicht im Inhalt; die Endung .log darf die Erkennung nicht verhindern
        src = self.tmp / "nur_name"
        src.mkdir()
        (src / "srv01.corp.local.log").write_text("x\n", encoding="utf-8")
        (src / "sicherung_srv02.corp.local.tar").write_text("x\n", encoding="utf-8")
        (src / "README.md").write_text("x\n", encoding="utf-8")
        _, out = FileRun(make_sanitizer(sanitize_filenames=True, process_archives=False)).run(src)
        names = sorted(p.name for p in out.iterdir() if p.name != REPORT_NAME)
        self.assertEqual(names, ["README.md", "[HOSTNAME_2].log", "sicherung_[HOSTNAME_1].tar"])

    def test_sanitized_filename_collisions(self):
        # Eigener Ordner ohne Fake-Daten, damit 10.1.2.3 sicher [IP_1] wird.
        # "10.1.2.3.log" wird zu "[IP_1].log" - genau wie die schon vorhandene Datei.
        src = self.tmp / "neu"
        src.mkdir()
        for name in ("10.1.2.3.log", "[IP_1].log"):
            (src / name).write_text("x\n", encoding="utf-8")
        report, out = FileRun(make_sanitizer(sanitize_filenames=True)).run(src)
        names = sorted(p.name for p in out.iterdir() if p.name != REPORT_NAME)
        self.assertEqual(names, ["[IP_1] (2).log", "[IP_1].log"])

    def test_exclude_does_not_apply_to_single_file(self):
        report, _ = FileRun(make_sanitizer(exclude_patterns=["*.log"])).run(self.input / "linux" / "auth.log",
                                                                          output_dir=self.tmp / "aus")
        self.assertEqual([e.rel_path for e in report.entries], ["auth.log"])

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


class ArchiveTests(SecretAssertions, TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.input = self.tmp / "eingabe"
        self.input.mkdir()
        self.secret_text = f"password={S['db_password']}\nhost {S['hostname']}\n"

    def run_folder(self, **kwargs):
        return FileRun(make_sanitizer(**kwargs)).run(self.input)

    def test_zip_roundtrip(self):
        with zipfile.ZipFile(self.input / "logs.zip", "w") as zf:
            zf.writestr("app/server.log", self.secret_text)
            zf.writestr("bild.png", b"\x89PNG\x00\x00" + S["db_password"].encode())
            zf.writestr("../../boese.txt", "x")
        (self.input / "lose.txt").write_text(f"auch {S['hostname']}\n", encoding="utf-8")
        report, out = self.run_folder()
        self.assertTrue((out / "logs.zip").is_file())
        with zipfile.ZipFile(out / "logs.zip") as zf:
            self.assertEqual(zf.namelist(), ["app/server.log"])
            inner = zf.read("app/server.log").decode("utf-8")
        self.assertNoSecrets(inner)
        self.assertIn("[PASSWORD_1]", inner)
        # gemeinsames Mapping mit den übrigen Dateien
        placeholder = inner.split("host ")[1].strip()
        self.assertIn(placeholder, (out / "lose.txt").read_text(encoding="utf-8"))
        status = {e.rel_path: (e.status, e.reason) for e in report.entries}
        self.assertEqual(status["logs.zip/bild.png"], ("skipped", "Binärdatei"))
        self.assertEqual(status["logs.zip/../../boese.txt"][1], "unsicherer Pfad im Archiv")
        self.assertFalse((self.tmp / "boese.txt").exists())
        self.assertEqual(report.stale, [])
        self.assertFalse((out / "logs.zip.tmp_pack").exists())

    def test_gz_and_tgz(self):
        with gzip.open(self.input / "app.log.gz", "wb") as fh:
            fh.write(self.secret_text.encode("utf-8"))
        tgz_src = self.tmp / "tar_inhalt.log"
        tgz_src.write_text(self.secret_text, encoding="utf-8")
        with tarfile.open(self.input / "paket.tar.gz", "w:gz") as tf:
            tf.add(tgz_src, arcname="var/log/tar_inhalt.log")
        report, out = self.run_folder()
        with gzip.open(out / "app.log.gz", "rb") as fh:
            self.assertNoSecrets(fh.read().decode("utf-8"))
        with tarfile.open(out / "paket.tar.gz", "r:gz") as tf:
            member = tf.getmember("var/log/tar_inhalt.log")
            self.assertEqual((member.uname, member.uid), ("", 0))
            self.assertNoSecrets(tf.extractfile(member).read().decode("utf-8"))
        self.assertEqual(report.by_status("failed"), [])

    def test_limits_and_broken_archives(self):
        with zipfile.ZipFile(self.input / "gross.zip", "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("a.log", "0" * 300_000)
            zf.writestr("b.log", "0" * 300_000)
        (self.input / "kaputt.zip").write_bytes(b"PK\x03\x04 kein echtes zip")
        report, out = self.run_folder(max_archive_mb=0.5)
        status = {e.rel_path: (e.status, e.reason) for e in report.entries}
        self.assertEqual(status["gross.zip"][0], "failed")
        self.assertIn("max_archive_mb", status["gross.zip"][1])
        self.assertEqual(status["kaputt.zip"][0], "failed")
        self.assertFalse((out / "gross.zip").exists())

    def test_staging_is_removed_and_option_off(self):
        with zipfile.ZipFile(self.input / "logs.zip", "w") as zf:
            zf.writestr("server.log", self.secret_text)
        run = FileRun(make_sanitizer())
        with mock.patch.object(files_mod.shutil, "rmtree", wraps=files_mod.shutil.rmtree) as rmtree:
            run.run(self.input)
        staged = [c.args[0] for c in rmtree.call_args_list if "archiv_" in str(c.args[0])]
        self.assertTrue(staged and not any(Path(p).exists() for p in staged), staged)
        report, _ = FileRun(make_sanitizer(process_archives=False)).run(self.input, output_dir=self.tmp / "aus")
        self.assertEqual([(e.rel_path, e.reason) for e in report.entries], [("logs.zip", "Binärdatei")])

    def test_archive_with_sanitized_filenames(self):
        host = S["hostname"]
        with zipfile.ZipFile(self.input / f"logs_{host}.zip", "w") as zf:
            zf.writestr(f"{host}.log", self.secret_text)
        sanitizer = make_sanitizer(sanitize_filenames=True)
        report, out = FileRun(sanitizer).run(self.input)
        placeholder = sanitizer.mapping.get(host)
        archive = out / f"logs_{placeholder}.zip"
        self.assertTrue(archive.is_file(), sorted(p.name for p in out.iterdir()))
        with zipfile.ZipFile(archive) as zf:
            self.assertEqual(zf.namelist(), [f"{placeholder}.log"])
        self.assertNotIn(host, (out / REPORT_NAME).read_text(encoding="utf-8"))


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
