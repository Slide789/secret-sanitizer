"""Hauptfenster.

Aufbau (Projektplan Abschnitt 10):
  oben:   Modus-Umschalter, Kategorie-Häkchen, deutlicher Prüf-Hinweis
  Mitte:  links "Original", rechts "Bereinigt", Treffer farbig nach Kategorie
  unten:  Trefferliste mit "doch nicht ersetzen", großer Kopier-Button
  Tabs:   Text & Vorschau | Dateien & Ordner | Regeln | Einstellungen

Das Mapping (Wert -> Platzhalter) existiert nur im Arbeitsspeicher.
"""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

# Drag & Drop ist optional: fehlt tkinterdnd2, läuft alles andere normal weiter.
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    _DND_BASES: tuple = (TkinterDnD.DnDWrapper,)
except ImportError:  # pragma: no cover - abhängig von der Installation
    TkinterDnD = None
    DND_FILES = ""
    _DND_BASES = ()

from .. import config
from ..config import APP_TITLE, APP_VERSION, MODES, Settings, load_settings, mode_label, save_settings
from ..core.models import PERSONAL_CATEGORIES
from ..core.files import (FileRun, LoadedText, RunError, load_text_file, safe_reason, sanitize_path_part,
                          save_sanitized_text)
from ..core.archives import archive_kind
from ..core.office import office_kind
from ..core.pdf import is_pdf
from ..core.pipeline import Sanitizer
from ..core.replacer import value_key
from ..core.rules import load_ruleset, load_user_rules, merge_user_rules, save_user_rules, slow_pattern_warnings
from ..i18n import LANG_ENV_VAR, current_language, detect_system_language, resolve_language, set_language, t
from . import dialogs
from .rule_editor import RuleEditor
from .widgets import CategoryPanel, FindingTable, HighlightTextbox

PREVIEW_DELAY_MS = 500
# Ab dieser Textlänge läuft die Vorschau im Hintergrund, damit das Fenster
# beim Einfügen großer Texte nicht einfriert.
ASYNC_PREVIEW_CHARS = 50_000
LANGUAGE_CHOICES = ("auto", "de", "en")   # Werte des Sprachfelds in Settings.language


def _fmt_int(n: int) -> str:
    """Zahl mit Tausendertrennung in der Schreibweise der App-Sprache (1.234 bzw. 1,234)."""
    text = f"{n:,}"
    return text.replace(",", ".") if current_language() == "de" else text


def _without_lang_args(args: list[str]) -> list[str]:
    """Kommandozeile ohne --lang (sonst überstimmte sie die neu gewählte Sprache)."""
    out: list[str] = []
    skip = False
    for arg in args:
        if skip:
            skip = False
        elif arg == "--lang":
            skip = True
        elif not arg.startswith("--lang="):
            out.append(arg)
    return out


def restart_app(app=None) -> None:
    """Startet die App neu und schließt danach das Fenster. Die neu gewählte Sprache steht schon in
    config.json; --lang und SECRET_SANITIZER_LANG würden sie überstimmen und werden deshalb nicht
    an den neuen Prozess weitergegeben."""
    if getattr(sys, "frozen", False):
        cmd = [sys.executable, *_without_lang_args(sys.argv[1:])]
    else:
        cmd = [sys.executable, "-m", "secret_sanitizer", "--gui"]
    env = {k: v for k, v in os.environ.items() if k != LANG_ENV_VAR}
    if getattr(sys, "frozen", False):
        # PyInstaller (onefile): ohne Reset hielte der neue Prozess sich für einen Unterprozess und
        # nutzte den _MEI-Ordner des alten, den dessen Bootloader beim Beenden löscht.
        env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    subprocess.Popen(cmd, env=env)
    if app is not None:
        app._on_close()


class App(ctk.CTk, *_DND_BASES):
    def __init__(self, lang: str | None = None) -> None:
        """lang: vom Aufrufer vorgegebene Sprache (z. B. aus --lang); ohne Angabe gilt
        Umgebungsvariable -> Einstellung -> Systemsprache."""
        super().__init__()
        ctk.set_appearance_mode("system")
        ctk.set_default_color_theme("blue")
        self.title(f"{APP_TITLE} {APP_VERSION}")
        self.geometry("1360x900")
        self.minsize(1000, 680)

        self.settings: Settings = load_settings()
        set_language(resolve_language(lang, self.settings.language))
        self.user_rules = load_user_rules(config.user_rules_path())
        self.ruleset = None
        self._rebuild_ruleset()

        # Ausnahmen ("doch nicht ersetzen"): eigener Schlüssel je Wert, nicht der
        # Platzhalter, denn [IP_1] bezeichnet nach neuem Text einen anderen Wert
        self.excluded: dict[str, dict] = {}        # "ex:<wert-schlüssel>" -> {keys, category, value}
        self.excluded_keys: set[str] = set()
        self.result = None
        self.result_text_original = ""
        self.loaded_file: tuple[Path, LoadedText] | None = None
        self._groups: dict[str, dict] = {}
        self._preview_job = None
        self._worker: threading.Thread | None = None
        self._queue: queue.Queue = queue.Queue()
        self._cancel = threading.Event()
        # Sitzungen (mit Mapping) der letzten Vorschau und des letzten Ordnerlaufs,
        # nur im Arbeitsspeicher, für die Rückübersetzung von Antworten
        self._text_sanitizer: Sanitizer | None = None
        self._run_sanitizer: Sanitizer | None = None
        self._preview_gen = 0          # zählt Vorschau-Aufträge; alte Ergebnisse werden verworfen
        self._preview_pending = False

        # Reiternamen: Code, der Reiter über den Namen anspricht, nutzt dieselben t()-Werte
        self.TAB_TEXT = t("gui.tab.text")
        self.TAB_FILES = t("gui.tab.files")
        self.TAB_RESTORE = t("gui.tab.restore")
        self.TAB_RULES = t("gui.tab.rules")
        self.TAB_SETTINGS = t("gui.tab.settings")
        self.RESTORE_SOURCES = (t("gui.restore.source_text"), t("gui.restore.source_run"))

        self._build_top()
        self.tabs = ctk.CTkTabview(self)
        self.tabs.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self._build_text_tab(self.tabs.add(self.TAB_TEXT))
        self._build_files_tab(self.tabs.add(self.TAB_FILES))
        self._build_restore_tab(self.tabs.add(self.TAB_RESTORE))
        self._build_rules_tab(self.tabs.add(self.TAB_RULES))
        self._build_settings_tab(self.tabs.add(self.TAB_SETTINGS))
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.dnd_enabled = self._enable_drag_and_drop()
        self.after(100, self._poll_queue)
        if self.ruleset.errors:
            self.after(300, lambda: dialogs.show_warning(
                t("gui.tab.rules"), t("gui.rules.invalid_some", errors="\n".join(self.ruleset.errors)), self))
        slow = slow_pattern_warnings(self.ruleset)
        if slow:
            self.after(400, lambda: dialogs.show_warning(
                t("gui.tab.rules"), t("gui.rules.slow_warn", warnings="\n".join(slow)), self))

    # ------------------------------------------------------------------
    # Regeln / Sanitizer
    # ------------------------------------------------------------------
    def _rebuild_ruleset(self) -> None:
        ruleset = load_ruleset(config.default_rules_path())
        self.ruleset = merge_user_rules(ruleset, self.user_rules)

    def _new_sanitizer(self) -> Sanitizer:
        return Sanitizer(self.settings, self.ruleset)

    def _save_user_rules(self, user_rules) -> Path:
        path = config.user_rules_path()
        save_user_rules(user_rules, path)
        self.user_rules = load_user_rules(path)
        self._rebuild_ruleset()
        self.schedule_preview(immediate=True)
        return path

    # ------------------------------------------------------------------
    # Kopfbereich
    # ------------------------------------------------------------------
    def _build_top(self) -> None:
        top = ctk.CTkFrame(self)
        top.pack(fill="x", padx=10, pady=(10, 6))
        left = ctk.CTkFrame(top, fg_color="transparent")
        left.pack(side="left", anchor="n", padx=8, pady=6)
        ctk.CTkLabel(left, text=t("gui.mode"), font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w")
        self.mode_var = tk.StringVar(value=mode_label(self.settings.mode))
        ctk.CTkSegmentedButton(left, values=[mode_label(m) for m in MODES], variable=self.mode_var,
                               command=self._mode_changed).pack(anchor="w", pady=4)
        self.mode_hint = ctk.CTkLabel(left, text="", text_color="gray", wraplength=230, justify="left")
        self.mode_hint.pack(anchor="w")
        self._update_mode_hint()

        self.categories = CategoryPanel(top, self.settings.enabled_categories, self._categories_changed,
                                        fg_color="transparent")
        self.categories.pack(side="left", fill="x", expand=True, padx=4, pady=4)
        self._categories_visible = True
        self.cat_toggle = ctk.CTkButton(top, text=t("gui.categories.hide"), width=130, fg_color="gray40", hover_color="gray30",
                                        command=self._toggle_categories)
        self.cat_toggle.pack(side="right", anchor="n", padx=8, pady=8)

        banner = ctk.CTkLabel(self, text=t("gui.banner"), fg_color="#7e5109", text_color="#ffffff", corner_radius=6,
                              font=ctk.CTkFont(size=13, weight="bold"), height=34, wraplength=1300)
        banner.pack(fill="x", padx=10, pady=(0, 6))

    def _toggle_categories(self) -> None:
        """Kategorie-Häkchen ein-/ausklappen (mehr Platz für die Vorschau)."""
        if self._categories_visible:
            self.categories.pack_forget()
            self.cat_toggle.configure(text=t("gui.categories.show"))
        else:
            self.categories.pack(side="left", fill="x", expand=True, padx=4, pady=4, before=self.cat_toggle)
            self.cat_toggle.configure(text=t("gui.categories.hide"))
        self._categories_visible = not self._categories_visible

    def _update_mode_hint(self) -> None:
        self.mode_hint.configure(text=t(f"gui.mode_hint.{self.settings.mode}"))

    def _mode_changed(self, label: str) -> None:
        mode = next(m for m in MODES if mode_label(m) == label)
        self.settings.mode = mode
        self._update_mode_hint()
        self._persist_settings()
        self.schedule_preview(immediate=True)

    def _categories_changed(self, values: dict) -> None:
        self.settings.enabled_categories = values
        self._persist_settings()
        self.schedule_preview(immediate=True)

    def _apply_profile_settings(self, values: dict) -> None:
        """Modus und Kategorien aus einem Profil übernehmen."""
        if values.get("mode") in MODES:
            self.settings.mode = values["mode"]
            self.mode_var.set(mode_label(self.settings.mode))
            self._update_mode_hint()
        if isinstance(values.get("enabled_categories"), dict):
            self.settings.enabled_categories = {**self.settings.enabled_categories, **values["enabled_categories"]}
            for cat, var in self.categories.vars.items():
                var.set(self.settings.is_category_enabled(cat))
            self.categories.personal_var.set(all(self.categories.vars[c].get() for c in PERSONAL_CATEGORIES))
        self._persist_settings()
        self.schedule_preview(immediate=True)

    def _persist_settings(self) -> bool:
        """Speichert die Einstellungen; False, wenn das Speichern fehlschlug (Toast ist gezeigt)."""
        try:
            save_settings(self.settings)
        except OSError as exc:
            self._toast(t("gui.toast.settings_not_saved", name=type(exc).__name__), error=True)
            return False
        return True

    # ------------------------------------------------------------------
    # Tab: Text & Vorschau
    # ------------------------------------------------------------------
    def _build_text_tab(self, tab) -> None:
        tab.grid_columnconfigure((0, 1), weight=1)
        tab.grid_rowconfigure(1, weight=4)
        tab.grid_rowconfigure(3, weight=1)

        bar = ctk.CTkFrame(tab, fg_color="transparent")
        bar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 4))
        ctk.CTkButton(bar, text=t("gui.text.open_file"), width=130, command=self.open_file).pack(side="left", padx=(0, 6))
        ctk.CTkButton(bar, text=t("gui.text.choose_folder"), width=130, command=self.choose_folder_from_text_tab).pack(side="left", padx=6)
        ctk.CTkButton(bar, text=t("gui.text.paste"), width=210, command=self.paste_clipboard).pack(side="left", padx=6)
        ctk.CTkButton(bar, text=t("gui.text.clear"), width=90, fg_color="gray40", hover_color="gray30",
                      command=self.clear_text).pack(side="left", padx=6)
        self.save_file_btn = ctk.CTkButton(bar, text=t("gui.text.save_file"), width=210, state="disabled",
                                           command=self.save_loaded_file)
        self.save_file_btn.pack(side="right", padx=6)
        self.source_label = ctk.CTkLabel(bar, text=t("gui.text.source_pasted"), text_color="gray")
        self.source_label.pack(side="right", padx=10)

        left = ctk.CTkFrame(tab)
        left.grid(row=1, column=0, sticky="nsew", padx=(0, 4))
        right = ctk.CTkFrame(tab)
        right.grid(row=1, column=1, sticky="nsew", padx=(4, 0))
        for frame, title in ((left, t("gui.text.original")), (right, t("gui.text.clean"))):
            frame.grid_rowconfigure(1, weight=1)
            frame.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(frame, text=title, font=ctk.CTkFont(size=14, weight="bold")).grid(row=0, column=0, sticky="w",
                                                                                           padx=8, pady=(6, 2))
        self.original_box = HighlightTextbox(left)
        self.original_box.grid(row=1, column=0, sticky="nsew", padx=6, pady=(0, 6))
        self.original_box.bind("<KeyRelease>", lambda _e: self.schedule_preview())
        self.original_box.bind("<<Paste>>", lambda _e: self.after(50, self.schedule_preview))
        self.clean_box = HighlightTextbox(right, readonly=True)
        self.clean_box.grid(row=1, column=0, sticky="nsew", padx=6, pady=(0, 6))

        info = ctk.CTkFrame(tab, fg_color="transparent")
        info.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(6, 2))
        ctk.CTkLabel(info, text=t("gui.text.findings"), font=ctk.CTkFont(size=14, weight="bold")).pack(side="left")
        self.summary_label = ctk.CTkLabel(info, text="", text_color="gray")
        self.summary_label.pack(side="left", padx=10)
        self.toggle_btn = ctk.CTkButton(info, text=t("gui.text.exclude"), width=170, command=self.toggle_selected,
                                        state="disabled")
        self.toggle_btn.pack(side="right")
        self.allow_btn = ctk.CTkButton(info, text=t("gui.text.always_ignore"), width=150, fg_color="gray40",
                                       hover_color="gray30", command=self.always_ignore_selected, state="disabled")
        self.allow_btn.pack(side="right", padx=(0, 8))
        ctk.CTkLabel(info, text=t("gui.text.dblclick_hint"), text_color="gray").pack(side="right", padx=10)

        self.table = FindingTable(tab, on_select=self._row_selected, on_toggle=self.toggle_exclude)
        self.table.grid(row=3, column=0, columnspan=2, sticky="nsew")

        bottom = ctk.CTkFrame(tab, fg_color="transparent")
        bottom.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        self.copy_btn = ctk.CTkButton(bottom, text=t("gui.text.copy"), height=48,
                                      font=ctk.CTkFont(size=17, weight="bold"), command=self.copy_result)
        self.copy_btn.pack(fill="x")
        self.toast_label = ctk.CTkLabel(bottom, text="", text_color="#27ae60")
        self.toast_label.pack(anchor="w")

    def _toast(self, text: str, error: bool = False) -> None:
        self.toast_label.configure(text=text, text_color="#e74c3c" if error else "#27ae60")
        self.after(5000, lambda: self.toast_label.configure(text=""))

    def schedule_preview(self, immediate: bool = False) -> None:
        if self._preview_job is not None:
            self.after_cancel(self._preview_job)
        self._preview_job = self.after(10 if immediate else PREVIEW_DELAY_MS, self.run_preview)

    def run_preview(self, sync: bool = False) -> None:
        """Aktualisiert die Vorschau. Große Texte werden im Hintergrund analysiert
        (außer bei sync=True, z. B. direkt vor dem Kopieren oder Speichern)."""
        if self._preview_job is not None:
            self.after_cancel(self._preview_job)
        self._preview_job = None
        self._preview_gen += 1
        self._preview_pending = False
        text = self.original_box.get_text()
        if not text:
            self.result = None
            self._text_sanitizer = None
            self.clean_box.set_text("")
            self.table.set_rows([])
            self.summary_label.configure(text="")
            self.original_box.clear_highlights()
            return
        # Neue Sitzung pro Vorschau: Nummerierung beginnt immer bei 1
        sanitizer = self._new_sanitizer()
        exclude = set(self.excluded_keys)
        if not sync and len(text) >= ASYNC_PREVIEW_CHARS:
            gen = self._preview_gen
            self._preview_pending = True
            self.summary_label.configure(text=t("gui.text.analyzing", n=_fmt_int(len(text))))
            self.config(cursor="watch")

            def work() -> None:
                try:
                    result = sanitizer.sanitize(text, exclude=exclude)
                    self._queue.put(("preview", gen, text, sanitizer, result))
                except Exception as exc:  # noqa: BLE001 - Meldung ohne Inhalt
                    self._queue.put(("preview_error", gen, safe_reason(exc)))

            threading.Thread(target=work, daemon=True).start()
            return
        self.config(cursor="watch")
        self.update_idletasks()
        try:
            result = sanitizer.sanitize(text, exclude=exclude)
        finally:
            self.config(cursor="")
        self._apply_preview(text, sanitizer, result)

    def _apply_preview(self, text: str, sanitizer: Sanitizer, result) -> None:
        self.result = result
        self._text_sanitizer = sanitizer
        self.result_text_original = text
        large = len(text) > self.settings.max_preview_chars
        if large:
            self._show_large_summary()
        else:
            self.clean_box.set_text(self.result.text)
            self.original_box.highlight((r.start, r.end, r.category) for r in self.result.replacements)
            self.clean_box.highlight((r.out_start, r.out_end, r.category) for r in self.result.replacements)
        self._fill_table(text)

    def _show_large_summary(self) -> None:
        """Über max_preview_chars: keine farbige Live-Vorschau (tkinter wäre zu
        langsam), sondern Zusammenfassung und Stichproben."""
        self.original_box.clear_highlights()
        counts = self.result.counts_by_category()
        lines = [t("gui.text.large_title", limit=_fmt_int(self.settings.max_preview_chars)),
                 t("gui.text.large_no_preview"), "",
                 t("gui.text.large_counts", counts=", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
                   or t("gui.text.none")), "",
                 t("gui.text.large_samples")]
        out_lines = self.result.text.split("\n")
        seen = set()
        for rep in self.result.replacements:
            line_no = self.result.text.count("\n", 0, rep.out_start)
            if line_no in seen:
                continue
            seen.add(line_no)
            lines.append("  " + out_lines[line_no][:200])
            if len(seen) >= 15:
                break
        self.clean_box.set_text("\n".join(lines))

    def _fill_table(self, text: str) -> None:
        groups: dict[str, dict] = {}
        for rep in self.result.replacements:
            value = text[rep.start:rep.end]
            g = groups.setdefault(rep.placeholder, {"key": rep.placeholder, "placeholder": rep.placeholder,
                                                    "category": rep.category, "value": value, "count": 0,
                                                    "detectors": set(), "confidence": 0.0, "keys": set(),
                                                    "excluded": False, "spans": [], "out_spans": []})
            g["count"] += 1
            g["detectors"].add(rep.detector)
            g["confidence"] = max(g["confidence"], rep.confidence)
            g["keys"].add(value_key(value))
            g["spans"].append((rep.start, rep.end))
            g["out_spans"].append((rep.out_start, rep.out_end))
        rows = sorted(groups.values(), key=lambda g: (g["category"], _placeholder_number(g["placeholder"])))
        for name, info in self.excluded.items():
            rows.append({"key": name, "placeholder": name, "category": info["category"], "value": info["value"],
                         "count": "-", "detectors": set(), "confidence": 0.0, "excluded": True})
        self._groups = groups
        self.table.set_rows(rows)
        total = len(self.result.replacements)
        self.summary_label.configure(text=t("gui.text.summary", total=total, values=len(groups),
                                            excluded=len(self.excluded)))
        self.toggle_btn.configure(state="disabled")
        self.allow_btn.configure(state="disabled")

    def _row_selected(self, key: str) -> None:
        self.toggle_btn.configure(state="normal",
                                  text=t("gui.text.include") if key in self.excluded else t("gui.text.exclude"))
        self.allow_btn.configure(state="normal")
        group = self._groups.get(key)
        if group and len(self.result_text_original) <= self.settings.max_preview_chars:
            self.original_box.mark(group["spans"])
            self.clean_box.mark(group["out_spans"])

    def toggle_selected(self) -> None:
        key = self.table.selected_key()
        if key is not None:
            self.toggle_exclude(key)

    def toggle_exclude(self, key: str) -> None:
        """'Doch nicht ersetzen': nimmt den Wert (alle Vorkommen) aus. Ausnahmen
        gelten nur für diese Sitzung und werden nicht gespeichert."""
        if key in self.excluded:
            info = self.excluded.pop(key)
            self.excluded_keys -= info["keys"]
        else:
            group = self._groups.get(key)
            if not group:
                return
            ex_key = "ex:" + min(group["keys"])
            self.excluded[ex_key] = {"keys": set(group["keys"]), "category": group["category"],
                                    "value": group["value"]}
            self.excluded_keys |= group["keys"]
        self.run_preview()

    def always_ignore_selected(self) -> None:
        """'Immer ignorieren': Wert dauerhaft in die Allowlist übernehmen."""
        key = self.table.selected_key()
        if key is None:
            return
        info = self._groups.get(key) or self.excluded.get(key)
        if not info:
            return
        value = info["value"].strip()
        if not value or "\n" in value:
            dialogs.show_error(t("gui.ignore.title"), t("gui.ignore.multiline"), parent=self)
            return
        if not dialogs.ask_yes_no(t("gui.ignore.title"), t("gui.ignore.confirm", n=len(value)), parent=self):
            return
        if key in self.excluded:
            self.excluded_keys -= self.excluded.pop(key)["keys"]
        if self.rule_editor.add_allow_entry(value):
            self._toast(t("gui.ignore.done", tab=self.TAB_RULES))

    def copy_result(self) -> None:
        if self._preview_pending or self.original_box.get_text() != self.result_text_original:
            self.run_preview(sync=True)
        if not self.result:
            self._toast(t("gui.toast.nothing"), error=True)
            return
        self.clipboard_clear()
        self.clipboard_append(self.result.text)
        self._toast(t("gui.toast.copied"))

    def paste_clipboard(self) -> None:
        try:
            text = self.clipboard_get()
        except tk.TclError:
            self._toast(t("gui.toast.clipboard_empty"), error=True)
            return
        self._set_original(text.replace("\r\n", "\n"), None)

    def clear_text(self) -> None:
        self.excluded.clear()
        self.excluded_keys.clear()
        self._set_original("", None)

    def _set_original(self, text: str, loaded: tuple[Path, LoadedText] | None) -> None:
        self.loaded_file = loaded
        self.original_box.set_text(text)
        if loaded:
            self.source_label.configure(text=t("gui.text.source_file", name=loaded[0].name, encoding=loaded[1].encoding))
            self.save_file_btn.configure(state="normal")
        else:
            self.source_label.configure(text=t("gui.text.source_pasted"))
            self.save_file_btn.configure(state="disabled")
        self.schedule_preview(immediate=True)

    def _enable_drag_and_drop(self) -> bool:
        """Dateien und Ordner aufs Fenster ziehen. Lädt die mitgelieferte
        tkdnd-Bibliothek; klappt das nicht, bleibt die App ohne Drag & Drop."""
        if TkinterDnD is None:
            return False
        try:
            self.TkdndVersion = TkinterDnD._require(self)
            self.drop_target_register(DND_FILES)
            self.dnd_bind("<<Drop>>", self._on_drop)
        except (tk.TclError, RuntimeError, OSError):
            return False
        return True

    def _on_drop(self, event):
        # Nur Dateipfade (DND_FILES), kein gezogener Text
        self.handle_dropped_paths(self.tk.splitlist(event.data))
        return event.action

    def handle_dropped_paths(self, raw_paths) -> None:
        """Eine Textdatei -> Vorschau; Ordner, Archiv oder große Datei -> Reiter
        \"Dateien & Ordner\". Es gelten dieselben Prüfungen wie bei \"Datei öffnen\"."""
        paths = [Path(p) for p in raw_paths if p]
        existing = [p for p in paths if p.exists()]
        if not existing:
            self._toast(t("gui.drop.not_found"), error=True)
            return
        if len(existing) > 1:
            dialogs.show_info(t("gui.drop.title"), t("gui.drop.multiple"), parent=self)
            return
        path = existing[0]
        if path.is_dir():
            self.tabs.set(self.TAB_FILES)
            self.input_var.set(str(path))
            self._toast(t("gui.drop.folder_taken", button=t("gui.files.start")))
            return
        if self.tabs.get() == self.TAB_FILES:
            self.input_var.set(str(path))
            self._toast(t("gui.drop.file_taken", button=t("gui.files.start")))
            return
        self.tabs.set(self.TAB_TEXT)
        self.open_file(path)

    def open_file(self, path: Path | None = None) -> None:
        if path is None:
            path = filedialog.askopenfilename(title=t("gui.open.title"), parent=self)
        if not path:
            return
        path = Path(path)
        try:
            size = path.stat().st_size
        except OSError as exc:
            dialogs.show_error(t("gui.open.title"), t("gui.open.unreadable", reason=safe_reason(exc)), parent=self)
            return
        size_mb = size / 1024 / 1024
        if size_mb > self.settings.max_file_size_mb and not dialogs.ask_yes_no(
                t("gui.open.large_title"), t("gui.open.large_msg", size=f"{size_mb:.0f}",
                                             limit=f"{self.settings.max_file_size_mb:g}"), parent=self):
            return
        # Archive und Office-Dokumente haben keine Textvorschau: wie ein Ordner im
        # Reiter "Dateien & Ordner" bereinigen
        is_archive = self.settings.process_archives and archive_kind(path.name)
        is_office = self.settings.process_office and office_kind(path.name)
        is_pdf_file = self.settings.process_pdf and is_pdf(path.name)
        if is_archive or is_office or is_pdf_file:
            what = (t("gui.open.what_archive") if is_archive else
                    t("gui.open.what_office") if is_office else t("gui.open.what_pdf"))
            if dialogs.ask_yes_no(t("gui.open.sanitize_title"), t("gui.open.sanitize_ask", what=what), parent=self):
                self.tabs.set(self.TAB_FILES)
                self.input_var.set(str(path))
                self.start_run()
            return
        # Große Dateien: ohne Vorschau direkt in den Ausgabeordner
        if size > self.settings.max_preview_chars * 2:
            if dialogs.ask_yes_no(t("gui.open.large_title"), t("gui.open.too_big"), parent=self):
                self.tabs.set(self.TAB_FILES)
                self.input_var.set(str(path))
                self.start_run(confirmed_large=True)
            return
        try:
            loaded = load_text_file(path)
        except RunError as exc:
            dialogs.show_error(t("gui.open.title"), str(exc), parent=self)
            return
        except Exception as exc:  # noqa: BLE001 - Meldung ohne Inhalt
            dialogs.show_error(t("gui.open.title"), t("gui.open.unreadable", reason=safe_reason(exc)), parent=self)
            return
        self.excluded.clear()
        self.excluded_keys.clear()
        self._set_original(loaded.text, (path, loaded))

    def save_loaded_file(self) -> None:
        if not self.loaded_file:
            return
        self.run_preview(sync=True)
        path, loaded = self.loaded_file
        name = None
        if self.settings.sanitize_filenames and self._text_sanitizer is not None:
            name = sanitize_path_part(self._text_sanitizer, path.name, self.excluded_keys)
        try:
            dest = save_sanitized_text(path, self.result.text, loaded, self.settings, name=name)
        except RunError as exc:
            dialogs.show_error(t("gui.save.title"), str(exc), parent=self)
            return
        except Exception as exc:  # noqa: BLE001
            dialogs.show_error(t("gui.save.title"), t("gui.save.failed", reason=safe_reason(exc)), parent=self)
            return
        dialogs.show_info(t("gui.save.done_title"), t("gui.save.done", dest=dest), parent=self)

    def choose_folder_from_text_tab(self) -> None:
        self.tabs.set(self.TAB_FILES)
        self.choose_input_folder()

    # ------------------------------------------------------------------
    # Tab: Dateien & Ordner
    # ------------------------------------------------------------------
    def _build_files_tab(self, tab) -> None:
        tab.grid_columnconfigure(1, weight=1)
        tab.grid_rowconfigure(6, weight=1)
        ctk.CTkLabel(tab, text=t("gui.files.intro"),
                     anchor="w", justify="left", wraplength=1200).grid(row=0, column=0, columnspan=4, sticky="w", pady=(4, 10))
        self.input_var = tk.StringVar()
        self.output_var = tk.StringVar(value=self.settings.output_dir)
        ctk.CTkLabel(tab, text=t("gui.files.input")).grid(row=1, column=0, sticky="w", padx=(0, 8))
        ctk.CTkEntry(tab, textvariable=self.input_var).grid(row=1, column=1, sticky="ew")
        ctk.CTkButton(tab, text=t("gui.text.open_file"), width=130, command=self.choose_input_file).grid(row=1, column=2, padx=6)
        ctk.CTkButton(tab, text=t("gui.text.choose_folder"), width=130, command=self.choose_input_folder).grid(row=1, column=3)
        ctk.CTkLabel(tab, text=t("gui.files.output")).grid(row=2, column=0, sticky="w", padx=(0, 8), pady=6)
        ctk.CTkEntry(tab, textvariable=self.output_var,
                     placeholder_text=t("gui.files.output_placeholder")).grid(row=2, column=1, sticky="ew")
        ctk.CTkButton(tab, text=t("gui.files.choose"), width=130, command=self.choose_output_folder).grid(row=2, column=2, padx=6)
        self.clean_var = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(tab, text=t("gui.files.clean"), variable=self.clean_var).grid(row=2, column=3, sticky="w")

        run_bar = ctk.CTkFrame(tab, fg_color="transparent")
        run_bar.grid(row=3, column=0, columnspan=4, sticky="ew", pady=8)
        self.start_btn = ctk.CTkButton(run_bar, text=t("gui.files.start"), height=40, width=220,
                                       font=ctk.CTkFont(size=15, weight="bold"), command=self.start_run)
        self.start_btn.pack(side="left")
        self.cancel_btn = ctk.CTkButton(run_bar, text=t("gui.files.cancel"), width=120, state="disabled",
                                        fg_color="#a93226", hover_color="#922b21", command=self._cancel.set)
        self.cancel_btn.pack(side="left", padx=8)
        self.open_out_btn = ctk.CTkButton(run_bar, text=t("gui.files.open_output"), width=190, state="disabled",
                                          command=self.open_output_folder)
        self.open_out_btn.pack(side="left", padx=8)
        self.filenames_var = tk.BooleanVar(value=self.settings.sanitize_filenames)
        ctk.CTkCheckBox(run_bar, text=t("gui.files.filenames"), variable=self.filenames_var,
                        command=self._filenames_changed).pack(side="left", padx=8)
        self.archives_var = tk.BooleanVar(value=self.settings.process_archives)
        ctk.CTkCheckBox(run_bar, text=t("gui.files.archives"), variable=self.archives_var,
                        command=self._archives_changed).pack(side="left", padx=8)
        self.progress = ctk.CTkProgressBar(tab)
        self.progress.set(0)
        self.progress.grid(row=4, column=0, columnspan=4, sticky="ew")
        self.progress_label = ctk.CTkLabel(tab, text="", anchor="w", text_color="gray")
        self.progress_label.grid(row=5, column=0, columnspan=4, sticky="w")

        panes = ctk.CTkFrame(tab, fg_color="transparent")
        panes.grid(row=6, column=0, columnspan=4, sticky="nsew", pady=(6, 0))
        panes.grid_columnconfigure((0, 1), weight=1)
        panes.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(panes, text=t("gui.files.report_title"), font=ctk.CTkFont(weight="bold")).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(panes, text=t("gui.files.samples_title"), font=ctk.CTkFont(weight="bold")).grid(row=0, column=1, sticky="w")
        self.report_box = HighlightTextbox(panes, readonly=True)
        self.report_box.grid(row=1, column=0, sticky="nsew", padx=(0, 4))
        self.samples_box = HighlightTextbox(panes, readonly=True)
        self.samples_box.grid(row=1, column=1, sticky="nsew", padx=(4, 0))
        self._last_output: Path | None = None

    def _filenames_changed(self) -> None:
        self.settings.sanitize_filenames = bool(self.filenames_var.get())
        self._persist_settings()

    def _archives_changed(self) -> None:
        self.settings.process_archives = bool(self.archives_var.get())
        self._persist_settings()

    def choose_input_file(self) -> None:
        path = filedialog.askopenfilename(title=t("gui.files.pick_file"), parent=self)
        if path:
            self.input_var.set(path)

    def choose_input_folder(self) -> None:
        path = filedialog.askdirectory(title=t("gui.files.pick_folder"), parent=self)
        if path:
            self.input_var.set(path)

    def choose_output_folder(self) -> None:
        path = filedialog.askdirectory(title=t("gui.files.pick_output"), parent=self)
        if path:
            self.output_var.set(path)

    def start_run(self, confirmed_large: bool = False) -> None:
        if self._worker and self._worker.is_alive():
            return
        src = self.input_var.get().strip()
        if not src or not Path(src).exists():
            dialogs.show_error(t("gui.run.title"), t("gui.run.need_input"), parent=self)
            return
        self._cancel.clear()
        self.start_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        self.open_out_btn.configure(state="disabled")
        self.progress.set(0)
        self.report_box.set_text("")
        self.samples_box.set_text("")
        output = self.output_var.get().strip() or None
        clean = self.clean_var.get()
        sanitizer = self._new_sanitizer()
        self._run_sanitizer = sanitizer

        def confirm_large(rel: str, size_mb: float) -> bool:
            if confirmed_large:
                return True
            return self._ask_from_worker(t("gui.open.large_title"), t("gui.run.large_msg", rel=rel, size=f"{size_mb:.0f}",
                                                                      limit=f"{self.settings.max_file_size_mb:g}"))

        def progress(done: int, total: int, rel: str) -> None:
            self._queue.put(("progress", done, total, rel))

        def work() -> None:
            try:
                report, out_root = FileRun(sanitizer, confirm_large=confirm_large, progress=progress,
                                           cancel=self._cancel).run(src, output_dir=output, clean_output=clean)
                self._queue.put(("done", report, out_root))
            except RunError as exc:
                self._queue.put(("error", str(exc)))
            except Exception as exc:  # noqa: BLE001 - Meldung ohne Inhalt
                self._queue.put(("error", t("gui.run.failed", reason=safe_reason(exc))))

        self._worker = threading.Thread(target=work, daemon=True)
        self._worker.start()

    def _ask_from_worker(self, title: str, question: str) -> bool:
        """Rückfrage aus dem Hintergrund-Thread im GUI-Thread stellen."""
        answer = {"value": False}
        done = threading.Event()
        self._queue.put(("ask", title, question, answer, done))
        done.wait()
        return answer["value"]

    def _poll_queue(self) -> None:
        try:
            while True:
                msg = self._queue.get_nowait()
                kind = msg[0]
                if kind == "progress":
                    _, done, total, rel = msg
                    self.progress.set(done / total if total else 1)
                    phase = t("gui.run.phase_analyze") if done < total / 2 else t("gui.run.phase_write")
                    self.progress_label.configure(text=t("gui.run.progress", phase=phase, rel=rel) if rel
                                                  else t("gui.run.progress_done"))
                elif kind == "ask":
                    _, title, question, answer, event = msg
                    answer["value"] = dialogs.ask_yes_no(title, question, parent=self)
                    event.set()
                elif kind == "done":
                    _, report, out_root = msg
                    self._run_finished()
                    self._last_output = out_root
                    self.open_out_btn.configure(state="normal")
                    self.report_box.set_text(report.to_text() + "\n" + t("gui.run.output_dir", path=out_root) + "\n")
                    self.samples_box.set_text("\n".join(report.samples) or t("gui.run.no_replacements"))
                    self.progress.set(1)
                    self.progress_label.configure(text=t("gui.run.aborted") if report.aborted else t("gui.run.finished"))
                elif kind == "preview":
                    _, gen, text, sanitizer, result = msg
                    if gen == self._preview_gen:   # sonst veraltet (inzwischen weitergetippt)
                        self._preview_pending = False
                        self.config(cursor="")
                        self._apply_preview(text, sanitizer, result)
                elif kind == "preview_error":
                    if msg[1] == self._preview_gen:
                        self._preview_pending = False
                        self.config(cursor="")
                        self.summary_label.configure(text=t("gui.text.preview_failed", reason=msg[2]))
                elif kind == "error":
                    self._run_finished()
                    self.progress_label.configure(text=t("gui.run.error"))
                    dialogs.show_error(t("gui.run.title"), msg[1], parent=self)
        except queue.Empty:
            pass
        self.after(100, self._poll_queue)

    def _run_finished(self) -> None:
        self.start_btn.configure(state="normal")
        self.cancel_btn.configure(state="disabled")

    def open_output_folder(self) -> None:
        if not self._last_output:
            return
        path = str(self._last_output)
        try:
            if sys.platform.startswith("win"):
                os.startfile(path)  # type: ignore[attr-defined]
            else:
                import subprocess

                subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", path])
        except OSError as exc:
            dialogs.show_error(t("gui.run.open_failed_title"), t("gui.run.open_failed", name=type(exc).__name__),
                               parent=self)

    # ------------------------------------------------------------------
    # Tab: Antwort zurückübersetzen
    # ------------------------------------------------------------------
    def _build_restore_tab(self, tab) -> None:
        tab.grid_columnconfigure((0, 1), weight=1)
        tab.grid_rowconfigure(2, weight=1)
        ctk.CTkLabel(tab, text=t("gui.restore.intro"),
                     anchor="w", justify="left", wraplength=1200).grid(row=0, column=0, columnspan=2, sticky="w",
                                                                       pady=(4, 6))
        bar = ctk.CTkFrame(tab, fg_color="transparent")
        bar.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 4))
        ctk.CTkLabel(bar, text=t("gui.restore.placeholders_from")).pack(side="left")
        self.restore_source = tk.StringVar(value=self.RESTORE_SOURCES[0])
        ctk.CTkSegmentedButton(bar, values=list(self.RESTORE_SOURCES), variable=self.restore_source,
                               command=lambda _v: self.run_restore()).pack(side="left", padx=8)
        ctk.CTkButton(bar, text=t("gui.text.paste"), width=210,
                      command=self.paste_restore_clipboard).pack(side="left", padx=6)
        self.restore_info = ctk.CTkLabel(bar, text="", text_color="gray")
        self.restore_info.pack(side="left", padx=10)
        self.restore_in = HighlightTextbox(tab, wrap="word")
        self.restore_in.grid(row=2, column=0, sticky="nsew", padx=(0, 4))
        self.restore_in.bind("<KeyRelease>", lambda _e: self._schedule_restore())
        self.restore_in.bind("<<Paste>>", lambda _e: self.after(50, self.run_restore))
        self.restore_out = HighlightTextbox(tab, readonly=True, wrap="word")
        self.restore_out.grid(row=2, column=1, sticky="nsew", padx=(4, 0))
        ctk.CTkButton(tab, text=t("gui.restore.copy"), height=40,
                      font=ctk.CTkFont(size=15, weight="bold"), command=self.copy_restored
                      ).grid(row=3, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ctk.CTkLabel(tab, text=t("gui.restore.warning"),
                     text_color="#e67e22", anchor="w").grid(row=4, column=0, columnspan=2, sticky="w")
        self._restore_job = None

    def _schedule_restore(self) -> None:
        if self._restore_job is not None:
            self.after_cancel(self._restore_job)
        self._restore_job = self.after(300, self.run_restore)

    def _restore_sanitizer(self) -> Sanitizer | None:
        if self.restore_source.get() == self.RESTORE_SOURCES[1]:
            return self._run_sanitizer
        return self._text_sanitizer

    def run_restore(self) -> None:
        self._restore_job = None
        text = self.restore_in.get_text()
        sanitizer = self._restore_sanitizer()
        if sanitizer is None or not len(sanitizer.mapping):
            self.restore_out.set_text(text)
            if self.restore_source.get() == self.RESTORE_SOURCES[0]:
                hint = t("gui.restore.hint_text", tab=self.TAB_TEXT)
            else:
                hint = t("gui.restore.hint_run")
            self.restore_info.configure(text=hint, text_color="#e67e22")
            return
        result = sanitizer.mapping.restore(text)
        self.restore_out.set_text(result.text)
        self.restore_out.highlight(result.spans)
        info = t("gui.restore.restored", n=len(result.spans))
        if result.unknown:
            info += t("gui.restore.unknown", names=", ".join(result.unknown[:5])) + (" …" if len(result.unknown) > 5 else "")
        self.restore_info.configure(text=info, text_color="#e67e22" if result.unknown else "gray")

    def paste_restore_clipboard(self) -> None:
        try:
            text = self.clipboard_get()
        except tk.TclError:
            self._toast(t("gui.toast.clipboard_empty"), error=True)
            return
        self.restore_in.set_text(text.replace("\r\n", "\n"))
        self.run_restore()

    def copy_restored(self) -> None:
        self.run_restore()
        self.clipboard_clear()
        self.clipboard_append(self.restore_out.get_text())

    # ------------------------------------------------------------------
    # Tab: Regeln
    # ------------------------------------------------------------------
    def _build_rules_tab(self, tab) -> None:
        self.rule_editor = RuleEditor(tab, self.user_rules, on_save=self._save_user_rules,
                                      get_settings=lambda: self.settings,
                                      apply_settings=self._apply_profile_settings, fg_color="transparent")
        self.rule_editor.pack(fill="both", expand=True)

    # ------------------------------------------------------------------
    # Tab: Einstellungen
    # ------------------------------------------------------------------
    def _build_settings_tab(self, tab) -> None:
        scroll = ctk.CTkScrollableFrame(tab, fg_color="transparent")
        scroll.pack(fill="both", expand=True)
        scroll.grid_columnconfigure(1, weight=1)
        self.setting_vars: dict[str, tk.StringVar] = {}
        fields = [(key, t(f"gui.settings.f.{key}")) for key in (
            "output_dir", "output_encoding", "max_file_size_mb", "max_archive_mb", "workers", "pdf_timeout_s",
            "pdf_max_memory_mb", "max_files_per_run", "max_preview_chars", "chunk_size", "chunk_overlap",
            "placeholder_style", "exclude_patterns")]
        row = 0
        ctk.CTkLabel(scroll, text=t("gui.settings.general"), font=ctk.CTkFont(size=15, weight="bold")).grid(row=row, column=0, sticky="w", pady=(4, 6))
        row += 1
        # Sprache: wirkt erst nach einem Neustart (siehe save_settings_form)
        self._language_labels = {"auto": t("gui.settings.language_auto"), "de": t("gui.settings.language_de"),
                                 "en": t("gui.settings.language_en")}
        self.language_var = tk.StringVar(value=self._language_labels[self.settings.language])
        ctk.CTkLabel(scroll, text=t("gui.settings.language"), anchor="w").grid(row=row, column=0, sticky="w", padx=(0, 10), pady=3)
        lang_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        lang_frame.grid(row=row, column=1, sticky="w", pady=3)
        ctk.CTkOptionMenu(lang_frame, variable=self.language_var, values=list(self._language_labels.values()),
                          width=160).pack(side="left")
        ctk.CTkLabel(lang_frame, text=t("gui.settings.language_hint"), text_color="gray").pack(side="left", padx=10)
        # Gilt eine andere Sprache als die aus den Einstellungen (--lang / Umgebungsvariable), kurz darauf hinweisen
        configured = self.settings.language if self.settings.language in ("de", "en") else detect_system_language()
        if current_language() != configured:
            ctk.CTkLabel(lang_frame, text=t("gui.settings.language_override"), text_color="gray").pack(side="left")
        row += 1
        for key, label in fields:
            var = tk.StringVar(value=_form_value(getattr(self.settings, key)))
            self.setting_vars[key] = var
            ctk.CTkLabel(scroll, text=label, anchor="w").grid(row=row, column=0, sticky="w", padx=(0, 10), pady=3)
            ctk.CTkEntry(scroll, textvariable=var, width=420).grid(row=row, column=1, sticky="w", pady=3)
            row += 1

        ctk.CTkLabel(scroll, text=t("gui.settings.documents"), font=ctk.CTkFont(size=15, weight="bold")
                     ).grid(row=row, column=0, sticky="w", pady=(14, 6))
        row += 1
        self.bool_vars: dict[str, tk.BooleanVar] = {}
        for key, label in ((k, t(f"gui.settings.b.{k}")) for k in ("process_office", "office_remove_media",
                                                                    "process_pdf")):
            var = tk.BooleanVar(value=getattr(self.settings, key))
            self.bool_vars[key] = var
            ctk.CTkCheckBox(scroll, text=label, variable=var,
                            command=lambda k=key: self._bool_setting_changed(k)).grid(
                row=row, column=0, columnspan=2, sticky="w", pady=3)
            row += 1

        ctk.CTkLabel(scroll, text=t("gui.settings.mode_thresholds"), font=ctk.CTkFont(size=15, weight="bold")
                     ).grid(row=row, column=0, sticky="w", pady=(14, 6))
        row += 1
        for mode in MODES:
            var = tk.StringVar(value=str(self.settings.mode_thresholds.get(mode)))
            self.setting_vars[f"mode_thresholds.{mode}"] = var
            ctk.CTkLabel(scroll, text=mode_label(mode), anchor="w").grid(row=row, column=0, sticky="w", pady=3)
            ctk.CTkEntry(scroll, textvariable=var, width=120).grid(row=row, column=1, sticky="w", pady=3)
            row += 1

        ctk.CTkLabel(scroll, text=t("gui.settings.entropy"),
                     font=ctk.CTkFont(size=15, weight="bold")).grid(row=row, column=0, sticky="w", pady=(14, 6))
        row += 1
        for mode in MODES:
            frame = ctk.CTkFrame(scroll, fg_color="transparent")
            ctk.CTkLabel(scroll, text=mode_label(mode), anchor="w").grid(row=row, column=0, sticky="w", pady=3)
            frame.grid(row=row, column=1, sticky="w")
            for charset in ("hex", "base64", "mixed"):
                var = tk.StringVar(value=str(self.settings.entropy_thresholds.get(mode, {}).get(charset, "")))
                self.setting_vars[f"entropy_thresholds.{mode}.{charset}"] = var
                ctk.CTkLabel(frame, text=charset).pack(side="left", padx=(0, 4))
                ctk.CTkEntry(frame, textvariable=var, width=70).pack(side="left", padx=(0, 12))
            var = tk.StringVar(value=str(self.settings.entropy_min_length.get(mode, "")))
            self.setting_vars[f"entropy_min_length.{mode}"] = var
            ctk.CTkLabel(frame, text=t("gui.settings.min_length")).pack(side="left", padx=(0, 4))
            ctk.CTkEntry(frame, textvariable=var, width=70).pack(side="left")
            row += 1

        btns = ctk.CTkFrame(scroll, fg_color="transparent")
        btns.grid(row=row, column=0, columnspan=2, sticky="w", pady=16)
        ctk.CTkButton(btns, text=t("gui.settings.save"), command=self.save_settings_form).pack(side="left")
        ctk.CTkButton(btns, text=t("gui.settings.defaults"), fg_color="gray40", hover_color="gray30",
                      command=self.reset_settings_form).pack(side="left", padx=8)
        row += 1
        ctk.CTkLabel(scroll, text=t("gui.settings.config_info", path=config.config_dir()),
                     anchor="w", justify="left", text_color="gray").grid(row=row, column=0, columnspan=2, sticky="w")

    def _form_to_dict(self) -> dict:
        data = self.settings.to_dict()
        data["language"] = self._selected_language()
        for key, var in self.setting_vars.items():
            raw = var.get().strip()
            parts = key.split(".")
            if parts[0] in ("output_dir", "output_encoding", "placeholder_style"):
                data[parts[0]] = raw
                continue
            if parts[0] == "exclude_patterns":
                data[parts[0]] = [x.strip() for x in raw.split(",") if x.strip()]
                continue
            try:
                value = float(raw) if "." in raw or parts[0] in ("entropy_thresholds", "mode_thresholds",
                                                                 "max_file_size_mb", "max_archive_mb") else int(raw)
            except ValueError:
                raise ValueError(key) from None
            if len(parts) == 1:
                data[key] = value
            elif len(parts) == 2:
                data[parts[0]][parts[1]] = value
            else:
                data[parts[0]].setdefault(parts[1], {})[parts[2]] = value
        return data

    def _selected_language(self) -> str:
        """Auswahl im Sprachfeld als Wert für Settings.language ('auto', 'de', 'en')."""
        shown = self.language_var.get()
        return next((code for code, label in self._language_labels.items() if label == shown), "auto")

    def save_settings_form(self) -> None:
        try:
            data = self._form_to_dict()
        except ValueError as exc:
            dialogs.show_error(self.TAB_SETTINGS, t("gui.settings.invalid_number", field=exc), parent=self)
            return
        new = Settings.from_dict(data)
        changed = [k for k in ("output_encoding", "placeholder_style") if getattr(new, k) != data[k]]
        language_changed = new.language != self.settings.language
        self.settings = new
        saved = self._persist_settings()
        self.output_var.set(new.output_dir)
        self._sync_settings_form()
        if changed:
            dialogs.show_warning(self.TAB_SETTINGS, t("gui.settings.reset_invalid", fields=", ".join(changed)),
                                 parent=self)
        self._toast(t("gui.settings.saved"))
        self.schedule_preview(immediate=True)
        if saved and language_changed and dialogs.ask_yes_no(t("gui.restart.title"), t("gui.restart.message"), parent=self):
            try:
                restart_app(self)
            except OSError as exc:
                dialogs.show_error(t("gui.restart.title"), t("gui.restart.failed", name=type(exc).__name__),
                                   parent=self)

    def reset_settings_form(self) -> None:
        defaults = Settings()
        defaults.mode = self.settings.mode
        defaults.enabled_categories = self.settings.enabled_categories
        defaults.language = self.settings.language   # die Sprache ändert nur ihr eigenes Feld (mit Neustart)
        self.settings = defaults
        self._persist_settings()
        self._sync_settings_form()
        self.schedule_preview(immediate=True)

    def _bool_setting_changed(self, key: str) -> None:
        setattr(self.settings, key, bool(self.bool_vars[key].get()))
        self._persist_settings()

    def _sync_settings_form(self) -> None:
        for key, var in self.bool_vars.items():
            var.set(getattr(self.settings, key))
        self.filenames_var.set(self.settings.sanitize_filenames)
        self.archives_var.set(self.settings.process_archives)
        self.language_var.set(self._language_labels.get(self.settings.language, self._language_labels["auto"]))
        data = self.settings.to_dict()
        for key, var in self.setting_vars.items():
            value = data
            for part in key.split("."):
                value = value.get(part, "") if isinstance(value, dict) else ""
            var.set(_form_value(value))

    # ------------------------------------------------------------------
    def _on_close(self) -> None:
        self._cancel.set()
        # Mapping und Ergebnis aus dem Speicher entfernen
        self.result = None
        for sanitizer in (self._text_sanitizer, self._run_sanitizer):
            if sanitizer is not None:
                sanitizer.reset()
        self._text_sanitizer = self._run_sanitizer = None
        self._groups.clear()
        self.excluded.clear()
        self.excluded_keys.clear()
        self.destroy()


def _form_value(value) -> str:
    """Wert für ein Eingabefeld der Einstellungen (Listen kommagetrennt)."""
    return ", ".join(value) if isinstance(value, list) else str(value)


def _placeholder_number(placeholder: str) -> int:
    digits = "".join(ch for ch in placeholder if ch.isdigit())
    return int(digits) if digits else 0


def run(lang: str | None = None) -> int:
    app = App(lang)
    app.mainloop()
    return 0

