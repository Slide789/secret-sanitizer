# Design: Secret Sanitizer zweisprachig (Deutsch / Englisch)

Stand: 2026-11-08 · Version danach: 1.3.0

## Ziel und Warum

Secret Sanitizer soll als **eine** App erscheinen, die Deutsch und Englisch **vollständig und gleichwertig**
unterstützt. Englisch ist keine abgespeckte Zusatzversion: Jeder Text, den ein Nutzer sieht oder bekommt
(GUI, CLI, Fehlermeldungen, Regeln, Kategorien, Bericht, Doku), gibt es in beiden Sprachen.

## Ziele

- Eine EXE (GUI) und eine CLI-EXE, beide mit beiden Sprachen.
- Sprache wird automatisch erkannt (Windows-Anzeigesprache) und lässt sich umstellen (GUI-Einstellungen,
  CLI-Option, Konfiguration).
- Alle Texte für Nutzer in beiden Sprachen: Fenster, Reiter, Buttons, Hinweise, Toasts, Dialoge,
  Fehlermeldungen, Modusnamen, Kategorienamen und -beschreibungen, Namen und Beschreibungen der
  mitgelieferten Regeln, CLI-Hilfe und -Ausgaben, Bericht.
- Doku auf GitHub in beiden Sprachen.
- Tests stellen sicher, dass keine Sprache unvollständig ist.

## Nicht-Ziele

- Weitere Sprachen (der Aufbau soll sie aber leicht möglich machen: eine weitere Datei).
- Übersetzung von Inhalten, die der Nutzer selbst anlegt (eigene Regeln in `user_rules.json`, eigene
  Wortlisten, Profilnamen). Die bleiben, wie der Nutzer sie schreibt.
- Code-Kommentare und Docstrings bleiben Deutsch.
- Änderungen an der Erkennung. Sie kennt schon beide Sprachen (z. B. `password`/`passwort`/`kennwort`,
  „password is …“ / „Passwort lautet …“).

## Anti-Ziele (wäre ein Fehlschlag, auch wenn es technisch läuft)

- Gemischte Oberfläche: in einer Sprache tauchen Texte der anderen auf (einzige Ausnahme: der
  Datei-Dialog von Windows, siehe GUI).
- Eine Sprache bricht etwas: Tests, Build, bestehende Konfigurationen, Profile oder Ausgabeordner früherer
  Läufe funktionieren nicht mehr.
- Neue Abhängigkeiten, Netzwerkzugriffe oder Dateien außerhalb der bisherigen Orte.
- Platzhalter (`[PASSWORD_1]` usw.) oder die Kategorie-IDs ändern sich je nach Sprache. Sie bleiben
  sprachunabhängig, sonst passt die Rückübersetzung nicht mehr.

## Rahmenbedingungen

- Python, customtkinter-GUI, argparse-CLI, PyInstaller-Build mit festgepinnten Paketen (SHA-256).
- Komplett offline, keine Telemetrie.
- Einstellungen in `%APPDATA%\secret_sanitizer\config.json` (Dataclass `Settings` in `config.py`,
  unbekannte/ungültige Werte fallen auf Standard zurück).
- Rund 480 Texte in `gui/app.py`, `gui/rule_editor.py`, `gui/widgets.py`, `cli.py`, `core/*.py`;
  Modusnamen in `config.MODE_LABELS`; Kategorien und Gruppen in `core/models.py`;
  rund 170 Namen/Beschreibungen in `rules/default_rules.json`.
- Viele bestehende Tests prüfen deutsche Texte.
- Commits nur unter Slide789, ohne Co-Author-Zeile.

## Ansätze

1. **Eigene Sprachdateien `de.json` / `en.json` mit kleiner Übersetzungsfunktion** (gewählt).
   Keine neue Abhängigkeit, passt zum geprüften Build, Vollständigkeit leicht testbar. Nachteil: keine
   Übersetzungs-Tools, man bearbeitet JSON direkt; bei zwei Sprachen unproblematisch.
2. **gettext mit `.po`/`.mo`.** Standard mit Tools wie Poedit, aber `.mo` muss im Build erzeugt und
   eingepackt werden, Vollständigkeits-Checks brauchen eigene Skripte. Für zwei Sprachen zu viel.
3. **Zwei getrennte EXEs (DE/EN).** Verworfen: kein Umschalten, doppelter Build und Release, widerspricht
   „eine App, beide Sprachen“.

Entschieden am 2026-11-08: Ansatz 1.

## Entwurf

### Übersetzungsmodul

- Neues Modul `secret_sanitizer/i18n.py` und Ordner `secret_sanitizer/locales/` mit `de.json` und
  `en.json`, flach: Schlüssel → Text, z. B. `"text_tab.copy_button": "Bereinigten Text kopieren"`.
- Funktion `t(key, **werte)`: holt den Text der aktiven Sprache und setzt Werte über `str.format` ein
  (`t("toast.saved", path=dest)`).
  Fehlt ein Schlüssel in der aktiven Sprache, wird Englisch genommen, fehlt er auch dort, der Schlüssel
  selbst (nur als Notnagel; Tests verhindern das).
- Funktion `set_language("de" | "en")` und `current_language()`. Die Sprache wird einmal beim Start gesetzt.
- Schlüssel sind sprechende IDs (Bereich.Element), nicht der deutsche Text.
- Sprachdateien kommen über die PyInstaller-Spec als Daten mit in beide EXEs.

### Sprachwahl

Reihenfolge (das Erste, was gesetzt ist, gewinnt):
1. CLI: `--lang de|en`
2. Umgebungsvariable `SECRET_SANITIZER_LANG`
3. `config.json`: neues Feld `language` mit `"auto"` (Standard), `"de"` oder `"en"`
4. `"auto"`: Windows-Anzeigesprache (`GetUserDefaultUILanguage`), Deutsch wenn die Hauptsprache Deutsch ist,
   sonst Englisch. Außerhalb von Windows: `locale` des Systems, gleiche Regel.

Bestehende `config.json` aus 1.2.0 ohne `language`-Feld werden wie `"auto"` behandelt. *(Meine Entscheidung:
Das Repo ist privat, es gibt kaum bestehende Installationen, und auf deutschem Windows bleibt alles Deutsch.)*

Die Sprache wird auch an die Worker-Prozesse für mehrere CPU-Kerne (`core/parallel.py`) weitergegeben, damit
deren Meldungen in derselben Sprache sind.

### GUI

- Alle sichtbaren Texte über `t()`, auch Reiternamen, Dialogtitel und Messageboxen.
- Im Reiter „Einstellungen“ eine Auswahl „Sprache: Automatisch / Deutsch / English“.
- Umstellen wirkt nach einem Neustart. Beim Speichern fragt die App „Jetzt neu starten?“ und weist darauf
  hin, dass die Zuordnung für die Rückübersetzung dabei verloren geht. *(Meine Entscheidung: Ein Umbau des
  Fensters im laufenden Betrieb wäre deutlich aufwendiger und fehleranfällig.)*
- Eigene Dialoge statt `tkinter.messagebox` (entschieden am 2026-11-08): ein kleines Modul
  `gui/dialogs.py` mit `show_info`, `show_warning`, `show_error`, `ask_yes_no`, `ask_yes_no_cancel` im
  customtkinter-Stil, modal, mit Tastatur (Enter = Standard-Button, Escape = Abbrechen/Nein) und
  übersetzten Buttons. Alle rund 35 `messagebox`-Aufrufe laufen darüber; die Rückgabewerte entsprechen
  denen von `messagebox`, damit die aufrufende Logik gleich bleibt. Grund: In der App-Sprache sollen auch
  die Buttons stimmen, unabhängig von der Windows-Sprache.
- Der Datei-Öffnen/Speichern-Dialog (`filedialog`) bleibt der von Windows und folgt der Windows-Sprache.
  Die Titel, die die App ihm übergibt, werden übersetzt.
- Englische und deutsche Texte sind unterschiedlich lang: Buttons, Spalten und Trefferliste müssen in beiden
  Sprachen passen (Prüfung per Augenschein im Smoke-Test).

### CLI

- Hilfe, Ausgaben und Fehlermeldungen über `t()`. Neue Option `--lang`.
- Die eingebauten argparse-Texte („usage:“, „options:“, „show this help message and exit“) werden in Deutsch
  ebenfalls übersetzt (eigener Formatter bzw. eigene Hilfe-Option). *(Meine Entscheidung, damit es keine
  gemischte Oberfläche gibt.)*
- Optionsnamen (`--mode`, `--check` …) und Werte (`strict`, `normal`, `loose`, Kategorie-IDs) bleiben gleich.
  Rückgabewerte bleiben gleich.

### Kategorien, Modi, Regeln

- `Category`-Label und -Beschreibung sowie Gruppennamen aus `core/models.py` über Schlüssel
  `category.<ID>.label` / `category.<ID>.description` / `group.<id>`.
- Modusnamen über `mode.strict` usw.
- Mitgelieferte Regeln: Name und Beschreibung über `rule.<id>.name` / `rule.<id>.description` in den
  Sprachdateien. `default_rules.json` behält seine deutschen Felder als Rückfall. *(Meine Entscheidung: alle
  Übersetzungen an einem Ort, der Vollständigkeits-Test deckt sie mit ab.)*
- Eigene Regeln (`user_rules.json`) zeigen ihren Namen so, wie der Nutzer ihn eingegeben hat. Überschreibt
  eine eigene Regel eine mitgelieferte (gleiche `id`), gilt der Name aus der eigenen Regel.

### Bericht und Ausgabedateien

- Berichtstext in der aktiven Sprache.
- Dateiname: `secret_sanitizer_bericht.txt` (Deutsch) bzw. `secret_sanitizer_report.txt` (Englisch).
  Die Prüfung „ist das ein Ausgabeordner eines früheren Laufs?“ erkennt **beide** Namen, damit ein Wechsel
  der Sprache keine Ordner unbrauchbar macht und `--clean` weiter funktioniert. Beim Aufräumen werden beide
  Namen als Bericht behandelt.
- Schreibt ein Lauf seinen Bericht in einen Ordner, in dem noch der Bericht der anderen Sprache liegt, wird
  dieser alte Bericht gelöscht. So liegt nie ein veralteter Bericht neben dem aktuellen. Beide Namen sind
  für Ausgabedateien reserviert (`_dest_names`), damit eine Eingabedatei mit diesem Namen nicht kollidiert.
  *(Meine Entscheidung.)*
- Ordnernamen `_sanitized` und Endungen wie `.pdf.txt` bleiben gleich.

### Doku

- `README.md` wird Englisch (GitHub zeigt sie zuerst), `README.de.md` ist die bisherige deutsche Fassung.
  Beide verlinken oben aufeinander. *(Meine Entscheidung; lässt sich leicht umdrehen.)*
- GitHub-Beschreibung zweisprachig oder Englisch mit deutschem Zusatz.

### Tests

- Neuer Test: `de.json` und `en.json` haben genau dieselben Schlüssel, keine leeren Texte, und die
  `{platzhalter}` in jedem Text stimmen überein.
- Neuer Test: Jede mitgelieferte Regel und jede Kategorie hat Name/Beschreibung in beiden Sprachen.
- Neuer Test: Im Code gibt es keine `t("…")`-Schlüssel, die in den Dateien fehlen (statischer Scan).
- Bestehende Tests laufen fest mit Deutsch (Sprache im Test-Setup setzen) und prüfen weiter ihre Texte.
- CLI-Tests zusätzlich mit `--lang en` für Hilfe, Hinweis und Bericht.
- GUI-Smoke-Test läuft in beiden Sprachen.
- Test, dass ein alter Ausgabeordner mit `secret_sanitizer_bericht.txt` auch mit Englisch erkannt wird.

### Release

- Version 1.3.0. Build wie bisher über `build_exe.bat`, Ergebnis in `dist\`.
- Commit und Push als Slide789 sowie die neue GitHub-Beschreibung (`gh repo edit`) gehören zum letzten
  Schritt, aber erst nach kurzer Rückfrage beim Nutzer. *(Meine Entscheidung.)*

## Dem Umsetzer überlassen

- Genaue Schlüsselnamen und Aufteilung in Bereiche.
- Ob `t()` die Sprachdatei beim Import oder beim ersten Aufruf lädt.
- Wie genau die argparse-Standardtexte ersetzt werden.
- Die englischen Formulierungen im Detail (natürlich, knapp, gleicher Ton wie die deutschen Texte).
- Reihenfolge der Umstellung (z. B. Datei für Datei, mit grünen Tests nach jedem Schritt).
