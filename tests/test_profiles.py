"""Tests für Regel-Profile (Export, Import, Prüfung, Zusammenführen)."""

import copy
import json
import unittest

from tests.helpers import TempDirTestCase, default_ruleset, make_sanitizer

from secret_sanitizer.config import Settings
from secret_sanitizer.core import profiles
from secret_sanitizer.core.profiles import ProfileError
from secret_sanitizer.core.rules import AllowEntry, UserRules, Wordlist, merge_user_rules, rule_from_dict


def sample_rules() -> UserRules:
    return UserRules(
        rules=[rule_from_dict({"id": "ticket", "name": "Ticket", "category": "CUSTOM", "pattern": r"TICKET-\d+"})],
        wordlists=[Wordlist("user_company", "Firmen", "COMPANY", ["Fakefirma GmbH", "Musterwerk AG"])],
        allowlist=[AllowEntry("203.0.113.77")],
    )


class ProfileTests(TempDirTestCase):
    def test_export_without_wordlists_by_default(self):
        path = self.tmp / "p.json"
        settings = Settings(mode="normal", enabled_categories={"EMAIL": False})
        profiles.export_profile(path, sample_rules(), "Team", settings)
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["type"], profiles.PROFILE_TYPE)
        self.assertNotIn("wordlists", data)
        self.assertNotIn("Fakefirma", path.read_text(encoding="utf-8"))
        self.assertEqual(data["settings"], {"mode": "normal", "enabled_categories": {"EMAIL": False}})
        # keine Pfade oder sonstigen Einstellungen
        self.assertEqual(set(data["settings"]), {"mode", "enabled_categories"})

    def test_roundtrip_with_wordlists(self):
        path = self.tmp / "p.json"
        profiles.export_profile(path, sample_rules(), "Team", include_wordlists=True)
        profile = profiles.load_profile(path)
        self.assertEqual(profile.name, "Team")
        self.assertEqual(profile.warnings, [])
        self.assertEqual([r.id for r in profile.rules.rules], ["ticket"])
        self.assertEqual(profile.rules.wordlists[0].words, ["Fakefirma GmbH", "Musterwerk AG"])
        self.assertIsNone(profile.settings)
        ruleset = merge_user_rules(copy.copy(default_ruleset()), profile.rules)   # merge legt neue Listen an
        out = make_sanitizer(ruleset=ruleset).sanitize("TICKET-4711 bei Fakefirma GmbH, 203.0.113.77").text
        self.assertEqual(out, "[CUSTOM_1] bei [COMPANY_1], 203.0.113.77")

    def test_rejects_foreign_and_broken_files(self):
        cases = {
            "kein_json.json": "das ist kein json",
            "fremd.json": json.dumps({"rules": []}),
            "neuer.json": json.dumps({"type": profiles.PROFILE_TYPE, "version": 99}),
            "liste.json": json.dumps({"type": profiles.PROFILE_TYPE, "version": 1, "rules": "x"}),
        }
        for name, content in cases.items():
            path = self.tmp / name
            path.write_text(content, encoding="utf-8")
            with self.assertRaises(ProfileError, msg=name):
                profiles.load_profile(path)
        big = self.tmp / "gross.json"
        big.write_bytes(b" " * (profiles.MAX_PROFILE_BYTES + 1))
        with self.assertRaises(ProfileError):
            profiles.load_profile(big)

    def test_invalid_entries_become_warnings(self):
        path = self.tmp / "p.json"
        path.write_text(json.dumps({
            "type": profiles.PROFILE_TYPE, "version": 1, "unbekannt": 1,
            "rules": [{"id": "gut", "category": "CUSTOM", "pattern": "GUT-\\d+"},
                      {"id": "kaputt", "category": "CUSTOM", "pattern": "("},
                      {"id": "langsam", "category": "CUSTOM", "pattern": "(a+)+b"}, 42],
            "settings": {"mode": "gibtsnicht", "enabled_categories": {"EMAIL": False, "QUATSCH": True},
                         "output_dir": "C:\\\\Windows"},
        }), encoding="utf-8")
        profile = profiles.load_profile(path)
        self.assertEqual([r.id for r in profile.rules.rules], ["gut", "langsam"])
        text = "\n".join(profile.warnings)
        self.assertIn("unbekannt", text)
        self.assertIn("kaputt", text)
        self.assertIn("langsam", text)
        self.assertEqual(profile.settings, {"enabled_categories": {"EMAIL": False}})

    def test_merge_and_summary(self):
        current = sample_rules()
        incoming = UserRules(
            rules=[rule_from_dict({"id": "ticket", "category": "CUSTOM", "pattern": r"TICKET-\d{5}"}),
                   rule_from_dict({"id": "neu", "category": "CUSTOM", "pattern": r"NEU-\d+"})],
            wordlists=[Wordlist("user_company", "Firmen", "COMPANY", ["fakefirma gmbh", "Dritte KG"])],
            allowlist=[AllowEntry("203.0.113.77"), AllowEntry("198.51.100.1")])
        self.assertEqual(profiles.summarize(current, incoming),
                         {"new_rules": 1, "changed_rules": 1, "new_words": 1, "new_allow": 1})
        merged = profiles.merge(current, incoming)
        self.assertEqual(sorted(r.id for r in merged.rules), ["neu", "ticket"])
        self.assertEqual(next(r for r in merged.rules if r.id == "ticket").pattern, r"TICKET-\d{5}")
        self.assertEqual(merged.wordlists[0].words, ["Fakefirma GmbH", "Musterwerk AG", "Dritte KG"])
        self.assertEqual([a.value for a in merged.allowlist], ["203.0.113.77", "198.51.100.1"])
        # Original unverändert
        self.assertEqual(current.wordlists[0].words, ["Fakefirma GmbH", "Musterwerk AG"])

    def test_named_profiles(self):
        profiles.save_named_profile("Kunde A", sample_rules())
        self.assertIn("Kunde A", profiles.list_profiles())
        self.assertEqual(profiles.load_named_profile("Kunde A").rules.wordlists[0].words[0], "Fakefirma GmbH")
        for bad in ["../boese", "a/b", "CON", "nul.txt", "", " ", "x" * 61, "a:b"]:
            self.assertFalse(profiles.valid_profile_name(bad), bad)
            with self.assertRaises(ProfileError):
                profiles.profile_path(bad)


if __name__ == "__main__":
    unittest.main()
