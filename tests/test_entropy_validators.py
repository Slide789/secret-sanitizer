"""Tests für Entropie-Analyse und Prüfsummen-Validatoren."""

import unittest

from tests.helpers import FALSE_POSITIVES, SECRETS, sanitize

from secret_sanitizer.detectors import validators
from secret_sanitizer.detectors.entropy_detector import charset_of, shannon_entropy

S = SECRETS


class EntropyTests(unittest.TestCase):
    def test_entropy_math(self):
        self.assertEqual(shannon_entropy("aaaa"), 0.0)
        self.assertAlmostEqual(shannon_entropy("abcd"), 2.0)
        self.assertEqual(charset_of("deadbeef12"), "hex")
        self.assertEqual(charset_of("Ab9+/x=="), "base64")
        self.assertEqual(charset_of("Ab9_x-Q"), "base64")

    def test_unknown_secret_found(self):
        out = sanitize(f"Wert ohne Kontext: {S['entropy_secret']} Ende")
        self.assertEqual(out, "Wert ohne Kontext: [SECRET_1] Ende")
        out = sanitize(f"aws {S['aws_secret']}")
        self.assertNotIn(S["aws_secret"], out)

    def test_modes_differ(self):
        weak = "k8s9df8g7s6d5f4gq1"  # 18 Zeichen
        self.assertNotIn(weak, sanitize(f"x {weak} y", mode="strict"))
        self.assertIn(weak, sanitize(f"x {weak} y", mode="normal"))  # Mindestlänge 20
        self.assertIn(S["entropy_secret"], sanitize(f"x {S['entropy_secret']} y", mode="loose"))

    def test_false_positives(self):
        for value in FALSE_POSITIVES:
            self.assertEqual(sanitize(value), value, value)

    def test_hash_hint(self):
        text = "commit 3f9a1c2be7d04f6a9e8b7c6d5a4f3e2d1c0b9a8f7e6d5c4b3a2"
        self.assertEqual(sanitize(text), text)

    def test_paths_and_identifiers(self):
        for text in ["/var/lib/docker/overlay2/l/ABCDEF123456", "my-service-name-v2-prod-2024",
                     "Microsoft.Windows.Desktop.App_10.0.19041", "node_modules/@types/node/index.d.ts"]:
            self.assertEqual(sanitize(text), text, text)


class ValidatorTests(unittest.TestCase):
    def test_luhn(self):
        self.assertTrue(validators.luhn_valid("4111 1111 1111 1111"))
        self.assertTrue(validators.luhn_valid("5500-0000-0000-0004"))
        self.assertFalse(validators.luhn_valid("4111 1111 1111 1112"))
        self.assertFalse(validators.luhn_valid("0000 0000 0000 0000"))
        self.assertFalse(validators.luhn_valid("123"))

    def test_iban(self):
        self.assertTrue(validators.iban_valid("DE89370400440532013000"))
        self.assertTrue(validators.iban_valid("DE89 3704 0044 0532 0130 00"))
        self.assertTrue(validators.iban_valid("GB82WEST12345698765432"))
        self.assertFalse(validators.iban_valid("DE00370400440532013000"))

    def test_ip(self):
        self.assertTrue(validators.ipv6_valid("2001:db8::1"))
        self.assertFalse(validators.ipv6_valid("12:30:45"))
        self.assertFalse(validators.ipv6_valid("00:1A:2B:3C:4D:5E"))
        self.assertTrue(validators.ipv4_valid("10.0.0.0/8"))

    def test_confidence_effect(self):
        self.assertGreater(validators.apply_validator("luhn", "4111111111111111", 0.5), 0.75)
        self.assertLess(validators.apply_validator("luhn", "4111111111111112", 0.5), 0.3)
        self.assertEqual(validators.apply_validator(None, "x", 0.5), 0.5)


if __name__ == "__main__":
    unittest.main()
