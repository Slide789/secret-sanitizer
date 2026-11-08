"""Tests für das Übersetzungsmodul (Sprachdateien, Auflösung, Einstellung)."""

from __future__ import annotations

import os
import re
import string
import unittest
from pathlib import Path
from unittest import mock

from tests.helpers import ROOT, Settings  # noqa: F401  (richtet Umgebung ein)

import json

from secret_sanitizer import i18n
from secret_sanitizer.config import MODES, default_rules_path
from secret_sanitizer.core.models import CATEGORIES, GROUPS
from secret_sanitizer.core.rules import UserRules, load_ruleset, rule_from_dict


def _fields(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def _texts(lang: str) -> dict[str, str]:
    return {k: v for k, v in i18n.load_catalog(lang).items() if k != "_argparse"}


class CatalogTests(unittest.TestCase):
    def test_catalogs_have_same_keys(self):
        self.assertEqual(set(i18n.load_catalog("de")) - {"_argparse"}, set(i18n.load_catalog("en")))

    def test_catalogs_not_empty(self):
        for lang in i18n.LANGUAGES:
            catalog = i18n.load_catalog(lang)
            self.assertGreater(len(catalog), 1, lang)
            self.assertIn("app.title", catalog, lang)

    def test_no_empty_texts(self):
        for lang in i18n.LANGUAGES:
            for key, value in _texts(lang).items():
                self.assertTrue(value.strip(), f"{lang}:{key} ist leer")

    def test_placeholders_match(self):
        de, en = _texts("de"), _texts("en")
        for key in de:
            self.assertEqual(_fields(de[key]), _fields(en[key]), key)

    def test_every_text_formats(self):
        for lang in i18n.LANGUAGES:
            for key, text in _texts(lang).items():
                felder = _fields(text)
                if felder:
                    text.format(**{f: "x" for f in felder})

    def test_all_t_keys_exist(self):
        de, en = _texts("de"), _texts("en")
        for path in (ROOT / "secret_sanitizer").rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            for key in re.findall(r'''\bt\(\s*["']([^"']+)["']''', source):
                self.assertIn(key, de, f"{path.name}: {key} fehlt in de")
                self.assertIn(key, en, f"{path.name}: {key} fehlt in en")


class DomainTextTests(unittest.TestCase):
    def setUp(self):
        self._old = i18n.current_language()
        self.addCleanup(i18n.set_language, self._old)
        i18n.set_language("de")

    def test_every_category_translated(self):
        for lang in i18n.LANGUAGES:
            catalog = i18n.load_catalog(lang)
            for cid in CATEGORIES:
                self.assertIn(f"category.{cid}.label", catalog, f"{lang}:{cid}")
                self.assertIn(f"category.{cid}.description", catalog, f"{lang}:{cid}")

    def test_every_group_and_mode_translated(self):
        for lang in i18n.LANGUAGES:
            catalog = i18n.load_catalog(lang)
            for g in GROUPS:
                self.assertIn(f"group.{g}", catalog, f"{lang}:{g}")
            for m in MODES:
                self.assertIn(f"mode.{m}", catalog, f"{lang}:{m}")

    def test_every_builtin_rule_translated(self):
        data = json.loads(default_rules_path().read_text(encoding="utf-8"))
        for lang in i18n.LANGUAGES:
            catalog = i18n.load_catalog(lang)
            for rule in data["rules"]:
                self.assertIn(f"rule.{rule['id']}.name", catalog, f"{lang}:{rule['id']}")
                self.assertIn(f"rule.{rule['id']}.description", catalog, f"{lang}:{rule['id']}")

    def test_category_label_follows_language(self):
        i18n.set_language("en")
        self.assertEqual(CATEGORIES["PASSWORD"].label, "Passwords")
        i18n.set_language("de")
        self.assertEqual(CATEGORIES["PASSWORD"].label, "Passwörter")

    def test_builtin_rule_follows_language(self):
        i18n.set_language("en")
        rs = load_ruleset(default_rules_path())
        rule = next(r for r in rs.rules if r.id == "aws_access_key")
        self.assertEqual(rule.name, i18n.t("rule.aws_access_key.name"))

    def test_user_rule_name_not_translated(self):
        i18n.set_language("en")
        mine = rule_from_dict({"id": "aws_access_key", "name": "Meine AWS-Regel", "category": "API_KEY",
                               "pattern": "AKIA[0-9A-Z]{16}"})
        user = UserRules(rules=[mine])
        from secret_sanitizer.core.rules import merge_user_rules
        rs = merge_user_rules(load_ruleset(default_rules_path()), user)
        rule = next(r for r in rs.rules if r.id == "aws_access_key")
        self.assertEqual(rule.name, "Meine AWS-Regel")


class TranslateTests(unittest.TestCase):
    def setUp(self):
        self._old = i18n.current_language()
        self.addCleanup(i18n.set_language, self._old)

    def test_t_without_values_returns_raw(self):
        for lang in i18n.LANGUAGES:
            i18n.set_language(lang)
            self.assertEqual(i18n.t("test.braces"), "[{CATEGORY}_{N}]")

    def test_t_formats_values(self):
        with mock.patch.dict(i18n._catalogs, {"en": {"x.y": "Hallo {name}"}, "de": {"x.y": "Hallo {name}"}}):
            i18n.set_language("de")
            self.assertEqual(i18n.t("x.y", name="Welt"), "Hallo Welt")

    def test_missing_key_falls_back(self):
        i18n.set_language("de")
        self.assertEqual(i18n.t("gibt.es.nicht"), "gibt.es.nicht")
        self.assertFalse(i18n.has_key("gibt.es.nicht"))
        self.assertTrue(i18n.has_key("app.title"))

    def test_invalid_language(self):
        with self.assertRaises(ValueError):
            i18n.set_language("fr")


class ResolveTests(unittest.TestCase):
    def test_resolve_order(self):
        with mock.patch("secret_sanitizer.i18n.detect_system_language", return_value="de"):
            with mock.patch.dict(os.environ, {i18n.LANG_ENV_VAR: "en"}):
                self.assertEqual(i18n.resolve_language("de", "en"), "de")   # cli
                self.assertEqual(i18n.resolve_language(None, "de"), "en")   # env vor setting
            env = {k: v for k, v in os.environ.items() if k != i18n.LANG_ENV_VAR}
            with mock.patch.dict(os.environ, env, clear=True):
                self.assertEqual(i18n.resolve_language(None, "en"), "en")   # setting
                self.assertEqual(i18n.resolve_language(None, "auto"), "de")  # system
            with mock.patch.dict(os.environ, {i18n.LANG_ENV_VAR: "xx"}):
                self.assertEqual(i18n.resolve_language(None, "en"), "en")   # ungültige env ignoriert

    def test_detect_system_language_error_is_english(self):
        with mock.patch("secret_sanitizer.i18n._windows_ui_langid", side_effect=OSError):
            with mock.patch("locale.getlocale", return_value=(None, None)):
                self.assertEqual(i18n.detect_system_language(), "en")

    def test_detect_system_language_german(self):
        with mock.patch("secret_sanitizer.i18n._windows_ui_langid", return_value=0x0407):
            self.assertEqual(i18n.detect_system_language(), "de")
        with mock.patch("secret_sanitizer.i18n._windows_ui_langid", return_value=0x0409):
            self.assertEqual(i18n.detect_system_language(), "en")


class SettingsTests(unittest.TestCase):
    def test_settings_language_invalid(self):
        for v in ("fr", 5, None, ""):
            self.assertEqual(Settings.from_dict({"language": v}).language, "auto", v)
        self.assertEqual(Settings.from_dict({}).language, "auto")
        self.assertEqual(Settings.from_dict({"language": "en"}).language, "en")


if __name__ == "__main__":
    unittest.main()
