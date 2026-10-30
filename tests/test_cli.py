"""Tests für die Kommandozeile und Sicherheitsprinzipien (offline, keine Werte in Ausgaben)."""

import os
import re
import subprocess
import sys
import unittest

from tests.helpers import ROOT, SECRETS, SecretAssertions, TempDirTestCase, copy_fake_data

from secret_sanitizer import config

S = SECRETS


class CliTests(SecretAssertions, TempDirTestCase):
    def cli(self, *args, stdin: bytes = b""):
        env = dict(os.environ)
        env[config.HOME_ENV_VAR] = str(self.tmp / "home")
        # Meldungen unabhängig von der Konsolen-Kodierung (unter Windows oft cp1252) als UTF-8
        env["PYTHONIOENCODING"] = "utf-8"
        return subprocess.run([sys.executable, "-m", "secret_sanitizer", *args], input=stdin, cwd=str(ROOT),
                              env=env, capture_output=True, timeout=120)

    def test_stdin_stdout(self):
        res = self.cli("-", stdin=f"password={S['db_password']} an {S['email']}\n".encode("utf-16"))
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(res.stdout.decode("utf-8"), "password=[PASSWORD_1] an [EMAIL_1]\n")
        self.assertIn("PASSWORD=1", res.stderr.decode("utf-8"))
        self.assertNoSecrets(res.stderr.decode("utf-8"))

    def test_no_personal(self):
        res = self.cli("-", "--no-personal", stdin=f"an {S['email']}".encode())
        self.assertEqual(res.stdout.decode(), f"an {S['email']}")

    def test_disable_and_mode(self):
        res = self.cli("-", "--disable", "IP", "--mode", "loose", stdin=b"ip 10.1.2.3 host=box7")
        self.assertEqual(res.stdout.decode(), "ip 10.1.2.3 host=box7")
        res = self.cli("-", "--disable", "GIBTSNICHT", stdin=b"x")
        self.assertEqual(res.returncode, 2)

    def test_folder_run(self):
        src = self.tmp / "daten"
        copy_fake_data(src)
        res = self.cli(str(src), "-q")
        self.assertEqual(res.returncode, 0, res.stderr)
        out = self.tmp / "daten_sanitized"
        self.assertTrue((out / "linux" / "auth.log").exists())
        self.assertNoSecrets((out / "linux" / "env_export.sh").read_text(encoding="utf-8"))

    def test_exclude_options(self):
        src = self.tmp / "daten"
        copy_fake_data(src)
        (src / "node_modules").mkdir()
        (src / "node_modules" / "a.js").write_text("x\n", encoding="utf-8")
        self.cli(str(src), "-q", "--exclude", "windows")
        out = self.tmp / "daten_sanitized"
        self.assertFalse((out / "node_modules").exists())   # Standardmuster
        self.assertFalse((out / "windows").exists())        # --exclude
        self.assertTrue((out / "linux").exists())
        self.cli(str(src), "-q", "--no-exclude", "-o", str(self.tmp / "alles"))
        self.assertTrue((self.tmp / "alles" / "node_modules" / "a.js").exists())

    def test_check_mode(self):
        src = self.tmp / "daten"
        copy_fake_data(src)
        res = self.cli(str(src), "--check")
        self.assertEqual(res.returncode, 3, res.stderr)
        out = res.stdout.decode("utf-8")
        self.assertIn("linux/auth.log: ", out)
        self.assertNotIn("binary/", out)
        self.assertNoSecrets(out + res.stderr.decode("utf-8"))
        self.assertFalse((self.tmp / "daten_sanitized").exists())   # nichts geschrieben
        clean = self.tmp / "sauber.txt"
        clean.write_text("Nur ein harmloser Satz.\n", encoding="utf-8")
        res = self.cli(str(clean), "--check")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(res.stdout, b"")
        res = self.cli("-", "--check", "-q", stdin=f"password={S['db_password']}".encode())
        self.assertEqual((res.returncode, res.stdout), (3, b""))

    def test_folder_run_output_has_no_secrets(self):
        src = self.tmp / "daten"
        copy_fake_data(src)
        res = self.cli(str(src), "-o", str(self.tmp / "aus"))
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertNoSecrets(res.stderr.decode("utf-8") + res.stdout.decode("utf-8"))

    def test_refuses_output_equal_input(self):
        src = self.tmp / "daten"
        copy_fake_data(src, "linux")
        res = self.cli(str(src), "-o", str(src))
        self.assertEqual(res.returncode, 2)
        self.assertIn("Ausgabeordner", res.stderr.decode("utf-8"))

    def test_binary_stdin(self):
        res = self.cli("-", stdin=b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + S["db_password"].encode())
        self.assertEqual(res.returncode, 2)
        self.assertNoSecrets(res.stderr.decode("utf-8"))

    def test_list_categories(self):
        res = self.cli("--list-categories")
        self.assertIn("PASSWORD", res.stdout.decode("utf-8"))


class SecurityPrincipleTests(unittest.TestCase):
    def test_no_network_code(self):
        """Komplett offline: Das Paket importiert keine Netzwerkmodule."""
        forbidden = re.compile(r"^\s*(?:import|from)\s+(socket|ssl|http|urllib\.request|ftplib|smtplib|"
                               r"requests|httpx|aiohttp|telnetlib|xmlrpc|webbrowser)\b", re.M)
        for path in (ROOT / "secret_sanitizer").rglob("*.py"):
            self.assertIsNone(forbidden.search(path.read_text(encoding="utf-8")), str(path))

    def test_no_logging_of_values(self):
        """Kein logging/print von Treffer-Werten im Kern."""
        for path in (ROOT / "secret_sanitizer" / "core").rglob("*.py"):
            src = path.read_text(encoding="utf-8")
            self.assertNotIn("import logging", src, str(path))
            self.assertNotIn("print(", src, str(path))

    def test_mapping_never_written(self):
        """Das Mapping wird nirgends serialisiert."""
        for path in (ROOT / "secret_sanitizer").rglob("*.py"):
            src = path.read_text(encoding="utf-8")
            self.assertNotRegex(src, r"(?:json\.dumps?|pickle)\([^)]*mapping", str(path))


if __name__ == "__main__":
    unittest.main()
