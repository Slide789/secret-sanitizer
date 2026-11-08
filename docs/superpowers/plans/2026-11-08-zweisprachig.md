# Zweisprachigkeit (DE/EN) – Umsetzungsplan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Secret Sanitizer unterstützt Deutsch und Englisch vollständig in GUI, CLI, Meldungen, Regeln, Bericht und Doku – in einer EXE, Sprache automatisch erkannt und umschaltbar.

**Architecture:** Ein kleines Modul `secret_sanitizer/i18n.py` lädt flache JSON-Sprachdateien (`locales/de.json`, `locales/en.json`) und stellt `t(key, **werte)` bereit. Alle Texte für Nutzer laufen über `t()`; Kategorien, Modi und mitgelieferte Regeln holen ihre Anzeige-Texte über Schlüssel. Die GUI bekommt eigene Dialoge statt `tkinter.messagebox`.

**Tech Stack:** Python 3.10+, customtkinter, argparse, unittest, PyInstaller (Onefile).

**Spec:** `docs/superpowers/specs/2026-11-08-zweisprachig-design.md`

## Global Constraints

- Keine neuen Abhängigkeiten, keine Netzwerkzugriffe, keine neuen Speicherorte (Konfiguration bleibt `%APPDATA%\secret_sanitizer\config.json`).
- Platzhalter (`[PASSWORD_1]` …), Kategorie-IDs, CLI-Optionsnamen und -Werte (`strict|normal|loose`, Kategorie-IDs), Rückgabewerte, Ordnername `_sanitized` und Endung `.pdf.txt` bleiben sprachunabhängig und unverändert.
- Sprachwahl-Reihenfolge: `--lang de|en` → Umgebungsvariable `SECRET_SANITIZER_LANG` → `config.json` Feld `language` (`"auto"` Standard, `"de"`, `"en"`) → Systemsprache (Deutsch wenn Hauptsprache Deutsch, sonst Englisch).
- Fehlender `language`-Eintrag in alter `config.json` = `"auto"`. Ungültiger Wert = `"auto"`.
- Berichtsname: `secret_sanitizer_bericht.txt` (de) / `secret_sanitizer_report.txt` (en); beide werden als Bericht erkannt.
- Eigene Regeln, Wortlisten und Profilnamen des Nutzers werden nie übersetzt.
- Code-Kommentare und Docstrings bleiben Deutsch.
- Einzige erlaubte Mischung: der Windows-Datei-Dialog (`filedialog`) folgt der Windows-Sprache.
- Version danach: `1.3.0`.
- Commits als Slide789 (lokale git-Identität ist gesetzt), **ohne** Co-Author-Zeile. Gearbeitet wird auf Branch `zweisprachig`; Merge nach `main`, Push und `gh repo edit` erst nach Rückfrage beim Nutzer (Task 7).
- Tests laufen mit `python -m unittest discover -s tests -t .` (Projekt-venv: `.venv-build\Scripts\python.exe`).

## Review Focus

- Sprache wird gewechselt, und ein früherer Ausgabeordner enthält den Bericht der anderen Sprache → Ordner gilt als eigener Ausgabeordner, `--clean` funktioniert, der alte Bericht wird ersetzt (Test in Task 3).
- Ein Sprachtext enthält wörtliche geschweifte Klammern (z. B. das Platzhalterformat `[{CATEGORY}_{N}]` im Einstellungs-Hinweis) → `t()` ohne Werte gibt den Text unverändert zurück; mit Werten muss jeder Text formatierbar sein (Test in Task 1).
- `config.json` mit kaputtem `language`-Wert (`"fr"`, `5`, `null`) → App startet mit `"auto"`, nichts stürzt ab (Test in Task 1).
- Ordnerlauf mit mehreren CPU-Kernen in Englisch → auch die Worker-Prozesse (spawn) liefern englische Meldungen, Bericht ist vollständig englisch (Test in Task 3).
- Systemsprache lässt sich nicht ermitteln (ctypes-Fehler, leere Locale) → Englisch, kein Absturz (Test in Task 1).

---

### Task 0: Branch anlegen

- [ ] **Step 1:** `git switch -c zweisprachig` im Repo `secret_sanitizer_projekt`. Erwartet: `Switched to a new branch 'zweisprachig'`.
- [ ] **Step 2:** Spec und diesen Plan committen: `git add docs && git commit -m "Design und Plan: Deutsch/Englisch"`.

---

### Task 1: Übersetzungsmodul, Sprachwahl, Konfiguration

**Files:**
- Create: `secret_sanitizer/i18n.py`, `secret_sanitizer/locales/de.json`, `secret_sanitizer/locales/en.json`, `tests/test_i18n.py`
- Modify: `secret_sanitizer/config.py` (Feld `language`, `_validate`), `tests/helpers.py`, `tests/gui_smoke.py` (Testsprache), `packaging/secret_sanitizer.spec` (`datas` für beide EXEs um `locales/*.json` ergänzen, wie `RULES`)

**Interfaces:**
- Produces:
  - `LANGUAGES = ("de", "en")`, `LANG_ENV_VAR = "SECRET_SANITIZER_LANG"`
  - `t(key: str, **values) -> str` – ohne `values` Text unverändert, mit `values` `str.format(**values)`. Fehlt der Schlüssel: Englisch, sonst der Schlüssel selbst.
  - `has_key(key: str) -> bool` (aktive Sprache)
  - `set_language(lang: str) -> None` (ungültig → `ValueError`), `current_language() -> str`
  - `detect_system_language() -> str` – Windows: `ctypes.windll.kernel32.GetUserDefaultUILanguage()`, Deutsch wenn `langid & 0x3FF == 0x07`; sonst `locale.getlocale()[0]` beginnt mit `de`; jeder Fehler → `"en"`.
  - `resolve_language(cli: str | None, setting: str) -> str` – Reihenfolge laut Global Constraints, Umgebungsvariable dazwischen.
  - `load_catalog(lang: str) -> dict[str, str]` (für Tests), Sprachdateien über `Path(__file__).parent / "locales"` (funktioniert auch in PyInstaller, wie `rules/`).
  - `Settings.language: str = "auto"`; `_validate` setzt alles außer `"auto" | "de" | "en"` auf `"auto"`.
- In den JSON-Dateien: flach, Schlüssel `bereich.element` (z. B. `gui.text.copy_button`). Sonderabschnitt `"_argparse"` (nur `de.json`, Objekt msgid → Übersetzung) wird in Task 4 befüllt und ist vom Schlüsselvergleich ausgenommen.

- [ ] **Step 1: Tests schreiben** in `tests/test_i18n.py`:
  - `test_catalogs_have_same_keys`: `set(load_catalog("de")) - {"_argparse"} == set(load_catalog("en"))`
  - `test_no_empty_texts`: kein Wert ist `""` oder nur Leerzeichen (beide Sprachen)
  - `test_placeholders_match`: für jeden Schlüssel sind die Feldnamen aus `string.Formatter().parse()` in de und en gleich
  - `test_every_text_formats`: für jeden Schlüssel mit Feldern gelingt `text.format(**{f: "x" for f in felder})` ohne Fehler
  - `test_t_without_values_returns_raw`: Schlüssel `test.braces` = `"[{CATEGORY}_{N}]"` in beiden Dateien; `t("test.braces") == "[{CATEGORY}_{N}]"`
  - `test_t_formats_values` und `test_missing_key_falls_back`: unbekannter Schlüssel → Schlüssel selbst
  - `test_resolve_order`: cli schlägt env schlägt setting schlägt System (System per `unittest.mock.patch("secret_sanitizer.i18n.detect_system_language", return_value="de")`)
  - `test_detect_system_language_error_is_english`: `ctypes`-Aufruf wirft (`patch` auf eine interne Hilfsfunktion `_windows_ui_langid`, die `OSError` wirft) und `locale.getlocale` liefert `(None, None)` → `"en"`
  - `test_settings_language_invalid`: `Settings.from_dict({"language": v}).language == "auto"` für `v in ("fr", 5, None, "")`; fehlendes Feld → `"auto"`; `"en"` bleibt `"en"`
- [ ] **Step 2:** `python -m unittest tests.test_i18n -v` → FAIL (`ModuleNotFoundError: secret_sanitizer.i18n`).
- [ ] **Step 3:** `i18n.py`, beide JSON-Dateien (zunächst nur `test.braces` und `app.title`), `Settings.language` implementieren.
- [ ] **Step 4:** In `tests/helpers.py` und `tests/gui_smoke.py` vor den Paket-Importen `os.environ.setdefault(i18n.LANG_ENV_VAR, "de")` bzw. `os.environ["SECRET_SANITIZER_LANG"] = "de"` setzen (gui_smoke: per Argument `--lang en` überschreibbar, siehe Task 6), damit bestehende Tests mit deutschen Texten auf jedem System Deutsch bekommen. Beim Import von `secret_sanitizer.i18n` wird die Sprache einmal über `resolve_language(None, "auto")` gesetzt.
- [ ] **Step 5:** Alle Tests: `python -m unittest discover -s tests -t .` → OK.
- [ ] **Step 6:** Commit `"i18n: Sprachmodul, Sprachdateien, Spracheinstellung"`.

---

### Task 2: Kategorien, Gruppen, Modi, mitgelieferte Regeln

**Files:**
- Modify: `secret_sanitizer/core/models.py`, `secret_sanitizer/config.py`, `secret_sanitizer/core/rules.py` (`load_ruleset`), alle Aufrufer von `MODE_LABELS`/`GROUPS`/`.label` (`cli.py:112-116`, `gui/app.py:133-184,912,921`, `gui/widgets.py:90-104,188`, `gui/rule_editor.py:300`), beide JSON-Dateien
- Test: `tests/test_i18n.py`

**Interfaces:**
- Consumes: `t`, `set_language`, `has_key` aus Task 1
- Produces:
  - `Category` behält `id, group, color`; `label` und `description` werden Properties: `t(f"category.{id}.label")` / `t(f"category.{id}.description")`. Konstruktor-Signatur: `Category(id, group, color)`. Doppelte `PHONE`-Zeile in `_CATEGORY_LIST` entfernen.
  - `GROUPS: tuple[str, ...]` (Reihenfolge wie heute) und `group_label(group: str) -> str` = `t(f"group.{group}")`
  - `config.mode_label(mode: str) -> str` = `t(f"mode.{mode}")`; `MODE_LABELS` entfällt.
  - `load_ruleset(...)`: Für jede **mitgelieferte** Regel (vor `merge_user_rules`) `name`/`description` aus `rule.<id>.name` / `rule.<id>.description` setzen, falls `has_key`, sonst Original behalten. Eigene Regeln bleiben unangetastet.

- [ ] **Step 1: Tests**:
  - `test_every_category_translated`: für jede Sprache und jede `CATEGORIES`-ID existieren `category.<ID>.label` und `.description` in `load_catalog(lang)`
  - `test_every_group_and_mode_translated`: `group.<g>` für alle `GROUPS`, `mode.<m>` für alle `MODES`
  - `test_every_builtin_rule_translated`: jede Regel-`id` in `rules/default_rules.json` hat `rule.<id>.name` und `rule.<id>.description` in beiden Katalogen
  - `test_category_label_follows_language`: `set_language("en")` → `CATEGORIES["PASSWORD"].label == "Passwords"`; `set_language("de")` → `"Passwörter"` (in `tearDown` auf `"de"` zurück)
  - `test_user_rule_name_not_translated`: Regel mit id `aws_access_key` in `UserRules`, Name `"Meine AWS-Regel"` → nach `load_ruleset` + Merge bleibt `"Meine AWS-Regel"` in `en`
- [ ] **Step 2:** Tests laufen lassen → FAIL.
- [ ] **Step 3:** Umsetzen; deutsche Texte 1:1 aus den bisherigen Werten in `de.json` übernehmen, englische Texte natürlich und knapp schreiben (z. B. `Passwords`, `Credentials & keys`, `Strict / Normal / Loose`).
- [ ] **Step 4:** Alle Tests → OK.
- [ ] **Step 5:** Commit `"i18n: Kategorien, Modi und Regeln zweisprachig"`.

---

### Task 3: Kern-Meldungen, Bericht, Ausgabeordner, Worker

**Files:**
- Modify: `secret_sanitizer/core/files.py` (u. a. Z. 40, 451, 663, 840-878, alle `RunError`/Meldungen), `core/models.py` (`Report.to_text` und andere Texte), `core/office.py`, `core/archives.py`, `core/pdf.py`, `core/profiles.py`, `core/rules.py` (Fehlertexte), `core/pipeline.py`, `core/encoding.py`, `core/parallel.py`, beide JSON-Dateien
- Test: `tests/test_files.py`, `tests/test_parallel.py`

**Interfaces:**
- Consumes: `t`, `current_language`, `set_language`
- Produces:
  - `REPORT_NAMES = {"de": "secret_sanitizer_bericht.txt", "en": "secret_sanitizer_report.txt"}`, `report_name() -> str` (aktive Sprache). `REPORT_NAME` entfällt; Aufrufer auf `report_name()` bzw. `REPORT_NAMES.values()` umstellen.
  - `check_clearable`: Ordner gilt als eigener, wenn **einer** der beiden Berichte darin liegt.
  - `find_stale`: beide Berichtsnamen überspringen.
  - `_dest_names`: beide Namen in `used` reservieren.
  - Nach dem Schreiben des Berichts: Bericht der anderen Sprache im `out_root` löschen, falls vorhanden.
  - `parallel._init_worker(..., language)`: neuer letzter Parameter vor `cancel_event`; ruft `set_language(language)`. `run_tasks`-Aufrufer übergeben `current_language()` in `initargs`.

- [ ] **Step 1: Tests**:
  - `test_report_name_per_language` (test_files): Lauf in `en` schreibt `secret_sanitizer_report.txt`, Inhalt enthält einen englischen Kopf (Wert von `t("report.title")` in en), keinen deutschen
  - `test_old_report_other_language_is_replaced`: Lauf in `de` → Ordner mit `_bericht.txt`; zweiter Lauf in `en` ins selbe Ziel mit `clean_output=True` gelingt, danach existiert nur `secret_sanitizer_report.txt`
  - `test_other_report_not_stale`: zweiter Lauf ohne clean → `find_stale` meldet keinen der beiden Berichtsnamen; alter Bericht ist gelöscht
  - `test_input_named_like_report_gets_renamed`: Eingabeordner enthält Datei `secret_sanitizer_report.txt`; Lauf in `de` → Ausgabe heißt `secret_sanitizer_report (2).txt`
  - `test_parallel_messages_in_english` (test_parallel): Ordnerlauf mit `workers=2` und genug Dateien für Parallelisierung in `en`; Bericht enthält keine deutschen Schlüsselwörter (`"Dateien"`, `"Ersetzt"`), dafür die englischen Gegenstücke
  - Bestehende Tests, die `REPORT_NAME` nutzen, auf `report_name()` umstellen
- [ ] **Step 2:** Tests → FAIL.
- [ ] **Step 3:** Alle Meldungen im Kern auf `t()` umstellen (Fehlermeldungen nennen weiter nur die Fehlerart, nie Werte), Berichtsnamen und Worker-Sprache umsetzen.
- [ ] **Step 4:** Alle Tests → OK.
- [ ] **Step 5:** Commit `"i18n: Kern-Meldungen, Bericht und Worker zweisprachig"`.

---

### Task 4: CLI

**Files:**
- Modify: `secret_sanitizer/cli.py`, `secret_sanitizer/i18n.py` (`install_argparse`), `de.json` (`_argparse`), `en.json`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `t`, `resolve_language`, `set_language`, `Settings.language`
- Produces:
  - Option `--lang {de,en}` (Optionsname und Werte sprachunabhängig). `main()` liest sie vor dem Bauen des eigentlichen Parsers (Vorab-Parser mit `parse_known_args`), ruft `set_language(resolve_language(args.lang, settings.language))`, dann `install_argparse()` und baut den Parser.
  - `i18n.install_argparse() -> None`: ersetzt `argparse._` und `argparse.ngettext` durch Funktionen, die in Deutsch im Abschnitt `_argparse` nachschlagen (msgid → Text, sonst msgid), in Englisch die msgid zurückgeben. Abdecken mindestens: `"usage: "`, `"options"`, `"positional arguments"`, `"show this help message and exit"`, `"%(prog)s: error: %(message)s\n"`, `"the following arguments are required: %s"`, `"unrecognized arguments: %s"`, `"invalid choice: %(value)r (choose from %(choices)s)"`, `"expected one argument"`. Die genauen msgids der laufenden Python-Version (3.14) im argparse-Quelltext prüfen.

- [ ] **Step 1: Tests** (über die bestehende CLI-Testhilfe, Umgebungsvariable je Test setzen):
  - `test_help_german`: `--help` mit `de` enthält `"Optionen"` und `"Aufruf:"`, nicht `"options:"`/`"usage:"`; enthält `t("cli.hint")` in de
  - `test_help_english`: `--lang en --help` enthält `"options:"` und `"Hint: Always check the results yourself."`, kein deutsches Wort aus der deutschen Hilfe (z. B. `"Ausgabeordner"`)
  - `test_lang_flag_beats_env`: env `de`, `--lang en` → englische Ausgabe
  - `test_stdin_hint_english`: `echo password=Sommer2024! | ... --lang en -` → stdout `password=[PASSWORD_1]`, stderr englisch (`"Replaced: PASSWORD=1"`)
  - `test_error_message_german`: unbekannte Option in `de` → stderr enthält `"Fehler:"` und Rückgabewert `2`
  - `test_list_categories_english`: `--lang en --list-categories` zeigt `"Passwords"`
- [ ] **Step 2:** Tests → FAIL.
- [ ] **Step 3:** Umsetzen. Englischer Hinweistext exakt: `"Hint: Always check the results yourself."`; deutscher bleibt `"Hinweis: Ergebnisse bitte immer selbst prüfen."`.
- [ ] **Step 4:** Alle Tests → OK.
- [ ] **Step 5:** Commit `"i18n: CLI zweisprachig, --lang"`.

---

### Task 5: Eigene Dialoge statt messagebox

**Files:**
- Create: `secret_sanitizer/gui/dialogs.py`, `tests/test_dialogs.py`
- Modify: `gui/app.py`, `gui/rule_editor.py`, `gui/widgets.py` (alle `messagebox.*`), beide JSON-Dateien (`dialog.ok`, `dialog.yes`, `dialog.no`, `dialog.cancel`)

**Interfaces:**
- Consumes: `t`
- Produces (gleiche Rückgabewerte wie `tkinter.messagebox`):
  - `show_info(title: str, message: str, parent) -> None`
  - `show_warning(title: str, message: str, parent) -> None`
  - `show_error(title: str, message: str, parent) -> None`
  - `ask_yes_no(title: str, message: str, parent) -> bool`
  - `ask_yes_no_cancel(title: str, message: str, parent) -> bool | None` (Abbrechen/Schließen → `None`)
  - Umsetzung: `ctk.CTkToplevel`, modal (`transient(parent)`, `grab_set()`, `wait_window()`), über dem Elternfenster zentriert, Symbol je Art (ℹ / ⚠ / ✖ / ?), Text umbricht. Tasten: Enter = Standard-Button (OK bzw. Ja), Escape = OK (Info/Warnung/Fehler), Nein (`ask_yes_no`) bzw. Abbrechen (`ask_yes_no_cancel`); Fenster-Schließen wie Escape.
  - Hilfsparameter nur für Tests: `_auto: str | None = None` (`"yes"|"no"|"cancel"|"ok"`) – löst per `after(50, …)` den Button aus.

- [ ] **Step 1: Tests** (`tests/test_dialogs.py`, `skipUnless` customtkinter importierbar und ein Display vorhanden, wie bei den bestehenden GUI-Tests):
  - `test_yes_no_returns_true_false`: `_auto="yes"` → `True`, `_auto="no"` → `False`
  - `test_yes_no_cancel_returns_none`: `_auto="cancel"` → `None`
  - `test_buttons_follow_language`: in `en` heißen die Buttons `"Yes"`/`"No"`, in `de` `"Ja"`/`"Nein"` (Button-Texte über die Widget-Hierarchie lesen)
  - `test_no_messagebox_left`: statischer Scan – `secret_sanitizer/gui/*.py` enthält kein `messagebox.` mehr
- [ ] **Step 2:** Tests → FAIL.
- [ ] **Step 3:** `dialogs.py` umsetzen, alle 35 Aufrufe umstellen (Logik der Aufrufer unverändert).
- [ ] **Step 4:** Alle Tests + `python tests/gui_smoke.py` → OK.
- [ ] **Step 5:** Commit `"GUI: eigene Dialoge statt messagebox"`.

---

### Task 6: GUI-Texte, Spracheinstellung, Neustart

**Files:**
- Modify: `gui/app.py`, `gui/rule_editor.py`, `gui/widgets.py`, `packaging/launcher_gui.py` (falls nötig für Neustart), `secret_sanitizer/__main__.py`, beide JSON-Dateien, `tests/gui_smoke.py`
- Test: `tests/test_i18n.py`

**Interfaces:**
- Consumes: alles aus Task 1–5
- Produces:
  - Alle sichtbaren Texte (Reiter, Buttons, Labels, Toasts, Dialogtitel und -texte, `filedialog`-Titel, Fenstertitel) über `t()`. Reiternamen werden beim Aufbau aus `t()` gesetzt; Code, der Reiter über den Namen anspricht, nutzt dieselben `t()`-Werte.
  - Einstellungs-Reiter: Auswahl „Sprache“ mit `Automatisch | Deutsch | English` (Schlüssel `gui.settings.language*`; „Deutsch“ und „English“ stehen in beiden Sprachen so). Speichern mit geänderter Sprache → `ask_yes_no(t("gui.restart.title"), t("gui.restart.message"))`; Text erwähnt, dass die Zuordnung für die Rückübersetzung verloren geht. Bei Ja: `restart_app()`.
  - `restart_app() -> None` in `gui/app.py`: frozen (`getattr(sys, "frozen", False)`) → `subprocess.Popen([sys.executable, *sys.argv[1:]])`, sonst `subprocess.Popen([sys.executable, "-m", "secret_sanitizer", "--gui"])`; danach Fenster schließen.
  - GUI-Start setzt die Sprache über `resolve_language(None, settings.language)`.
  - `tests/gui_smoke.py` akzeptiert `--lang de|en` (Standard `de`) und läuft in beiden Sprachen durch.

- [ ] **Step 1: Test** `test_all_t_keys_exist` (statischer Scan): alle Literale aus `re.findall(r'\bt\(\s*"([^"]+)"', quelltext)` in `secret_sanitizer/**/*.py` existieren in beiden Katalogen. (Läuft schon ab Task 1 mit, wird hier erst wirklich belastet.)
- [ ] **Step 2: Test** `test_no_german_literals_in_gui`: grober Scan von `gui/*.py` auf String-Literale mit Umlauten oder typischen deutschen Wörtern (`" und "`, `"Datei"`, `"Ordner"`, `"Einstellungen"`) außerhalb von Kommentaren/Docstrings → keiner gefunden (Ausnahmen per expliziter Liste, z. B. `"Deutsch"`).
- [ ] **Step 3:** Tests → FAIL.
- [ ] **Step 4:** Umsetzen.
- [ ] **Step 5:** Alle Tests, `python tests/gui_smoke.py --lang de` und `--lang en` → beide `GUI-Smoke-Test OK`.
- [ ] **Step 6:** Manuelle Sichtprüfung: App in `en` und `de` starten (`SECRET_SANITIZER_LANG`), alle Reiter durchklicken, prüfen, dass nichts abgeschnitten ist und keine fremdsprachigen Texte auftauchen (Ausnahme: Datei-Dialog). Gefundenes beheben.
- [ ] **Step 7:** Commit `"i18n: GUI zweisprachig, Sprachauswahl mit Neustart"`.

---

### Task 7: Doku, Version, Build, Release

**Files:**
- Create: `README.de.md` (bisherige `README.md`, oben Link `[English](README.md)`)
- Modify: `README.md` (vollständige englische Fassung, oben Link `[Deutsch](README.de.md)`; neu in beiden: Abschnitt zur Sprache – Automatik, `--lang`, `SECRET_SANITIZER_LANG`, Einstellung, Berichtsnamen), `secret_sanitizer/config.py` (`APP_VERSION = "1.3.0"`)

- [ ] **Step 1:** READMEs schreiben. Englischer Hinweis oben: `> Note: Always check the results yourself.`
- [ ] **Step 2:** Version auf `1.3.0`.
- [ ] **Step 3:** `build_exe.bat` (über `cmd /c "<voller Pfad>\build_exe.bat"`) → endet mit `Fertig. Die Programme liegen im Ordner dist\`, Tests im Build `OK`.
- [ ] **Step 4:** `dist\secret_sanitizer_cli.exe --lang en --help` zeigt englische Hilfe; ohne `--lang` auf diesem Rechner deutsch. GUI-EXE einmal mit `SECRET_SANITIZER_LANG=en` starten und Sichtprüfung.
- [ ] **Step 5:** Commit `"Version 1.3.0, README Englisch + Deutsch"`.
- [ ] **Step 6:** **Nutzer fragen**, ob `zweisprachig` nach `main` gemergt und gepusht werden soll und ob die GitHub-Beschreibung geändert werden soll. Vorschlag: `"Redacts passwords, tokens and IPs from logs, configs and text before you share them (offline, GUI + CLI, English/German)."` Erst nach Ja: `git switch main && git merge --ff-only zweisprachig && git push origin main`, dann `gh repo edit Slide789/secret-sanitizer --description "…"`.
