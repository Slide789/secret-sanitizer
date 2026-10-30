"""Tests für den Regex-Detektor (inkl. Windows-/Linux-Muster, Hashes, PEM)."""

import unittest

from tests.helpers import SECRETS, SecretAssertions, default_ruleset, make_sanitizer, sanitize

from secret_sanitizer.core.models import DetectContext
from secret_sanitizer.config import Settings
from secret_sanitizer.detectors.regex_detector import RegexDetector

S = SECRETS


def regex_hits(text):
    det = RegexDetector(default_ruleset())
    return {(f.category, text[f.start:f.end]) for f in det.detect(text, DetectContext(Settings()))}


class RegexDetectorTests(SecretAssertions, unittest.TestCase):
    def assertHit(self, text, category, value):
        self.assertIn((category, value), regex_hits(text))

    def test_cloud_tokens(self):
        self.assertHit(f"key {S['aws_key']} ok", "API_KEY", S["aws_key"])
        self.assertHit(f"t={S['github']}", "TOKEN", S["github"])
        self.assertHit(f"x {S['gitlab']} y", "TOKEN", S["gitlab"])
        self.assertHit(f"x {S['slack']} y", "TOKEN", S["slack"])
        self.assertHit(f"x {S['google']} y", "API_KEY", S["google"])
        self.assertHit(f"jwt {S['jwt']} y", "JWT", S["jwt"])

    def test_network(self):
        self.assertHit("von 192.168.178.23 port", "IP", "192.168.178.23")
        self.assertHit("netz 10.0.0.0/8", "IP", "10.0.0.0/8")
        self.assertHit(f"inet6 {S['ipv6']}", "IP", S["ipv6"])
        self.assertHit("inet6 fe80::1%eth0 x", "IP", "fe80::1%eth0")
        self.assertHit(f"hw {S['mac']}", "MAC", S["mac"])
        self.assertHit("hw 00-1A-2B-3C-4D-5E", "MAC", "00-1A-2B-3C-4D-5E")
        self.assertHit(f"an {S['email']}.", "EMAIL", S["email"])
        self.assertHit(f"db {S['hostname']} up", "HOSTNAME", S["hostname"])

    def test_no_ip_false_positives(self):
        text = "Version 10.0.19045 um 12:30:45, 999.1.1.1, 1.2.3.4.5"
        self.assertEqual(sanitize(text), text)

    def test_url_credentials(self):
        text = f"postgres://appuser:{S['url_pw']}@db:5432/x"
        self.assertHit(text, "PASSWORD", S["url_pw"])
        self.assertHit(text, "USERNAME", "appuser")
        out = sanitize(f"redis://:{S['url_pw']}@cache.fake-firma.local:6379/0")
        self.assertEqual(out, "redis://:[PASSWORD_1]@[HOSTNAME_1]:6379/0")

    def test_pem_block_complete(self):
        text = f"vorher\n-----BEGIN RSA PRIVATE KEY-----\n{S['private_key_body']}\n-----END RSA PRIVATE KEY-----\nnachher"
        out = sanitize(text)
        self.assertEqual(out, "vorher\n[PRIVATE_KEY_1]\nnachher")

    def test_pem_truncated(self):
        text = f"-----BEGIN OPENSSH PRIVATE KEY-----\n{S['private_key_body']}\n(abgeschnitten)"
        out = sanitize(text)
        for line in S["private_key_body"].splitlines():
            self.assertNotIn(line, out)

    def test_certificate(self):
        text = f"-----BEGIN CERTIFICATE-----\n{S['cert_body']}\n-----END CERTIFICATE-----"
        self.assertEqual(sanitize(text), "[CERTIFICATE_1]")

    def test_windows_patterns(self):
        self.assertHit(f"C:\\Users\\{S['win_user']}\\Desktop", "USERNAME", S["win_user"])
        self.assertHit(f"c:/users/{S['win_user']}/x", "USERNAME", S["win_user"])
        self.assertHit(f"SID {S['sid']} ok", "SID", S["sid"])
        self.assertHit(f"HKEY_USERS\\{S['sid']}\\Software", "SID", S["sid"])
        self.assertHit(f"login {S['domain_user']} ok", "USERNAME", S["domain_user"])
        self.assertHit(f"net use {S['unc']} x", "UNC_PATH", S["unc"])
        self.assertHit(f"Administrator:500:{S['lm']}:{S['ntlm']}:::", "PASSWORD_HASH", f"{S['lm']}:{S['ntlm']}")

    def test_windows_no_false_positives(self):
        hits = regex_hits("C:\\Users\\Public\\x C:\\Windows\\System32 HKLM\\SOFTWARE\\Microsoft NT AUTHORITY\\SYSTEM S-1-5-18")
        self.assertFalse([h for h in hits if h[0] in ("USERNAME", "SID")], hits)

    def test_linux_patterns(self):
        self.assertHit(f"/home/{S['linux_user']}/x", "USERNAME", S["linux_user"])
        self.assertHit(f"root:{S['sha512crypt']}:19000:0:::", "PASSWORD_HASH", S["sha512crypt"])
        self.assertHit(f"u:{S['md5crypt']}:1", "PASSWORD_HASH", S["md5crypt"])
        self.assertHit(f"u:{S['bcrypt']}:1", "PASSWORD_HASH", S["bcrypt"])
        self.assertHit(f"ssh-ed25519 {S['ssh_pub']} jdoe@laptop", "SSH_KEY", S["ssh_pub"])
        self.assertHit(f"ssh-ed25519 {S['ssh_pub']} jdoe@laptop", "USERNAME", "jdoe@laptop")
        self.assertHit(f"Authorization: Bearer {S['bearer']}", "TOKEN", S["bearer"])
        self.assertHit(f'"auth": "{S["docker_auth"]}"', "TOKEN", S["docker_auth"])
        self.assertHit(f"data:\n  db-pass: {S['k8s_b64']}\n", "SECRET", S["k8s_b64"])

    def test_checksums(self):
        out = sanitize(f"Karte {S['credit_card']} und 4111 1111 1111 1112", mode="loose")
        self.assertIn("[CREDIT_CARD_1]", out)
        self.assertIn("4111 1111 1111 1112", out)  # ungültige Luhn-Summe
        out = sanitize(f"IBAN {S['iban']} und DE00370400440532013000", mode="loose")
        self.assertIn("[IBAN_1]", out)
        self.assertIn("DE00370400440532013000", out)

    def test_modes(self):
        text = f"host {S['hostname']} und web.fake-firma.de"
        self.assertNotIn("web.fake-firma.de", sanitize(text, mode="strict"))
        self.assertIn("web.fake-firma.de", sanitize(text, mode="loose"))

    def test_public_example_domains_allowed(self):
        self.assertEqual(sanitize("siehe example.com und localhost"), "siehe example.com und localhost")

    def test_personal_toggle(self):
        out = make_sanitizer(enabled_categories={"EMAIL": False}).sanitize(f"an {S['email']}").text
        self.assertIn(S["email"], out)


if __name__ == "__main__":
    unittest.main()
