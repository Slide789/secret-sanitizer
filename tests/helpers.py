"""Hilfsfunktionen für die Tests.

Temporäre Dateien landen in tests/_tmp/ (innerhalb des Projektordners), und
der Konfigurationsordner wird dorthin umgelenkt, damit Tests nie die echte
Benutzer-Konfiguration anfassen.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TMP_ROOT = ROOT / "tests" / "_tmp"
TMP_ROOT.mkdir(parents=True, exist_ok=True)

from secret_sanitizer import config  # noqa: E402

os.environ[config.HOME_ENV_VAR] = str(TMP_ROOT / "config_home")

from secret_sanitizer.config import Settings  # noqa: E402
from secret_sanitizer.core.pipeline import Sanitizer, load_default_ruleset  # noqa: E402

from tests.fake_data import FAKE_DIR, FALSE_POSITIVES, SECRETS, generate  # noqa: E402,F401

_RULESET = None


def copy_fake_data(target: Path, subdir: str = "") -> Path:
    """Erzeugt die Fake-Testdaten frisch in target, statt tests/fake_secrets zu
    kopieren. So beeinflussen dort liegengebliebene Dateien (z. B. die Ausgabe
    eines Probelaufs) keinen Test. subdir: nur diesen Unterordner übernehmen."""
    if not subdir:
        generate(target)
        return target
    staging = Path(tempfile.mkdtemp(prefix="fake_", dir=str(TMP_ROOT)))
    try:
        generate(staging)
        shutil.copytree(staging / subdir, target)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return target


def default_ruleset():
    """Mitgelieferte Regeln (ohne eigene Regeln), einmal geladen."""
    global _RULESET
    if _RULESET is None:
        _RULESET = load_default_ruleset(include_user_rules=False)
    return _RULESET


def make_sanitizer(mode: str = "strict", ruleset=None, **settings_kwargs) -> Sanitizer:
    settings = Settings(mode=mode, **settings_kwargs)
    return Sanitizer(settings, ruleset if ruleset is not None else default_ruleset())


def sanitize(text: str, mode: str = "strict", **kwargs) -> str:
    return make_sanitizer(mode, **kwargs).sanitize(text).text


class TempDirTestCase(unittest.TestCase):
    """Stellt self.tmp (eigener Ordner unter tests/_tmp) bereit."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix=self.__class__.__name__ + "_", dir=str(TMP_ROOT)))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)


class SecretAssertions:
    def assertNoSecrets(self, text: str, keys=None, msg: str = "") -> None:
        keys = keys or list(SECRETS)
        for key in keys:
            value = SECRETS[key]
            self.assertNotIn(value, text, f"Secret '{key}' ist noch enthalten {msg}")
            self.assertNotIn(value.casefold(), text.casefold(), f"Secret '{key}' (andere Schreibweise) {msg}")
