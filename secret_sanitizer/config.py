"""Zentrale Konfiguration: Programmname, Standardwerte, Laden und Speichern.

Der Programmname steht nur hier (APP_NAME). Alles andere (Konfigurationsordner,
Fenstertitel, Umgebungsvariable) wird davon abgeleitet.

Hinweis zu den Speicherorten: config.json und user_rules.json liegen im
Benutzer-Konfigurationsordner (Windows: %APPDATA%\\<APP_NAME>), nicht im
Programmordner. Grund: In der .exe (PyInstaller) ist der Programmordner nur ein
temporäres Entpackverzeichnis; Änderungen dort wären nach dem Beenden weg.
"""

from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from .i18n import t

APP_NAME = "secret_sanitizer"
APP_TITLE = "Secret Sanitizer"
APP_VERSION = "1.3.0"

# Umgebungsvariable, mit der sich der Konfigurationsordner umlenken lässt
# (z. B. für Tests oder eine portable Installation).
HOME_ENV_VAR = APP_NAME.upper() + "_HOME"

MODES = ("strict", "normal", "loose")


def mode_label(mode: str) -> str:
    """Anzeigename eines Modus in der aktuellen Sprache."""
    return t(f"mode.{mode}")


DEFAULT_MODE_THRESHOLDS = {"strict": 0.3, "normal": 0.5, "loose": 0.75}

# Shannon-Entropie-Schwellen (Bit pro Zeichen) je Zeichensatz und Modus.
DEFAULT_ENTROPY_THRESHOLDS = {
    "strict": {"hex": 3.0, "base64": 3.6, "mixed": 3.4},
    "normal": {"hex": 3.2, "base64": 3.9, "mixed": 3.7},
    "loose": {"hex": 3.5, "base64": 4.3, "mixed": 4.1},
}
DEFAULT_ENTROPY_MIN_LENGTH = {"strict": 16, "normal": 20, "loose": 24}

DEFAULT_PLACEHOLDER_STYLE = "[{CATEGORY}_{N}]"

# Ordner und Dateien, die bei Ordnerläufen übersprungen werden (fnmatch-Muster,
# verglichen mit dem Namen und mit dem relativen Pfad, ohne Groß/klein).
DEFAULT_EXCLUDE_PATTERNS = [".git", ".svn", ".hg", "node_modules", "__pycache__", ".venv", "venv",
                            ".idea", ".vs", "*_sanitized"]


@dataclass
class Settings:
    """Alle Einstellungen mit Standardwerten (siehe Projektplan Abschnitt 7)."""

    mode: str = "strict"
    # Kategorie -> an/aus. Fehlende Kategorien gelten als eingeschaltet.
    enabled_categories: dict = field(default_factory=dict)
    # Leer = automatisch "<eingabeordner>_sanitized" neben dem Eingabeordner.
    output_dir: str = ""
    output_encoding: str = "utf-8"
    max_file_size_mb: float = 100
    max_files_per_run: int = 10000
    max_preview_chars: int = 200_000
    chunk_size: int = 1_000_000
    chunk_overlap: int = 65_536
    entropy_thresholds: dict = field(default_factory=lambda: copy.deepcopy(DEFAULT_ENTROPY_THRESHOLDS))
    entropy_min_length: dict = field(default_factory=lambda: dict(DEFAULT_ENTROPY_MIN_LENGTH))
    mode_thresholds: dict = field(default_factory=lambda: dict(DEFAULT_MODE_THRESHOLDS))
    placeholder_style: str = DEFAULT_PLACEHOLDER_STYLE
    exclude_patterns: list = field(default_factory=lambda: list(DEFAULT_EXCLUDE_PATTERNS))
    # Ordner- und Dateinamen in der Ausgabe ebenfalls bereinigen (und im Bericht nur
    # die bereinigten Namen zeigen)
    sanitize_filenames: bool = False
    # Archive (.zip, .tar, .tar.gz/.tgz, .gz) entpacken, Inhalt bereinigen, wieder einpacken
    process_archives: bool = True
    max_archive_mb: float = 500
    # CPU-Kerne für Ordnerläufe: 0 = automatisch (Kerne - 1, höchstens 8), 1 = nur ein Kern
    workers: int = 0
    # Word/Excel/PowerPoint (.docx, .xlsx, .pptx) bereinigen; Bilder und eingebettete Objekte entfernen
    process_office: bool = True
    office_remove_media: bool = True
    # PDF: Text herausziehen und als bereinigte .txt ausgeben (in eigenem Prozess mit Limits)
    process_pdf: bool = True
    pdf_timeout_s: int = 60
    pdf_max_memory_mb: int = 1024
    # Oberflächensprache: "auto" (Systemsprache), "de" oder "en"
    language: str = "auto"

    # ------------------------------------------------------------------
    def is_category_enabled(self, category: str) -> bool:
        return bool(self.enabled_categories.get(category, True))

    def threshold(self) -> float:
        return float(self.mode_thresholds.get(self.mode, DEFAULT_MODE_THRESHOLDS["strict"]))

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Settings":
        """Erzeugt Settings aus einem Dict. Unbekannte oder ungültige Werte
        werden durch Standardwerte ersetzt, damit eine kaputte Config das
        Programm nicht lahmlegt."""
        settings = cls()
        if not isinstance(data, dict):
            return settings
        known = {f.name for f in fields(cls)}
        for key, value in data.items():
            if key not in known:
                continue
            default = getattr(settings, key)
            if isinstance(default, bool) or default is None:
                ok = isinstance(value, type(default))
            elif isinstance(default, (int, float)):
                ok = isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0
            else:
                ok = isinstance(value, type(default))
            if ok:
                if isinstance(default, dict):
                    merged = copy.deepcopy(default)
                    merged.update(value)
                    value = merged
                setattr(settings, key, value)
        settings._validate()
        return settings

    def _validate(self) -> None:
        if self.mode not in MODES:
            self.mode = "strict"
        if self.language not in ("auto", "de", "en"):
            self.language = "auto"
        if "{CATEGORY}" not in self.placeholder_style or "{N}" not in self.placeholder_style:
            self.placeholder_style = DEFAULT_PLACEHOLDER_STYLE
        self.max_files_per_run = int(self.max_files_per_run)
        self.max_preview_chars = int(self.max_preview_chars)
        self.chunk_size = max(10_000, int(self.chunk_size))
        self.chunk_overlap = max(1_000, min(int(self.chunk_overlap), self.chunk_size // 2))
        self.exclude_patterns = [str(p).strip() for p in self.exclude_patterns if str(p).strip()]
        try:
            "".encode(self.output_encoding)
        except (LookupError, TypeError):
            self.output_encoding = "utf-8"


# ----------------------------------------------------------------------
# Speicherorte
# ----------------------------------------------------------------------

def config_dir() -> Path:
    """Ordner für config.json und user_rules.json."""
    override = os.environ.get(HOME_ENV_VAR)
    if override:
        return Path(override)
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / APP_NAME
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / APP_NAME


def config_path() -> Path:
    return config_dir() / "config.json"


def user_rules_path() -> Path:
    return config_dir() / "user_rules.json"


def package_dir() -> Path:
    """Ordner des Pakets, funktioniert auch in der PyInstaller-.exe."""
    frozen_base = getattr(sys, "_MEIPASS", None)
    if frozen_base:
        return Path(frozen_base) / APP_NAME
    return Path(__file__).resolve().parent


def default_rules_path() -> Path:
    return package_dir() / "rules" / "default_rules.json"


def user_rules_template_path() -> Path:
    return package_dir() / "rules" / "user_rules.json"


# ----------------------------------------------------------------------
# Laden / Speichern
# ----------------------------------------------------------------------

def load_settings(path: Path | None = None) -> Settings:
    """Lädt die Einstellungen. Fehlt die Datei oder ist sie kaputt, werden
    die Standardwerte verwendet (die Datei selbst wird dabei nicht verändert)."""
    path = Path(path) if path else config_path()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return Settings.from_dict(json.load(fh))
    except (OSError, ValueError):
        return Settings()


def save_settings(settings: Settings, path: Path | None = None) -> Path:
    path = Path(path) if path else config_path()
    write_json_atomic(path, settings.to_dict())
    return path


def write_json_atomic(path: Path, data) -> None:
    """Schreibt JSON erst in eine temporäre Datei und benennt sie dann um,
    damit bei einem Absturz keine halbe Datei zurückbleibt."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp_", suffix=".json", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
