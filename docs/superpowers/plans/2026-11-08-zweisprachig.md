# Umsetzung: Deutsch und Englisch

Wie die zweisprachige Version 1.3.0 gebaut wurde, in sieben Schritten. Das Warum steht im
[Design](../specs/2026-11-08-zweisprachig-design.md).

Kurz zusammengefasst: Ein kleines Modul `secret_sanitizer/i18n.py` lädt die flachen Sprachdateien
`locales/de.json` und `locales/en.json` und stellt `t(key, **werte)` bereit. Alle Texte laufen über `t()`.
Kategorien, Modi und mitgelieferte Regeln holen ihre Anzeigetexte über Schlüssel, und die Oberfläche hat
eigene Dialoge statt `tkinter.messagebox`. Technik: Python 3.10+, customtkinter, argparse, unittest,
PyInstaller (Onefile).

## Feste Regeln für alle Schritte

- Keine neuen Abhängigkeiten, keine Netzwerkzugriffe, keine neuen Speicherorte. Die Konfiguration bleibt
  in `%APPDATA%\secret_sanitizer\config.json`.
- Platzhalter (`[PASSWORD_1]` …), Kategorie-IDs, Optionsnamen und -werte der Kommandozeile
  (`strict|normal|loose`, Kategorie-IDs), Rückgabewerte, der Ordnername `_sanitized` und die Endung
  `.pdf.txt` hängen nicht von der Sprache ab.
- Reihenfolge der Sprachwahl: `--lang de|en`, dann `SECRET_SANITIZER_LANG`, dann das Feld `language` in der
  `config.json` (`"auto"` als Standard, `"de"`, `"en"`), dann die Systemsprache (Deutsch, wenn die
  Hauptsprache Deutsch ist, sonst Englisch).
- Fehlt `language` in einer alten `config.json` oder steht dort Unsinn, gilt `"auto"`.
- Der Bericht heißt `secret_sanitizer_bericht.txt` (de) bzw. `secret_sanitizer_report.txt` (en). Beide
  Namen gelten als Bericht.
- Eigene Regeln, Wortlisten und Profilnamen werden nie übersetzt.
- Code-Kommentare und Docstrings bleiben Deutsch.
- Die einzige erlaubte Mischung ist der Datei-Dialog von Windows, der der Windows-Sprache folgt.
- Gearbeitet wurde auf dem Branch `zweisprachig`. Getestet wird mit
  `python -m unittest discover -s tests -t .`

## Fälle, die leicht schiefgehen

- Nach einem Sprachwechsel enthält ein alter Ausgabeordner den Bericht der anderen Sprache. Der Ordner
  muss trotzdem als eigener gelten, `--clean` muss gehen, und der alte Bericht wird ersetzt.
- Ein Text enthält wörtliche geschweifte Klammern, etwa das Platzhalterformat `[{CATEGORY}_{N}]`. Ohne
  Werte gibt `t()` den Text unverändert zurück, mit Werten muss jeder Text formatierbar sein.
- In der `config.json` steht ein kaputter Wert für `language` (`"fr"`, `5`, `null`). Die App startet dann
  mit `"auto"`.
- Bei einem Ordnerlauf auf mehreren CPU-Kernen auf Englisch müssen auch die Worker-Prozesse englische
  Meldungen liefern.
- Wenn sich die Systemsprache nicht ermitteln lässt (Fehler in ctypes, leere Locale), läuft das Programm
  auf Englisch weiter.

## 1. Übersetzungsmodul, Sprachwahl, Konfiguration

Neu: `secret_sanitizer/i18n.py`, `locales/de.json`, `locales/en.json`, `tests/test_i18n.py`. Angepasst:
`config.py`, `tests/helpers.py`, `tests/gui_smoke.py` und die PyInstaller-Spec, die die Sprachdateien in
beide EXEs packt.

Was `i18n.py` bereitstellt:

- `LANGUAGES = ("de", "en")` und `LANG_ENV_VAR = "SECRET_SANITIZER_LANG"`
- `t(key, **values)`: ohne Werte der unveränderte Text, mit Werten `str.format`. Fehlt der Schlüssel, kommt
  der englische Text, sonst der Schlüssel selbst.
- `has_key(key)`, `set_language(lang)` (wirft bei ungültiger Sprache `ValueError`), `current_language()`
- `detect_system_language()`: unter Windows `GetUserDefaultUILanguage()`, Deutsch bei
  `langid & 0x3FF == 0x07`, sonst `locale.getlocale()`. Jeder Fehler ergibt `"en"`.
- `resolve_language(cli, setting)` nach der Reihenfolge oben
- `load_catalog(lang)` für die Tests. Die Dateien liegen neben dem Modul und werden so auch in der EXE
  gefunden.

`Settings` bekommt das Feld `language = "auto"`. Alles außer `"auto"`, `"de"` und `"en"` wird zu `"auto"`.
Die Sprachdateien sind flach (`bereich.element`). Nur `de.json` hat zusätzlich den Abschnitt `_argparse`
für die argparse-Texte (Schritt 4).

Tests: beide Dateien haben dieselben Schlüssel, keine leeren Texte, dieselben Platzhalter, jeder Text lässt
sich formatieren, `t()` ohne Werte lässt Klammern stehen, fehlende Schlüssel fallen zurück, die Reihenfolge
der Sprachwahl stimmt, Fehler bei der Systemsprache ergeben Englisch, ungültige Einstellungen ergeben
`"auto"`. Dazu ein Scan, der prüft, dass jeder `t("…")`-Schlüssel im Code in beiden Dateien steht. Die
bestehenden Tests laufen fest auf Deutsch.

## 2. Kategorien, Gruppen, Modi, mitgelieferte Regeln

Angepasst: `core/models.py`, `config.py`, `core/rules.py` und alle Stellen, die `MODE_LABELS`, `GROUPS`
oder `.label` benutzt haben.

- `Category(id, group, color)`. Name und Beschreibung sind jetzt Properties, die `category.<ID>.label` und
  `category.<ID>.description` nachschlagen. Eine doppelte `PHONE`-Zeile fiel dabei weg.
- `GROUPS` ist ein Tupel, `group_label(group)` liefert den Namen. `config.mode_label(mode)` ersetzt
  `MODE_LABELS`.
- `load_ruleset` setzt Name und Beschreibung der mitgelieferten Regeln aus `rule.<id>.name` und
  `rule.<id>.description`, bevor die eigenen Regeln dazukommen. Eigene Regeln bleiben, wie sie sind.

Tests: jede Kategorie, Gruppe, jeder Modus und jede mitgelieferte Regel ist in beiden Sprachen da,
Kategorienamen folgen der Sprache, und der Name einer eigenen Regel bleibt auch auf Englisch unverändert.

## 3. Meldungen im Kern, Bericht, Ausgabeordner, Worker

Angepasst: `core/files.py`, `core/models.py`, `core/office.py`, `core/archives.py`, `core/pdf.py`,
`core/profiles.py`, `core/rules.py`, `core/pipeline.py`, `core/encoding.py`, `core/parallel.py`.

- `REPORT_NAMES = {"de": "secret_sanitizer_bericht.txt", "en": "secret_sanitizer_report.txt"}` und
  `report_name()` für die aktive Sprache ersetzen `REPORT_NAME`.
- `check_clearable` erkennt einen eigenen Ausgabeordner an beiden Berichtsnamen, `find_stale` überspringt
  beide, `_dest_names` reserviert beide.
- Nach dem Schreiben des Berichts wird der Bericht der anderen Sprache im Ausgabeordner gelöscht.
- `parallel._init_worker` bekommt die Sprache mit und setzt sie im Worker-Prozess.
- Fehlermeldungen nennen weiterhin nur die Art des Fehlers, nie einen Wert.

Tests: ein Lauf auf Englisch schreibt `secret_sanitizer_report.txt` mit englischem Inhalt, ein zweiter Lauf
in einer anderen Sprache ersetzt den alten Bericht (mit und ohne `--clean`), eine Eingabedatei mit dem
Namen eines Berichts wird zu `secret_sanitizer_report (2).txt`, und Worker-Prozesse liefern englische
Meldungen.

## 4. Kommandozeile

Angepasst: `cli.py`, `i18n.py`, beide Sprachdateien.

- Neue Option `--lang {de,en}`. `main()` liest sie mit einem kleinen Vorab-Parser, setzt die Sprache und
  baut erst danach den eigentlichen Parser.
- `install_argparse()` ersetzt `argparse._` und `argparse.ngettext`. Auf Deutsch kommen die Texte aus dem
  Abschnitt `_argparse`, auf Englisch bleibt alles wie in Python. Abgedeckt sind mindestens „usage“,
  „options“, „positional arguments“, die Hilfe-Zeile und die üblichen Fehlermeldungen (fehlendes Argument,
  unbekanntes Argument, ungültige Auswahl). Die genauen Texte stammen aus argparse von Python 3.14.
- Der Hinweis lautet auf Englisch `Hint: Always check the results yourself.` und auf Deutsch weiter
  `Hinweis: Ergebnisse bitte immer selbst prüfen.`

Tests: die deutsche Hilfe ist komplett deutsch, die englische komplett englisch, `--lang` schlägt die
Umgebungsvariable, die Ausgabe über die Pipe ist auf Englisch richtig, Fehler auf Deutsch enden mit
Rückgabewert `2`, und `--list-categories` zeigt englische Namen.

## 5. Eigene Dialoge statt messagebox

Neu: `gui/dialogs.py` und `tests/test_dialogs.py`. Alle `messagebox`-Aufrufe in `gui/app.py` und
`gui/rule_editor.py` laufen jetzt darüber.

- `show_info`, `show_warning`, `show_error`, `ask_yes_no` (gibt `bool` zurück) und `ask_yes_no_cancel`
  (`True`, `False` oder `None` bei Abbrechen), jeweils mit Titel, Text und Elternfenster
- Die Dialoge sind modal und über dem Elternfenster zentriert, mit Symbol je Art und umbrechendem Text.
  Enter löst den Standard-Button aus, Escape und das Schließen des Fensters bedeuten OK, Nein oder
  Abbrechen.
- Für die Tests gibt es einen versteckten Parameter `_auto`, der nach kurzer Zeit einen Button auslöst.

Tests: die Rückgabewerte stimmen, die Buttons heißen je nach Sprache Ja/Nein oder Yes/No, und im
GUI-Code steht kein `messagebox.` mehr.

## 6. Texte der Oberfläche, Spracheinstellung, Neustart

Angepasst: `gui/app.py`, `gui/rule_editor.py`, `gui/widgets.py`, `__main__.py`, die Sprachdateien und
`tests/gui_smoke.py`.

- Alle sichtbaren Texte laufen über `t()`: Reiter, Buttons, Beschriftungen, Kurzmeldungen, Dialoge, Titel
  der Datei-Dialoge, Fenstertitel.
- Im Reiter „Einstellungen“ gibt es die Auswahl Automatisch, Deutsch oder English. Ändert man die Sprache,
  fragt die App, ob sie neu starten soll, und weist darauf hin, dass die Zuordnung für die Rückübersetzung
  verloren geht.
- `restart_app()` startet das Programm neu, in der EXE mit demselben Aufruf, sonst über
  `python -m secret_sanitizer --gui`, und schließt dann das alte Fenster.
- Der GUI-Smoke-Test läuft mit `--lang de` und mit `--lang en`.

Tests: ein Scan stellt sicher, dass im GUI-Code keine deutschen Texte mehr fest stehen. Danach wurde die
App in beiden Sprachen durchgeklickt, um abgeschnittene Texte zu finden.

## 7. Doku, Version, Build

- `README.md` ist jetzt Englisch, die bisherige deutsche Fassung liegt in `README.de.md`. Beide verlinken
  oben aufeinander und haben einen neuen Abschnitt zur Sprache.
- `APP_VERSION = "1.3.0"`
- Gebaut über `build_exe.bat`. Geprüft wurde danach, dass `secret_sanitizer_cli.exe --lang en --help`
  englisch ist, ohne `--lang` auf einem deutschen System deutsch, und dass die GUI-EXE auf Englisch
  startet.
- Danach wurde der Branch nach `main` gemergt, und die Beschreibung auf GitHub wurde Englisch.
