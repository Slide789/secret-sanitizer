"""Tests für Gerüst und Kern: config, Regelformat, Kodierung, Replacer, Merger."""

import json
import unittest

from tests.helpers import TempDirTestCase, default_ruleset, make_sanitizer

from secret_sanitizer import config
from secret_sanitizer.config import Settings, load_settings, save_settings
from secret_sanitizer.core import encoding
from secret_sanitizer.core.merger import resolve_overlaps
from secret_sanitizer.core.models import CATEGORIES, PERSONAL_CATEGORIES, Finding
from secret_sanitizer.core.replacer import PlaceholderMapping, apply_replacements
from secret_sanitizer.core.rules import RuleError, load_ruleset, rule_from_dict


class ConfigTests(TempDirTestCase):
    def test_app_name_only_in_config(self):
        self.assertEqual(config.APP_NAME, "secret_sanitizer")
        self.assertTrue(config.HOME_ENV_VAR.startswith(config.APP_NAME.upper()))

    def test_defaults(self):
        s = Settings()
        self.assertEqual(s.mode, "strict")
        self.assertEqual(s.output_encoding, "utf-8")
        self.assertEqual(s.max_file_size_mb, 100)
        self.assertEqual(s.placeholder_style, "[{CATEGORY}_{N}]")
        self.assertTrue(s.is_category_enabled("PASSWORD"))
        self.assertLess(s.mode_thresholds["strict"], s.mode_thresholds["normal"])
        self.assertLess(s.mode_thresholds["normal"], s.mode_thresholds["loose"])

    def test_roundtrip(self):
        path = self.tmp / "config.json"
        s = Settings(mode="loose", enabled_categories={"EMAIL": False}, max_files_per_run=5)
        save_settings(s, path)
        loaded = load_settings(path)
        self.assertEqual(loaded.mode, "loose")
        self.assertFalse(loaded.is_category_enabled("EMAIL"))
        self.assertEqual(loaded.max_files_per_run, 5)

    def test_invalid_values_fall_back(self):
        path = self.tmp / "config.json"
        path.write_text(json.dumps({"mode": "egal", "max_file_size_mb": -3, "placeholder_style": "XX",
                                    "output_encoding": "gibtsnicht", "unbekannt": 1}), encoding="utf-8")
        s = load_settings(path)
        self.assertEqual(s.mode, "strict")
        self.assertEqual(s.max_file_size_mb, 100)
        self.assertEqual(s.placeholder_style, "[{CATEGORY}_{N}]")
        self.assertEqual(s.output_encoding, "utf-8")

    def test_broken_file_gives_defaults(self):
        path = self.tmp / "config.json"
        path.write_text("{kaputt", encoding="utf-8")
        self.assertEqual(load_settings(path).mode, "strict")


class RuleFormatTests(TempDirTestCase):
    def test_default_rules_valid(self):
        rs = default_ruleset()
        self.assertEqual(rs.errors, [])
        self.assertGreater(len(rs.rules), 40)
        ids = [r.id for r in rs.rules]
        self.assertEqual(len(ids), len(set(ids)), "doppelte Regel-IDs")
        for r in rs.rules:
            self.assertIn(r.category, CATEGORIES)
            self.assertTrue(r.description, f"Regel {r.id} ohne description")

    def test_personal_categories(self):
        self.assertIn("EMAIL", PERSONAL_CATEGORIES)
        self.assertIn("NAME", PERSONAL_CATEGORIES)

    def test_invalid_rule_rejected(self):
        with self.assertRaises(RuleError):
            rule_from_dict({"id": "x", "category": "PASSWORD", "pattern": "("})
        with self.assertRaises(RuleError):
            rule_from_dict({"id": "x", "category": "GIBTSNICHT", "pattern": "a"})
        with self.assertRaises(RuleError):
            rule_from_dict({"id": "x", "category": "PASSWORD", "pattern": "a*"})  # passt auf leer
        with self.assertRaises(RuleError):
            rule_from_dict({"id": "x", "category": "PASSWORD", "pattern": "a", "confidence": 3})

    def test_error_message_contains_no_text(self):
        try:
            rule_from_dict({"id": "meine_regel", "category": "PASSWORD", "pattern": "geheim(123"})
        except RuleError as exc:
            self.assertNotIn("geheim", str(exc))
            self.assertIn("meine_regel", str(exc))

    def test_user_rules_override_and_append(self):
        user = self.tmp / "user_rules.json"
        user.write_text(json.dumps({
            "rules": [
                {"id": "ipv4", "name": "aus", "category": "IP", "pattern": "x{99}", "enabled": False},
                {"id": "ticket", "name": "Ticket", "category": "CUSTOM", "pattern": r"TICKET-\d+", "confidence": 0.9},
                {"id": "kaputt", "category": "CUSTOM", "pattern": "("},
            ],
            "wordlists": [{"id": "firma", "name": "Firma", "category": "COMPANY", "words": ["Fakefirma"]}],
            "allowlist": ["10.0.0.1"],
        }), encoding="utf-8")
        rs = load_ruleset(config.default_rules_path(), user)
        self.assertEqual(len(rs.errors), 1)
        ipv4 = [r for r in rs.rules if r.id == "ipv4"]
        self.assertEqual(len(ipv4), 1)
        self.assertFalse(ipv4[0].enabled)
        self.assertTrue(rs.is_allowed("10.0.0.1"))
        self.assertEqual(rs.wordlists[-1].category, "COMPANY")

    def test_allowlist_regex_not_combinable(self):
        # Einzeln gültig, zusammen nicht kombinierbar: darf die Erkennung nicht lahmlegen
        user = self.tmp / "user_rules.json"
        user.write_text(json.dumps({"allowlist": [
            {"value": "(?i)fakehost\\d+", "regex": True},
            {"value": "(?P<x>abc)\\d", "regex": True},
            {"value": "(?P<x>xyz)\\d", "regex": True},
        ]}), encoding="utf-8")
        rs = load_ruleset(config.default_rules_path(), user)
        self.assertEqual(rs.errors, [])
        self.assertTrue(rs.is_allowed("FakeHost7"))
        self.assertTrue(rs.is_allowed("xyz1"))
        self.assertFalse(rs.is_allowed("hunter22"))
        out = make_sanitizer(ruleset=rs).sanitize("password=hunter22 user=xyz1").text
        self.assertEqual(out, "password=[PASSWORD_1] user=xyz1")


class EncodingTests(unittest.TestCase):
    def test_boms(self):
        self.assertEqual(encoding.detect_encoding("abc".encode("utf-16")), "utf-16")
        self.assertEqual(encoding.detect_encoding("abc".encode("utf-8-sig")), "utf-8-sig")
        self.assertEqual(encoding.detect_encoding("abc".encode("utf-32")), "utf-32")

    def test_utf16_without_bom(self):
        self.assertEqual(encoding.detect_encoding("password=abc\r\n".encode("utf-16-le")), "utf-16-le")
        self.assertEqual(encoding.detect_encoding("password=abc\r\n".encode("utf-16-be")), "utf-16-be")

    def test_utf8_and_fallback(self):
        self.assertEqual(encoding.detect_encoding("Grüße".encode("utf-8")), "utf-8")
        self.assertEqual(encoding.detect_encoding("Grüße".encode("cp1252")), "cp1252")
        # Abgeschnittenes Mehrbytezeichen am Probenende ist trotzdem UTF-8
        self.assertEqual(encoding.detect_encoding("aü".encode("utf-8")[:-1]), "utf-8")

    def test_binary(self):
        self.assertTrue(encoding.is_binary(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x01\x02"))
        self.assertFalse(encoding.is_binary(b"normaler text"))

    def test_newlines(self):
        text, nl = encoding.normalize_newlines("a\r\nb\r\nc")
        self.assertEqual((text, nl), ("a\nb\nc", "\r\n"))
        self.assertEqual(encoding.restore_newlines(text, nl), "a\r\nb\r\nc")
        self.assertEqual(encoding.normalize_newlines("a\nb"), ("a\nb", "\n"))

    def test_decode_bytes(self):
        self.assertEqual(encoding.decode_bytes("Grüße".encode("utf-16")), ("Grüße", "utf-16"))
        with self.assertRaises(ValueError):
            encoding.decode_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x01\x02")


class ReplacerMergerTests(unittest.TestCase):
    def test_same_value_same_placeholder(self):
        m = PlaceholderMapping()
        self.assertEqual(m.placeholder_for("geheim1", "PASSWORD"), "[PASSWORD_1]")
        self.assertEqual(m.placeholder_for("anders2", "PASSWORD"), "[PASSWORD_2]")
        self.assertEqual(m.placeholder_for("GEHEIM1", "PASSWORD"), "[PASSWORD_1]")
        self.assertEqual(m.placeholder_for("10.0.0.5", "IP"), "[IP_1]")
        self.assertNotIn("geheim1", repr(m))

    def test_custom_style(self):
        m = PlaceholderMapping("<<{CATEGORY}-{N}>>")
        self.assertEqual(m.placeholder_for("x", "IP"), "<<IP-1>>")

    def test_variants_propagate(self):
        m = PlaceholderMapping()
        m.placeholder_for("p@ss word!", "PASSWORD")
        text = 'a=p%40ss%20word%21 b="P@SS WORD!" c=p%40ss+word%21'
        found = m.find_propagated(text)
        self.assertEqual(len(found), 3)

    def test_propagation_respects_word_boundaries(self):
        m = PlaceholderMapping()
        m.placeholder_for("jdoe", "USERNAME")
        self.assertEqual(len(m.find_propagated("jdoe xjdoe jdoes svc_jdoe /home/jdoe/")), 2)

    def test_trie_prefers_longest_and_backtracks(self):
        m = PlaceholderMapping()
        m.placeholder_for("geheim", "PASSWORD")
        m.placeholder_for("geheim123", "PASSWORD")
        m.placeholder_for("jdoe", "USERNAME")
        m.placeholder_for("jdoe@laptop", "USERNAME")
        text = "geheim123 geheim1234 geheim jdoe@laptopX jdoe@laptop"
        spans = [(f.start, f.end) for f in m.find_propagated(text)]
        self.assertIn((0, 9), spans)            # längster Wert
        self.assertIn((21, 27), spans)          # "geheim"
        self.assertIn((28, 32), spans)          # jdoe in jdoe@laptopX
        self.assertIn((41, 52), spans)          # jdoe@laptop
        self.assertNotIn((10, 16), spans)       # geheim in geheim1234 (Wortgrenze)

    def test_long_values_propagate(self):
        m = PlaceholderMapping()
        long_value = "Ab1" * 100
        m.placeholder_for(long_value, "SECRET")
        self.assertEqual(len(m.find_propagated("x " + long_value.upper() + " y")), 1)

    def test_overlap_highest_confidence_wins(self):
        a = Finding(0, 10, "SECRET", 0.5, "entropy")
        b = Finding(2, 12, "TOKEN", 0.9, "regex")
        self.assertEqual(resolve_overlaps([a, b]), [b])

    def test_confident_container_wins(self):
        block = Finding(0, 100, "PRIVATE_KEY", 0.99, "regex")
        inner = Finding(10, 20, "SECRET", 1.0, "regex")
        self.assertEqual(resolve_overlaps([block, inner]), [block])

    def test_non_block_container_does_not_win(self):
        email = Finding(0, 30, "EMAIL", 0.9, "regex")
        password = Finding(0, 10, "PASSWORD", 0.95, "regex")
        self.assertEqual(resolve_overlaps([email, password]), [password])

    def test_propagation_only_fills_gaps(self):
        primary = Finding(0, 50, "PRIVATE_KEY", 0.99, "regex")
        prop_inside = Finding(10, 15, "PASSWORD", 1.0, "propagation")
        prop_outside = Finding(60, 65, "PASSWORD", 1.0, "propagation")
        self.assertEqual(resolve_overlaps([primary], [prop_inside, prop_outside]), [primary, prop_outside])

    def test_agreement_bonus(self):
        a = Finding(0, 5, "IP", 0.6, "regex")
        b = Finding(0, 5, "IP", 0.6, "context")
        (merged,) = resolve_overlaps([a, b])
        self.assertGreater(merged.confidence, 0.6)

    def test_apply_replacements_positions(self):
        text = "pw=geheim1 und geheim1"
        m = PlaceholderMapping()
        res = apply_replacements(text, [Finding(3, 10, "PASSWORD", 0.9, "x"), Finding(15, 22, "PASSWORD", 1, "p")], m)
        self.assertEqual(res.text, "pw=[PASSWORD_1] und [PASSWORD_1]")
        r0 = res.replacements[0]
        self.assertEqual(res.text[r0.out_start:r0.out_end], "[PASSWORD_1]")
        self.assertNotIn("geheim1", repr(res.replacements))

    def test_finding_repr_has_no_value(self):
        self.assertNotIn("geheim", repr(Finding(0, 6, "PASSWORD", 0.9, "x")))


class PipelineTests(unittest.TestCase):
    def test_crlf_preserved(self):
        s = make_sanitizer()
        out = s.sanitize("ip 10.1.2.3\r\nnoch mal 10.1.2.3\r\n").text
        self.assertEqual(out, "ip [IP_1]\r\nnoch mal [IP_1]\r\n")

    def test_exclude_value(self):
        s = make_sanitizer()
        out = s.sanitize("a 10.1.2.3 b 10.9.9.9", exclude={"10.1.2.3"}).text
        self.assertEqual(out, "a 10.1.2.3 b [IP_1]")

    def test_disabled_category(self):
        out = make_sanitizer(enabled_categories={"IP": False}).sanitize("a 10.1.2.3").text
        self.assertEqual(out, "a 10.1.2.3")

    def test_resanitize_is_stable(self):
        s = make_sanitizer()
        once = s.sanitize("host 10.1.2.3 mail a.b@fake-firma.de").text
        self.assertEqual(make_sanitizer().sanitize(once).text, once)

    def test_restore_ai_answer(self):
        s = make_sanitizer()
        s.sanitize("Server SqlBox7.corp.local, password=Geheim99 und 10.1.2.3")
        answer = "Verbinde dich mit [HOSTNAME_1] auf [IP_1] ([PASSWORD_1]); [IP_9] kenne ich nicht."
        res = s.mapping.restore(answer)
        self.assertEqual(res.text, "Verbinde dich mit SqlBox7.corp.local auf 10.1.2.3 (Geheim99); [IP_9] kenne ich nicht.")
        self.assertEqual(res.unknown, ["[IP_9]"])
        self.assertEqual([res.text[a:b] for a, b, _ in res.spans], ["SqlBox7.corp.local", "10.1.2.3", "Geheim99"])
        self.assertEqual([c for _, _, c in res.spans], ["HOSTNAME", "IP", "PASSWORD"])
        self.assertNotIn("Geheim99", repr(res))

    def test_restore_does_not_confuse_prefixes(self):
        m = PlaceholderMapping()
        for i in range(1, 12):
            m.placeholder_for(f"wert{i:02d}", "IP")
        self.assertEqual(m.restore("[IP_1] [IP_11]").text, "wert01 wert11")
        m.clear()
        self.assertEqual(m.restore("[IP_1]").text, "[IP_1]")


if __name__ == "__main__":
    unittest.main()
