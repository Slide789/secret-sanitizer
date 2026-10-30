"""Tests für eigene Wortlisten."""

import copy
import unittest

from tests.helpers import SECRETS, default_ruleset, make_sanitizer

from secret_sanitizer.core.rules import Wordlist

S = SECRETS


def ruleset_with(*wordlists):
    rs = copy.copy(default_ruleset())
    rs.wordlists = list(wordlists)
    return rs


class WordlistTests(unittest.TestCase):
    def test_company_and_project(self):
        rs = ruleset_with(Wordlist("firma", "Firma", "COMPANY", ["Fakefirma GmbH", "Fakefirma"]),
                          Wordlist("proj", "Projekte", "PROJECT", ["Projekt Phoenix"]))
        out = make_sanitizer(ruleset=rs).sanitize(f"Kunde {S['company']}, kurz FAKEFIRMA, im Projekt  Phoenix.").text
        self.assertEqual(out, "Kunde [COMPANY_1], kurz [COMPANY_2], im [PROJECT_1].")

    def test_case_sensitive_list(self):
        rs = ruleset_with(Wordlist("x", "X", "HOSTNAME", ["SRV-DB01"], ignore_case=False))
        # Ohne Treffer in exakter Schreibweise wird nichts erkannt ...
        self.assertEqual(make_sanitizer(ruleset=rs).sanitize("nur srv-db01").text, "nur srv-db01")
        # ... wurde der Wert aber erkannt, ersetzt die Propagation (sicherheitshalber)
        # auch andere Schreibweisen.
        out = make_sanitizer(ruleset=rs).sanitize("SRV-DB01 und srv-db01").text
        self.assertEqual(out, "[HOSTNAME_1] und [HOSTNAME_1]")

    def test_word_boundaries(self):
        rs = ruleset_with(Wordlist("x", "X", "USERNAME", ["max"]))
        out = make_sanitizer(ruleset=rs).sanitize("max maximal Max_ x-max").text
        self.assertEqual(out, "[USERNAME_1] maximal Max_ x-[USERNAME_1]")

    def test_person_names_toggle(self):
        rs = ruleset_with(Wordlist("namen", "Namen", "NAME", [S["person"]]))
        text = f"Ansprechpartnerin {S['person']}"
        self.assertEqual(make_sanitizer(ruleset=rs).sanitize(text).text, "Ansprechpartnerin [NAME_1]")
        off = make_sanitizer(ruleset=rs, enabled_categories={"NAME": False}).sanitize(text).text
        self.assertEqual(off, text)

    def test_disabled_list(self):
        rs = ruleset_with(Wordlist("x", "X", "COMPANY", ["Fakefirma"], enabled=False))
        self.assertEqual(make_sanitizer(ruleset=rs).sanitize("Fakefirma").text, "Fakefirma")

    def test_domain_inside_fqdn(self):
        rs = ruleset_with(Wordlist("d", "Domains", "DOMAIN", ["fake-firma.de"]))
        out = make_sanitizer(ruleset=rs).sanitize("web.fake-firma.de").text
        self.assertEqual(out, "web.[DOMAIN_1]")


if __name__ == "__main__":
    unittest.main()
