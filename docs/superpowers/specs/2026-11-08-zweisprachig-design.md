# Design: Secret Sanitizer auf Deutsch und Englisch

Stand: 2026-11-08 · umgesetzt in Version 1.3.0

## Worum es geht

Secret Sanitizer soll eine einzige App sein, die Deutsch und Englisch vollständig unterstützt. Die
englische Fassung ist keine abgespeckte Zusatzversion: Alles, was jemand sieht oder bekommt (Oberfläche,
Kommandozeile, Fehlermeldungen, Regeln, Kategorien, Bericht, Doku), gibt es in beiden Sprachen.

## Ziele

- Eine GUI-EXE und eine CLI-EXE, beide mit beiden Sprachen.
- Die Sprache wird automatisch über die Windows-Anzeigesprache erkannt und lässt sich umstellen: in den
  Einstellungen der Oberfläche, per Kommandozeilen-Option oder in der Konfiguration.
- Alle Texte gibt es in beiden Sprachen: Fenster, Reiter, Buttons, Hinweise, Kurzmeldungen, Dialoge,
  Fehlermeldungen, Modi, Kategorien, Namen und Beschreibungen der mitgelieferten Regeln, Hilfe und Ausgaben
  der Kommandozeile und der Bericht.
- Die Doku auf GitHub gibt es ebenfalls in beiden Sprachen.
- Tests sorgen dafür, dass keine der beiden Sprachen Lücken hat.

## Was nicht dazugehört

- Weitere Sprachen. Der Aufbau soll sie aber leicht machen: eine zusätzliche Datei.
- Inhalte, die man selbst anlegt (eigene Regeln in `user_rules.json`, Wortlisten, Profilnamen). Die bleiben
  so, wie man sie geschrieben hat.
- Code-Kommentare und Docstrings. Sie bleiben Deutsch.
- Änderungen an der Erkennung. Die kennt schon beide Sprachen, etwa `password`/`passwort`/`kennwort` oder
  „password is …“ / „Passwort lautet …“.

## Was auf keinen Fall passieren darf

- Eine gemischte Oberfläche, in der Texte der anderen Sprache auftauchen. Einzige Ausnahme ist der
  Datei-Dialog von Windows (siehe GUI).
- Dass eine der Sprachen etwas kaputt macht: Tests, Build, bestehende Konfigurationen, Profile oder
  Ausgabeordner früherer Läufe.
- Neue Abhängigkeiten, Netzwerkzugriffe oder Dateien an neuen Orten.
- Platzhalter (`[PASSWORD_1]` usw.) oder Kategorie-IDs, die sich je nach Sprache ändern. Sonst passt die
  Rückübersetzung nicht mehr.

## Ausgangslage

- Python mit customtkinter für die Oberfläche, argparse für die Kommandozeile und PyInstaller für den Build.
  Alle Pakete sind mit SHA-256-Prüfsummen angepinnt.
- Das Programm arbeitet komplett offline und sammelt keine Telemetrie.
- Einstellungen liegen in `%APPDATA%\secret_sanitizer\config.json` (Dataclass `Settings` in `config.py`).
  Unbekannte oder ungültige Werte fallen auf den Standard zurück.
- Vorher standen rund 480 Texte fest im Code (`gui/app.py`, `gui/rule_editor.py`, `gui/widgets.py`,
  `cli.py`, `core/*.py`), die Modusnamen in `config.MODE_LABELS`, Kategorien und Gruppen in
  `core/models.py` und rund 170 Namen und Beschreibungen in `rules/default_rules.json`.
- Viele bestehende Tests prüfen deutsche Texte.

## Mögliche Wege

1. **Eigene Sprachdateien `de.json` und `en.json` mit einer kleinen Übersetzungsfunktion.** Das braucht
   keine neue Abhängigkeit, passt zum geprüften Build, und ob beide Sprachen vollständig sind, lässt sich
   leicht testen. Dafür gibt es keine Übersetzungs-Tools, man bearbeitet das JSON direkt. Bei zwei Sprachen
   ist das kein Problem.
2. **gettext mit `.po`/`.mo`-Dateien.** Das ist der übliche Standard und hat Tools wie Poedit. Die
   `.mo`-Dateien müssten aber beim Build erzeugt und eingepackt werden, und für die Vollständigkeits-Tests
   bräuchte es eigene Skripte. Für zwei Sprachen ist das zu viel.
3. **Zwei getrennte EXEs.** Dann könnte man nicht umschalten und müsste alles doppelt bauen. Das passt nicht
   zu „eine App, zwei Sprachen“.

Gewählt am 2026-11-08: Weg 1.

## Entwurf

### Übersetzungsmodul

- Neues Modul `secret_sanitizer/i18n.py` und ein Ordner `secret_sanitizer/locales/` mit `de.json` und
  `en.json`. Die Dateien sind flach aufgebaut, Schlüssel und Text, zum Beispiel
  `"text_tab.copy_button": "Bereinigten Text kopieren"`.
- `t(key, **werte)` holt den Text der aktiven Sprache und setzt Werte per `str.format` ein, etwa
  `t("toast.saved", path=dest)`. Fehlt ein Schlüssel, nimmt die Funktion den englischen Text und als
  letzten Notnagel den Schlüssel selbst. Die Tests sorgen dafür, dass es dazu nicht kommt.
- `set_language("de" | "en")` und `current_language()`. Die Sprache wird einmal beim Start gesetzt.
- Die Schlüssel sind sprechende IDs nach dem Muster Bereich.Element und nicht der deutsche Text.
- Die Sprachdateien kommen über die PyInstaller-Spec mit in beide EXEs.

### Wie die Sprache bestimmt wird

Die erste gesetzte Angabe gewinnt:

1. Kommandozeile: `--lang de|en`
2. Umgebungsvariable `SECRET_SANITIZER_LANG`
3. Neues Feld `language` in der `config.json`: `"auto"` (Standard), `"de"` oder `"en"`
4. Bei `"auto"` die Anzeigesprache von Windows (`GetUserDefaultUILanguage`): Deutsch, wenn die Hauptsprache
   Deutsch ist, sonst Englisch. Außerhalb von Windows gilt dieselbe Regel für die `locale` des Systems.

Eine `config.json` aus Version 1.2.0 ohne das Feld `language` wird wie `"auto"` behandelt. Auf einem
deutschen Windows bleibt damit alles wie gewohnt auf Deutsch.

Die Worker-Prozesse für mehrere CPU-Kerne (`core/parallel.py`) bekommen die Sprache mit, damit auch ihre
Meldungen passen.

### Oberfläche

- Alle sichtbaren Texte laufen über `t()`, auch Reiternamen und Dialoge.
- Im Reiter „Einstellungen“ gibt es eine Auswahl „Sprache: Automatisch / Deutsch / English“.
- Eine neue Sprache gilt erst nach einem Neustart. Beim Speichern fragt die App, ob sie gleich neu starten
  soll, und sagt dazu, dass dabei die Zuordnung für die Rückübersetzung verloren geht. Das Fenster im
  laufenden Betrieb umzubauen wäre deutlich aufwendiger und fehleranfälliger.
- Statt `tkinter.messagebox` gibt es eigene Dialoge in `gui/dialogs.py`: `show_info`, `show_warning`,
  `show_error`, `ask_yes_no` und `ask_yes_no_cancel`. Sie sind modal, lassen sich per Tastatur bedienen
  (Enter für den Standard-Button, Escape für Abbrechen bzw. Nein) und haben übersetzte Buttons. Die
  Rückgabewerte entsprechen denen von `messagebox`, damit die aufrufende Logik gleich bleibt. Der Grund:
  Bei den Windows-Meldungsfenstern richten sich Ja/Nein nach der Windows-Sprache und nicht nach der App.
- Der Datei-Dialog zum Öffnen und Speichern bleibt der von Windows und folgt deshalb der Windows-Sprache.
  Nur die Titel, die die App übergibt, werden übersetzt.
- Englische und deutsche Texte sind unterschiedlich lang. Buttons, Spalten und Trefferliste müssen in
  beiden Sprachen passen.

### Kommandozeile

- Hilfe, Ausgaben und Fehlermeldungen laufen über `t()`. Neu ist die Option `--lang`.
- Auch die eingebauten Texte von argparse („usage:“, „options:“, „show this help message and exit“) gibt es
  auf Deutsch, damit die Hilfe nicht halb englisch ist.
- Optionsnamen (`--mode`, `--check` …), ihre Werte (`strict`, `normal`, `loose`, Kategorie-IDs) und die
  Rückgabewerte bleiben gleich.

### Kategorien, Modi, Regeln

- Name und Beschreibung der Kategorien und die Gruppennamen aus `core/models.py` kommen über die Schlüssel
  `category.<ID>.label`, `category.<ID>.description` und `group.<id>`.
- Die Modusnamen kommen über `mode.strict` usw.
- Für die mitgelieferten Regeln stehen Name und Beschreibung als `rule.<id>.name` und
  `rule.<id>.description` in den Sprachdateien. `default_rules.json` behält die deutschen Felder als
  Rückfall. So liegen alle Übersetzungen an einem Ort, und der Vollständigkeits-Test deckt sie mit ab.
- Eigene Regeln zeigen ihren Namen so, wie er eingegeben wurde. Ersetzt eine eigene Regel eine
  mitgelieferte (gleiche `id`), gilt der eigene Name.

### Bericht und Ausgabedateien

- Der Bericht erscheint in der aktiven Sprache.
- Er heißt auf Deutsch `secret_sanitizer_bericht.txt` und auf Englisch `secret_sanitizer_report.txt`. Ob
  ein Ordner von einem früheren Lauf stammt, erkennt das Programm an beiden Namen. Ein Sprachwechsel macht
  also keinen Ausgabeordner unbrauchbar, und `--clean` funktioniert weiter.
- Liegt beim Schreiben noch der Bericht der anderen Sprache im Ordner, wird er gelöscht, damit nie ein
  veralteter Bericht neben dem aktuellen steht. Beide Namen sind für Ausgabedateien reserviert, damit eine
  Eingabedatei mit diesem Namen nicht mit dem Bericht kollidiert.
- Der Ordnername `_sanitized` und Endungen wie `.pdf.txt` bleiben gleich.

### Doku

- `README.md` wird Englisch, weil GitHub diese Datei zuerst zeigt. Die bisherige deutsche Fassung zieht nach
  `README.de.md` um. Beide verlinken oben aufeinander.
- Die Beschreibung auf GitHub wird Englisch.

### Tests

- `de.json` und `en.json` haben genau dieselben Schlüssel, keine leeren Texte und in jedem Text dieselben
  `{platzhalter}`.
- Jede mitgelieferte Regel und jede Kategorie hat Name und Beschreibung in beiden Sprachen.
- Ein statischer Scan prüft, dass jeder `t("…")`-Schlüssel im Code auch in den Dateien steht.
- Die bestehenden Tests laufen fest auf Deutsch und prüfen weiter ihre Texte.
- Die CLI-Tests laufen zusätzlich mit `--lang en` für Hilfe, Hinweis und Bericht.
- Der GUI-Smoke-Test läuft in beiden Sprachen.
- Ein alter Ausgabeordner mit `secret_sanitizer_bericht.txt` wird auch auf Englisch erkannt.

### Release

- Version 1.3.0, gebaut wie bisher über `build_exe.bat`, Ergebnis in `dist\`.

## Bewusst offen gelassen

- Die genauen Schlüsselnamen und ihre Aufteilung in Bereiche.
- Ob `t()` die Sprachdatei beim Import oder beim ersten Aufruf lädt.
- Wie genau die argparse-Texte ersetzt werden.
- Die englischen Formulierungen im Detail. Sie sollen natürlich und knapp sein und denselben Ton wie die
  deutschen haben.
- Die Reihenfolge der Umstellung, etwa Datei für Datei mit grünen Tests nach jedem Schritt.
