"""Regel-Editor (einfache Form): eigene Regex-Regeln mit Testfeld, Wortlisten
und Allowlist. Speichert nach user_rules.json im Konfigurationsordner, damit
niemand JSON von Hand schreiben muss."""

from __future__ import annotations

import re
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

import customtkinter as ctk

from ..core import profiles
from ..core.models import CATEGORIES
from ..core.rules import AllowEntry, RuleError, UserRules, Wordlist, redos_risk, rule_from_dict
from ..detectors.wordlist_detector import compile_wordlist
from . import dialogs
from .widgets import HighlightTextbox, style_treeview

CATEGORY_IDS = list(CATEGORIES)
REGEX_PREFIX = "re:"
REDOS_WARNING = ("Das Muster enthält verschachtelte Wiederholungen wie (a+)+ oder (\\w+\\s?)+. Solche Muster "
                 "können bei manchen Texten extrem langsam werden und das Programm einfrieren. Besser die innere "
                 "oder äußere Wiederholung entfernen oder einen festen Trenner einbauen.")


class RuleEditor(ctk.CTkFrame):
    def __init__(self, master, user_rules: UserRules, on_save, get_settings=None, apply_settings=None,
                 **kwargs) -> None:
        super().__init__(master, **kwargs)
        self.user_rules = user_rules
        self.on_save = on_save
        # Für Profile: aktuelle Einstellungen lesen bzw. Modus/Kategorien aus einem Profil übernehmen
        self.get_settings = get_settings
        self.apply_settings = apply_settings
        self._current: int | None = None  # Index der bearbeiteten Regel
        self._test_job = None

        self.grid_columnconfigure(0, weight=3)
        self.grid_columnconfigure(1, weight=2)
        self.grid_rowconfigure(0, weight=1)

        left = ctk.CTkFrame(self)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        right = ctk.CTkFrame(self)
        right.grid(row=0, column=1, sticky="nsew")
        self._build_rules(left)
        self._build_lists(right)

        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        ctk.CTkButton(bottom, text="Alle Regeln speichern", command=self.save, width=220, height=36,
                      font=ctk.CTkFont(size=14, weight="bold")).pack(side="right")
        self._build_profile_bar(bottom)
        self.status = ctk.CTkLabel(bottom, text="", anchor="w")
        self.status.pack(side="left", fill="x", expand=True)

        self._refresh_rule_list()
        self._load_lists()

    # ------------------------------------------------------------------
    # Eigene Regeln
    # ------------------------------------------------------------------
    def _build_rules(self, frame) -> None:
        frame.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(frame, text="Eigene Regeln (reguläre Ausdrücke)", font=ctk.CTkFont(size=15, weight="bold")
                     ).grid(row=0, column=0, columnspan=3, sticky="w", padx=8, pady=(8, 4))

        style_treeview(frame)
        self.rule_tree = ttk.Treeview(frame, columns=("name", "category", "enabled"), show="headings", height=3,
                                      selectmode="browse")
        for key, label, width in (("name", "Name", 220), ("category", "Kategorie", 120), ("enabled", "Aktiv", 60)):
            self.rule_tree.heading(key, text=label)
            self.rule_tree.column(key, width=width, anchor="w")
        self.rule_tree.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=8)
        self.rule_tree.bind("<<TreeviewSelect>>", self._rule_selected)
        btns = ctk.CTkFrame(frame, fg_color="transparent")
        btns.grid(row=1, column=2, sticky="n", padx=8)
        ctk.CTkButton(btns, text="Neue Regel", width=110, command=self._new_rule).pack(pady=2)
        ctk.CTkButton(btns, text="Löschen", width=110, fg_color="#a93226", hover_color="#922b21",
                      command=self._delete_rule).pack(pady=2)

        form = ctk.CTkFrame(frame, fg_color="transparent")
        form.grid(row=2, column=0, columnspan=3, sticky="ew", padx=8, pady=6)
        form.grid_columnconfigure(1, weight=1)
        self.var_name = tk.StringVar()
        self.var_desc = tk.StringVar()
        self.var_pattern = tk.StringVar()
        self.var_category = tk.StringVar(value="CUSTOM")
        self.var_conf = tk.DoubleVar(value=0.9)
        self.var_icase = tk.BooleanVar(value=True)
        self.var_enabled = tk.BooleanVar(value=True)

        def row(r, label, widget):
            ctk.CTkLabel(form, text=label, anchor="w").grid(row=r, column=0, sticky="w", pady=2, padx=(0, 6))
            widget.grid(row=r, column=1, sticky="ew", pady=2)

        row(0, "Name", ctk.CTkEntry(form, textvariable=self.var_name))
        row(1, "Beschreibung", ctk.CTkEntry(form, textvariable=self.var_desc,
                                            placeholder_text="Wofür ist die Regel?"))
        pattern_entry = ctk.CTkEntry(form, textvariable=self.var_pattern, font=ctk.CTkFont(family="Consolas", size=13))
        row(2, "Muster (Regex)", pattern_entry)
        ctk.CTkLabel(form, text="Tipp: Mit (?P<value>...) wird nur dieser Teil ersetzt, z. B.  kunde=(?P<value>\\w+)",
                     text_color="gray", anchor="w").grid(row=3, column=1, sticky="w")
        row(4, "Kategorie", ctk.CTkOptionMenu(form, variable=self.var_category, values=CATEGORY_IDS))
        conf_frame = ctk.CTkFrame(form, fg_color="transparent")
        self.conf_label = ctk.CTkLabel(conf_frame, text="0.90", width=40)
        ctk.CTkSlider(conf_frame, from_=0.05, to=1.0, number_of_steps=19, variable=self.var_conf,
                      command=lambda v: self.conf_label.configure(text=f"{float(v):.2f}")).pack(
            side="left", fill="x", expand=True)
        self.conf_label.pack(side="left", padx=6)
        row(5, "Konfidenz", conf_frame)
        opts = ctk.CTkFrame(form, fg_color="transparent")
        ctk.CTkCheckBox(opts, text="Groß-/Kleinschreibung ignorieren", variable=self.var_icase,
                        command=self._schedule_test).pack(side="left")
        ctk.CTkCheckBox(opts, text="Aktiv", variable=self.var_enabled).pack(side="left", padx=12)
        row(6, "Optionen", opts)
        ctk.CTkButton(form, text="Regel übernehmen", command=self._apply_rule).grid(row=7, column=1, sticky="e", pady=4)

        ctk.CTkLabel(frame, text="Testfeld: Beispieltext eintippen, Treffer werden sofort markiert",
                     anchor="w").grid(row=3, column=0, columnspan=3, sticky="w", padx=8)
        self.test_box = HighlightTextbox(frame, height=90, wrap="word")
        self.test_box.grid(row=4, column=0, columnspan=3, sticky="nsew", padx=8, pady=(2, 4))
        self.test_result = ctk.CTkLabel(frame, text="", anchor="w")
        self.test_result.grid(row=5, column=0, columnspan=3, sticky="w", padx=8, pady=(0, 8))
        frame.grid_rowconfigure(4, weight=1)
        self.var_pattern.trace_add("write", lambda *_: self._schedule_test())
        self.test_box.bind("<KeyRelease>", lambda _e: self._schedule_test())

    def _schedule_test(self) -> None:
        if self._test_job is not None:
            self.after_cancel(self._test_job)
        self._test_job = self.after(250, self._run_test)

    def _run_test(self) -> None:
        self._test_job = None
        self.test_box.tag_remove("testhit", "1.0", "end")
        pattern = self.var_pattern.get()
        if not pattern:
            self.test_result.configure(text="", text_color=("gray10", "gray90"))
            return
        try:
            regex = re.compile(pattern, re.IGNORECASE if self.var_icase.get() else 0)
        except re.error as exc:
            self.test_result.configure(text=f"Ungültiges Muster: {exc.msg} (Position {exc.pos})", text_color="#e74c3c")
            return
        if redos_risk(pattern):
            # Nicht live testen: ein solches Muster könnte die Oberfläche einfrieren
            self.test_result.configure(text="⚠ Möglicherweise sehr langsames Muster (verschachtelte Wiederholung) "
                                            "– wird nicht live getestet.", text_color="#e74c3c")
            return
        text = self.test_box.get_text()
        count = 0
        for m in regex.finditer(text):
            start, end = m.span("value") if "value" in regex.groupindex and m.group("value") is not None else m.span()
            if end > start:
                self.test_box.tag_add("testhit", self.test_box.index_of(start), self.test_box.index_of(end))
                count += 1
            if count >= 5000:
                break
        warn = "  ⚠ Muster passt auf leeren Text" if regex.match("") else ""
        self.test_result.configure(text=f"{count} Treffer{warn}", text_color="#e67e22" if warn else ("gray10", "gray90"))

    def _refresh_rule_list(self) -> None:
        self.rule_tree.delete(*self.rule_tree.get_children())
        for i, rule in enumerate(self.user_rules.rules):
            self.rule_tree.insert("", "end", iid=str(i), values=(rule.name, rule.category, "ja" if rule.enabled else "nein"))

    def _rule_selected(self, _event=None) -> None:
        sel = self.rule_tree.selection()
        if not sel:
            return
        self._current = int(sel[0])
        rule = self.user_rules.rules[self._current]
        self.var_name.set(rule.name)
        self.var_desc.set(rule.description)
        self.var_pattern.set(rule.pattern)
        self.var_category.set(rule.category)
        self.var_conf.set(rule.confidence)
        self.conf_label.configure(text=f"{rule.confidence:.2f}")
        self.var_icase.set("IGNORECASE" in rule.flags)
        self.var_enabled.set(rule.enabled)

    def _new_rule(self) -> None:
        self._current = None
        self.rule_tree.selection_remove(*self.rule_tree.selection())
        self.var_name.set("")
        self.var_desc.set("")
        self.var_pattern.set("")
        self.var_category.set("CUSTOM")
        self.var_conf.set(0.9)
        self.conf_label.configure(text="0.90")
        self.var_icase.set(True)
        self.var_enabled.set(True)

    def _apply_rule(self) -> None:
        name = self.var_name.get().strip() or "Eigene Regel"
        existing_ids = {r.id for i, r in enumerate(self.user_rules.rules) if i != self._current}
        if self._current is not None:
            rule_id = self.user_rules.rules[self._current].id
        else:
            base = "user_" + (re.sub(r"\W+", "_", name.lower()).strip("_") or "regel")
            rule_id, n = base, 2
            while rule_id in existing_ids:
                rule_id, n = f"{base}_{n}", n + 1
        try:
            rule = rule_from_dict({
                "id": rule_id, "name": name, "description": self.var_desc.get().strip(),
                "category": self.var_category.get(), "pattern": self.var_pattern.get(),
                "confidence": round(float(self.var_conf.get()), 2),
                "flags": ["IGNORECASE"] if self.var_icase.get() else [], "enabled": self.var_enabled.get(),
            })
        except RuleError as exc:
            dialogs.show_error("Regel ungültig", str(exc), parent=self)
            return
        if redos_risk(rule.pattern) and not dialogs.ask_yes_no(
                "Langsames Muster", REDOS_WARNING + "\n\nTrotzdem übernehmen?", parent=self):
            return
        if self._current is None:
            self.user_rules.rules.append(rule)
            self._current = len(self.user_rules.rules) - 1
        else:
            self.user_rules.rules[self._current] = rule
        self._refresh_rule_list()
        self.rule_tree.selection_set(str(self._current))
        self.status.configure(text="Regel übernommen – zum Aktivieren 'Alle Regeln speichern' klicken.")

    def _delete_rule(self) -> None:
        if self._current is None:
            return
        rule = self.user_rules.rules[self._current]
        if not dialogs.ask_yes_no("Regel löschen", f"Regel '{rule.name}' löschen?", parent=self):
            return
        del self.user_rules.rules[self._current]
        self._current = None
        self._refresh_rule_list()
        self._new_rule()

    # ------------------------------------------------------------------
    # Wortlisten und Allowlist
    # ------------------------------------------------------------------
    def _build_lists(self, frame) -> None:
        frame.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(frame, text="Eigene Wortlisten", font=ctk.CTkFont(size=15, weight="bold")
                     ).grid(row=0, column=0, sticky="w", padx=8, pady=(8, 0))
        ctk.CTkLabel(frame, text="Ein Eintrag pro Zeile: Firmennamen, interne Hosts, Benutzer, Projekte, Personen …",
                     text_color="gray", anchor="w", wraplength=420, justify="left").grid(row=1, column=0, sticky="w", padx=8)
        top = ctk.CTkFrame(frame, fg_color="transparent")
        top.grid(row=2, column=0, sticky="ew", padx=8, pady=4)
        self.var_wl_category = tk.StringVar(value="COMPANY")
        self.var_wl_icase = tk.BooleanVar(value=True)
        ctk.CTkLabel(top, text="Kategorie").pack(side="left")
        ctk.CTkOptionMenu(top, variable=self.var_wl_category, values=CATEGORY_IDS, width=150,
                          command=self._wl_category_changed).pack(side="left", padx=6)
        ctk.CTkCheckBox(top, text="Groß/klein ignorieren", variable=self.var_wl_icase).pack(side="left", padx=6)
        self.wl_box = ctk.CTkTextbox(frame, height=150, font=ctk.CTkFont(family="Consolas", size=12))
        self.wl_box.grid(row=3, column=0, sticky="nsew", padx=8)
        self.wl_box.bind("<FocusOut>", lambda _e: self._store_wordlist())

        ctk.CTkLabel(frame, text="Allowlist (wird nie ersetzt)", font=ctk.CTkFont(size=15, weight="bold")
                     ).grid(row=4, column=0, sticky="w", padx=8, pady=(12, 0))
        ctk.CTkLabel(frame, text=f"Ein Eintrag pro Zeile, exakt (ohne Groß/klein). Mit '{REGEX_PREFIX}' am Anfang als "
                                 "regulärer Ausdruck, z. B.  re:10\\.0\\.0\\.\\d+",
                     text_color="gray", anchor="w", wraplength=420, justify="left").grid(row=5, column=0, sticky="w", padx=8)
        self.allow_box = ctk.CTkTextbox(frame, height=120, font=ctk.CTkFont(family="Consolas", size=12))
        self.allow_box.grid(row=6, column=0, sticky="nsew", padx=8, pady=(2, 8))
        frame.grid_rowconfigure(3, weight=1)
        frame.grid_rowconfigure(6, weight=1)
        self._wl_shown = self.var_wl_category.get()

    def _wordlist_for(self, category: str) -> Wordlist | None:
        for wl in self.user_rules.wordlists:
            if wl.id == f"user_{category.lower()}":
                return wl
        return None

    def _load_lists(self) -> None:
        self._show_wordlist(self.var_wl_category.get())
        lines = [(REGEX_PREFIX + a.value) if a.regex else a.value for a in self.user_rules.allowlist]
        self.allow_box.delete("1.0", "end")
        self.allow_box.insert("1.0", "\n".join(lines))

    def _show_wordlist(self, category: str) -> None:
        self._wl_shown = category
        wl = self._wordlist_for(category)
        self.wl_box.delete("1.0", "end")
        if wl:
            self.wl_box.insert("1.0", "\n".join(wl.words))
            self.var_wl_icase.set(wl.ignore_case)
        else:
            self.var_wl_icase.set(True)

    def _store_wordlist(self) -> None:
        category = self._wl_shown
        words = [w.strip() for w in self.wl_box.get("1.0", "end").splitlines() if w.strip()]
        wl = self._wordlist_for(category)
        if wl is None and not words:
            return
        if wl is None:
            label = CATEGORIES[category].label if category in CATEGORIES else category
            wl = Wordlist(id=f"user_{category.lower()}", name=f"Eigene Liste: {label}", category=category,
                          description="In der GUI gepflegte Wortliste.")
            self.user_rules.wordlists.append(wl)
        wl.words = words
        wl.ignore_case = self.var_wl_icase.get()

    def _wl_category_changed(self, category: str) -> None:
        self._store_wordlist()
        self._show_wordlist(category)

    def _store_allowlist(self) -> bool:
        entries = []
        for line in self.allow_box.get("1.0", "end").splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith(REGEX_PREFIX):
                value = line[len(REGEX_PREFIX):]
                try:
                    re.compile(value)
                except re.error as exc:
                    dialogs.show_error("Allowlist", f"Ungültiger regulärer Ausdruck in der Allowlist ({exc.msg}).",
                                         parent=self)
                    return False
                if redos_risk(value) and not dialogs.ask_yes_no(
                        "Allowlist", REDOS_WARNING + "\n\nTrotzdem speichern?", parent=self):
                    return False
                entries.append(AllowEntry(value=value, regex=True, description="In der GUI gepflegt."))
            else:
                entries.append(AllowEntry(value=line, description="In der GUI gepflegt."))
        self.user_rules.allowlist = entries
        return True

    # ------------------------------------------------------------------
    # Profile
    # ------------------------------------------------------------------
    def _build_profile_bar(self, bar) -> None:
        buttons = [("Laden", self.load_selected_profile), ("Speichern als …", self.save_profile_as),
                   ("Importieren …", self.import_profile_file), ("Exportieren …", self.export_profile)]
        frame = ctk.CTkFrame(bar, fg_color="transparent")
        frame.pack(side="right", padx=(0, 12))
        ctk.CTkLabel(bar, text="Profil:", font=ctk.CTkFont(weight="bold")).pack(side="right", padx=(12, 4))
        self.var_profile = tk.StringVar(value="")
        self.profile_box = ctk.CTkComboBox(frame, variable=self.var_profile, values=profiles.list_profiles() or [""],
                                           width=170, state="readonly")
        self.profile_box.pack(side="left", padx=(0, 6))
        for text, command in buttons:
            ctk.CTkButton(frame, text=text, width=110, fg_color="gray40", hover_color="gray30",
                          command=command).pack(side="left", padx=2)

    def _refresh_profiles(self, select: str = "") -> None:
        names = profiles.list_profiles()
        self.profile_box.configure(values=names or [""])
        if select:
            self.var_profile.set(select)

    def _collect(self) -> bool:
        """Übernimmt offene Eingaben (Wortliste, Allowlist) in self.user_rules."""
        self._store_wordlist()
        return self._store_allowlist()

    def save_profile_as(self) -> None:
        if not self._collect():
            return
        name = ctk.CTkInputDialog(text="Name des Profils (z. B. \"Kunde A\"):", title="Profil speichern").get_input()
        if not name:
            return
        name = name.strip()
        if not profiles.valid_profile_name(name):
            dialogs.show_error("Profil", "Ungültiger Name. Erlaubt sind Buchstaben, Ziffern, Leerzeichen und "
                                           "- _ . (max. 60 Zeichen).", parent=self)
            return
        if name in profiles.list_profiles() and not dialogs.ask_yes_no(
                "Profil", f"Profil \"{name}\" überschreiben?", parent=self):
            return
        settings = self.get_settings() if self.get_settings else None
        try:
            profiles.save_named_profile(name, self.user_rules, settings)
        except (OSError, profiles.ProfileError) as exc:
            dialogs.show_error("Profil", f"Speichern fehlgeschlagen ({type(exc).__name__}).", parent=self)
            return
        self._refresh_profiles(select=name)
        self.status.configure(text=f"Profil gespeichert: {name}")

    def load_selected_profile(self) -> None:
        name = self.var_profile.get().strip()
        if not name:
            dialogs.show_info("Profil", "Noch kein Profil gespeichert oder ausgewählt.", parent=self)
            return
        try:
            profile = profiles.load_named_profile(name)
        except profiles.ProfileError as exc:
            dialogs.show_error("Profil", str(exc), parent=self)
            return
        self._import(profile)

    def import_profile_file(self) -> None:
        path = filedialog.askopenfilename(title="Profil importieren", parent=self,
                                          filetypes=[("Profil (JSON)", "*.json"), ("Alle Dateien", "*.*")])
        if not path:
            return
        try:
            profile = profiles.load_profile(path)
        except profiles.ProfileError as exc:
            dialogs.show_error("Profil importieren", str(exc), parent=self)
            return
        self._import(profile)

    def _import(self, profile, merge: bool | None = None) -> bool:
        """Zeigt, was sich ändert, und übernimmt das Profil. merge=None: nachfragen."""
        if not self._collect():
            return False
        info = profiles.summarize(self.user_rules, profile.rules)
        lines = [f"Profil \"{profile.name}\":",
                 f"  {info['new_rules']} neue und {info['changed_rules']} geänderte Regeln",
                 f"  {info['new_words']} neue Wörter in Wortlisten",
                 f"  {info['new_allow']} neue Allowlist-Einträge"]
        if profile.settings:
            lines.append("  setzt außerdem " + " und ".join(
                {"mode": "den Modus", "enabled_categories": "die Kategorien"}[k] for k in profile.settings))
        if profile.warnings:
            lines += ["", "Hinweise:"] + [f"  - {w}" for w in profile.warnings[:8]]
            if len(profile.warnings) > 8:
                lines.append(f"  … und {len(profile.warnings) - 8} weitere")
        if merge is None:
            answer = dialogs.ask_yes_no_cancel(
                "Profil übernehmen", "\n".join(lines) + "\n\nJa = mit den aktuellen Regeln zusammenführen\n"
                                                        "Nein = aktuelle eigene Regeln ersetzen", parent=self)
            if answer is None:
                return False
            merge = answer
        self.user_rules = profiles.merge(self.user_rules, profile.rules) if merge else profile.rules
        self._current = None
        self._refresh_rule_list()
        self._load_lists()
        if profile.settings and self.apply_settings:
            self.apply_settings(profile.settings)
        ok = self.save()
        if ok:
            self.status.configure(text=f"Profil \"{profile.name}\" übernommen "
                                       f"({'zusammengeführt' if merge else 'ersetzt'}).")
        return ok

    def export_profile(self) -> None:
        if not self._collect():
            return
        path = filedialog.asksaveasfilename(title="Profil exportieren", parent=self, defaultextension=".json",
                                            initialfile="profil.json", filetypes=[("Profil (JSON)", "*.json")])
        if not path:
            return
        with_words = False
        if any(w.words for w in self.user_rules.wordlists):
            with_words = dialogs.ask_yes_no(
                "Wortlisten mitexportieren?",
                "Die Wortlisten enthalten Firmen-, Host- und Personennamen im Klartext.\n\n"
                "Nur mitexportieren, wenn die Datei in vertrauenswürdigen Händen bleibt.\n\nMitexportieren?",
                default="no", parent=self)
        settings = self.get_settings() if self.get_settings else None
        try:
            profiles.export_profile(path, self.user_rules, Path(path).stem, settings, with_words)
        except OSError as exc:
            dialogs.show_error("Profil exportieren", f"Speichern fehlgeschlagen ({type(exc).__name__}).",
                                 parent=self)
            return
        self.status.configure(text=f"Profil exportiert{' (mit Wortlisten)' if with_words else ' (ohne Wortlisten)'}: "
                                   f"{path}")

    def add_allow_entry(self, value: str) -> bool:
        """Übernimmt einen Wert (exakt) in die Allowlist und speichert alle Regeln.
        Rückgabe False, wenn das Speichern scheiterte."""
        lines = [line.strip() for line in self.allow_box.get("1.0", "end").splitlines() if line.strip()]
        if value.casefold() not in (line.casefold() for line in lines):
            lines.append(value)
        self.allow_box.delete("1.0", "end")
        self.allow_box.insert("1.0", "\n".join(lines))
        return self.save()

    # ------------------------------------------------------------------
    def save(self) -> bool:
        self._store_wordlist()
        if not self._store_allowlist():
            return False
        # Leere Wortlisten nicht mitspeichern
        self.user_rules.wordlists = [w for w in self.user_rules.wordlists if w.words]
        for wl in self.user_rules.wordlists:
            compile_wordlist(wl.words, wl.ignore_case)  # prüft, dass alles kompilierbar ist
        try:
            path = self.on_save(self.user_rules)
        except OSError as exc:
            dialogs.show_error("Speichern fehlgeschlagen", f"Regeln konnten nicht gespeichert werden "
                                                              f"({type(exc).__name__}).", parent=self)
            return False
        self.status.configure(text=f"Gespeichert: {path}")
        return True

