# Secret Sanitizer (`secret_sanitizer`)

Ein Windows-Tool, das Texte, Logs, Konfigurationen und Befehlsausgaben **vor dem Senden an eine KI bereinigt**.
Passwörter, Tokens, Schlüssel, IP-Adressen, Hostnamen, Benutzernamen, E-Mail-Adressen usw. werden erkannt und
durch **konsistente Platzhalter** ersetzt, z. B. `[PASSWORD_1]`, `[IP_3]`, `[EMAIL_2]`. Derselbe Wert bekommt
immer denselben Platzhalter. So versteht die KI den Zusammenhang, sieht aber keine echten Daten.

Das Tool läuft unter Windows, verarbeitet aber genauso **Linux-Material** (Logs, Configs, Shell-Ausgaben).

> ### ⚠ Wichtiger Hinweis
> Das Tool **senkt das Risiko deutlich, bietet aber keine 100-%-Garantie**, dass alle sensiblen Daten gefunden
> werden. Prüfe das Ergebnis **immer selbst**, bevor du es an eine KI sendest, und beachte die internen
> Richtlinien deines Unternehmens zur KI-Nutzung.

---

## Inhalt

1. [Installation als .exe](#1-installation-als-exe)
2. [Installation aus dem Quellcode](#2-installation-aus-dem-quellcode)
3. [Die .exe selbst bauen](#3-die-exe-selbst-bauen)
4. [Bedienung der Oberfläche](#4-bedienung-der-oberfläche)
5. [Kommandozeile](#5-kommandozeile)
6. [Was wird erkannt?](#6-was-wird-erkannt)
7. [Konfiguration und eigene Regeln](#7-konfiguration-und-eigene-regeln)
8. [Sicherheit](#8-sicherheit)
9. [Grenzen und bekannte Einschränkungen](#9-grenzen-und-bekannte-einschränkungen)
10. [Entwicklung und Tests](#10-entwicklung-und-tests)

---

## 1. Installation als .exe

Die .exe enthält alles, was das Programm braucht. Python muss **nicht** installiert sein.

1. Die Datei `secret_sanitizer.exe` in einen beliebigen Ordner kopieren, z. B. `C:\Tools\SecretSanitizer\`.
2. Doppelklick auf `secret_sanitizer.exe` startet die Oberfläche.
3. Beim ersten Start zeigt Windows eventuell die Meldung **„Der Computer wurde durch Windows geschützt“**
   (SmartScreen), weil die Datei nicht digital signiert ist. Klicke auf **„Weitere Informationen“** und dann
   auf **„Trotzdem ausführen“**. In Firmenumgebungen muss die IT die Datei eventuell freigeben.
4. Optional für die Kommandozeile: `secret_sanitizer_cli.exe` daneben legen (siehe [Kommandozeile](#5-kommandozeile)).

Deinstallieren: die .exe-Dateien löschen. Wenn du auch die Einstellungen entfernen willst, lösche zusätzlich den
Ordner `%APPDATA%\secret_sanitizer` (dazu `%APPDATA%\secret_sanitizer` in die Adresszeile des Explorers eingeben).

## 2. Installation aus dem Quellcode

Voraussetzung: **Python 3.10 oder neuer**.

1. Python von <https://www.python.org/downloads/windows/> installieren. Im Installer
   **„Add python.exe to PATH“** und **„tcl/tk and IDLE“** anhaken (Letzteres ist Standard und wird für die
   Oberfläche gebraucht).
2. Eingabeaufforderung (`cmd`) oder PowerShell im Projektordner öffnen, d. h. in dem Ordner, in dem diese
   README liegt.
3. Eine virtuelle Umgebung anlegen und aktivieren:
   ```bat
   python -m venv .venv
   .venv\Scripts\activate
   ```
   (Linux/macOS: `python3 -m venv .venv` und `source .venv/bin/activate`)
4. Abhängigkeiten installieren. Das ist nur `customtkinter`, und nur die Oberfläche braucht es:
   ```bat
   pip install -r requirements.txt
   ```
5. Starten:
   ```bat
   python -m secret_sanitizer
   ```
   Ohne Argumente startet die Oberfläche, mit Argumenten die Kommandozeile (`python -m secret_sanitizer --help`).

Erkennung, Regeln und Kommandozeile kommen **ohne Zusatzpakete** aus. Für reine Kommandozeilen-Nutzung kannst du
Schritt 4 also überspringen.

## 3. Die .exe selbst bauen

Die .exe muss **unter Windows** gebaut werden. PyInstaller erzeugt immer Programme für das System, auf dem es
läuft. Ein Build unter Linux ergibt keine .exe.

1. Python 3.10+ wie in Abschnitt 2 installieren (Python von python.org verwenden).
2. Im Projektordner ausführen:
   ```bat
   build_exe.bat
   ```
   Das Skript legt eine eigene Build-Umgebung `.venv-build` an, installiert `customtkinter` und `pyinstaller`,
   lässt alle Tests laufen und baut danach:
   - `dist\secret_sanitizer.exe`: Oberfläche (ohne Konsolenfenster)
   - `dist\secret_sanitizer_cli.exe`: Kommandozeile
3. Danach auf einem **sauberen Windows-Rechner ohne Python** testen: die .exe starten, Text einfügen, Ordner
   bereinigen.

Manueller Aufruf ohne Skript: `pyinstaller --noconfirm --clean packaging\secret_sanitizer.spec`

Der exe-Name wird aus `APP_NAME` in `secret_sanitizer/config.py` gelesen. Der Programmname steht nur dort.

## 4. Bedienung der Oberfläche

Aufbau des Fensters: oben Modus und Kategorien, darunter der Prüf-Hinweis, in der Mitte links das Original
und rechts die bereinigte Fassung, unten die Trefferliste und der Kopier-Button.

### Oben: Modus und Kategorien

- **Modus** bestimmt, ab welcher Sicherheit ersetzt wird:
  - **Streng** (Standard, empfohlen): ersetzt auch unsichere Treffer. Lieber ein Platzhalter zu viel.
  - **Normal**: ausgewogen.
  - **Locker**: nur sichere Treffer. Besser lesbar, aber **riskanter**.
- **Kategorien**: Jede Kategorie (Passwörter, IP-Adressen, Hostnamen …) lässt sich einzeln an- und abschalten.
  **Personenbezogene Daten** (E-Mail-Adressen, Personennamen) haben einen eigenen Schalter.
  Mit „Kategorien ▲“ lässt sich der Bereich einklappen.
- Modus und Kategorien werden automatisch gespeichert.

### Reiter „Text & Vorschau“

1. Text in das linke Feld **„Original“** einfügen (Strg+V oder „Aus Zwischenablage einfügen“) oder über
   **„Datei öffnen“** eine Textdatei laden.
2. Rechts erscheint sofort die **bereinigte Fassung**. Die Treffer sind in beiden Feldern **farbig nach
   Kategorie** markiert.
3. Unten steht die **Trefferliste**: ein Eintrag pro ersetztem Wert, mit Platzhalter, Kategorie, gekürztem
   Originalwert, Anzahl, erkennendem Verfahren und Konfidenz. Ein Klick auf einen Eintrag markiert die Stellen
   im Text.
4. **„Doch nicht ersetzen“** (oder Doppelklick) nimmt einen Wert aus. Das gilt dann für **alle** Vorkommen
   dieses Werts. Mit „Wieder ersetzen“ wird das rückgängig gemacht. Ausnahmen gelten nur bis zum Schließen und
   werden nicht gespeichert. Dauerhafte Ausnahmen gehören in die Allowlist.
5. **„Bereinigten Text kopieren“** legt das Ergebnis in die Zwischenablage. Ergebnis prüfen und dann in die KI
   einfügen.
6. War eine Datei geladen, schreibt **„Bereinigte Datei speichern“** das Ergebnis in den Ausgabeordner.
   Das Original bleibt unverändert.

Sehr große Texte (mehr als `max_preview_chars` Zeichen, Standard 200 000) zeigt das Tool ohne farbige Vorschau,
weil das Textfeld sonst sehr langsam wird. Stattdessen gibt es eine Zusammenfassung mit Stichproben. Kopieren
funktioniert trotzdem.

### Reiter „Dateien & Ordner“

1. **„Datei öffnen“** oder **„Ordner wählen“** (alle Dateien inklusive Unterordner).
2. **Ausgabeordner**: leer lassen bedeutet automatisch `<eingabeordner>_sanitized` neben dem Eingabeordner.
   Beispiel: `C:\Logs\Server1` wird zu `C:\Logs\Server1_sanitized`. Bei einer einzelnen Datei
   `C:\Logs\app.log` landet das Ergebnis in `C:\Logs_sanitized\app.log`.
3. **„Bereinigen starten“**. Die Unterordnerstruktur bleibt erhalten, die **Originale werden nie verändert**.
4. Danach erscheint der **Bericht**: bearbeitete, übersprungene (z. B. Binärdateien) und fehlgeschlagene Dateien
   mit Anzahl der Ersetzungen pro Kategorie, **ohne Originalwerte**. Der Bericht wird auch als
   `secret_sanitizer_bericht.txt` in den Ausgabeordner geschrieben.
5. Dateien über `max_file_size_mb` (Standard 100 MB) lösen eine Rückfrage aus.

Bei einem Ordnerlauf bekommt derselbe Wert **in allen Dateien denselben Platzhalter**. Die Platzhalter-Nummern
sind über den ganzen Lauf fortlaufend.

Unterstützt werden Textdateien in UTF-8, UTF-16 (z. B. PowerShell-Ausgaben mit `>`), UTF-32, cp1252 und Latin-1.
Die Kodierung wird automatisch erkannt. Windows-Zeilenenden (`\r\n`) bleiben erhalten. Die Ausgabe ist
standardmäßig UTF-8.

### Reiter „Regeln“

- **Eigene Regeln**: Name, Beschreibung, Muster (regulärer Ausdruck), Kategorie und Konfidenz eintragen und
  „Regel übernehmen“ klicken. Im **Testfeld** darunter siehst du beim Tippen sofort, was das Muster findet.
  Tipp: Mit `(?P<value>...)` wird nur ein Teil ersetzt, z. B. `kunde=(?P<value>\w+)` ersetzt nur den
  Kundennamen.
- **Eigene Wortlisten**: Kategorie wählen (z. B. Firmennamen, Hostnamen, Benutzernamen, Projektnamen,
  Personennamen) und einen Eintrag pro Zeile eintragen. Diese Wörter werden exakt ersetzt.
- **Allowlist**: Einträge, die **nie** ersetzt werden, einer pro Zeile. Mit `re:` am Anfang ist der Eintrag ein
  regulärer Ausdruck.
- **„Alle Regeln speichern“** aktiviert die Änderungen.

### Reiter „Einstellungen“

Hier lassen sich alle Werte aus `config.json` bearbeiten: Ausgabeordner, Ausgabekodierung, Limits,
Blockgröße, Platzhalterstil, Schwellen der Modi und Entropie-Schwellen.

## 5. Kommandozeile

Aus dem Quellcode mit `python -m secret_sanitizer …`, mit der .exe als `secret_sanitizer_cli.exe …`.

```bat
REM Ordner bereinigen -> logs_sanitized\
python -m secret_sanitizer C:\Logs\logs

REM Datei in einen bestimmten Ausgabeordner
python -m secret_sanitizer app.log -o C:\Temp\bereinigt

REM Über die Pipe (stdin -> stdout), z. B. Befehlsausgabe direkt bereinigen
ipconfig /all | python -m secret_sanitizer - > ipconfig_bereinigt.txt

REM Modus, Kategorien
python -m secret_sanitizer --mode normal --no-personal --disable HOSTNAME,IP datei.txt
```

Wichtige Optionen (alle siehe `--help`):

| Option | Bedeutung |
|---|---|
| `-o ORDNER` | Ausgabeordner |
| `-m strict\|normal\|loose` | Modus |
| `--no-personal` | E-Mail-Adressen und Personennamen nicht ersetzen |
| `--disable KAT,…` / `--enable KAT,…` | Kategorien ab-/anschalten (`--list-categories` zeigt alle) |
| `--output-encoding utf-8\|same\|…` | Kodierung der Ausgabe (`same` = wie Eingabe) |
| `-y` | große Dateien ohne Rückfrage verarbeiten |
| `--config DATEI`, `--rules DATEI` | andere config.json / user_rules.json |
| `--no-user-rules` | nur mitgelieferte Regeln |

Hinweis zur Pipe unter Windows: `cmd` gibt Text in der OEM-Codepage (meist cp850) aus. Umlaute können dadurch
in der Ausgabe verfälscht erscheinen, die Erkennung selbst ist davon nicht betroffen. Für saubere Umlaute die
Ausgabe erst in eine Datei schreiben (`ipconfig /all > ip.txt`) und dann die Datei bereinigen.

Rückgabewerte: `0` ok, `1` einzelne Dateien fehlgeschlagen, `2` Bedien- oder Eingabefehler.
Meldungen auf der Konsole enthalten nur Zähler und relative Pfade, keine Originalwerte.

## 6. Was wird erkannt?

Alle Verfahren laufen parallel. Überlappende Treffer werden zusammengeführt, der Treffer mit der höchsten
Konfidenz gewinnt. Der Modus legt die Mindest-Konfidenz fest.

| Verfahren | Beispiele |
|---|---|
| **Bekannte Formate (Regex)** | AWS-Keys `AKIA…`, GitHub `ghp_…`, GitLab, Slack, Google, Stripe, OpenAI/Anthropic-Keys, JWT, Azure `AccountKey=`, `user:pass@host` in URLs, E-Mail, IPv4/IPv6 (auch private), MAC, Hostnamen/FQDNs |
| **PEM-Blöcke** | `-----BEGIN … PRIVATE KEY-----` bis `-----END …-----` als Ganzes, auch abgeschnittene Blöcke; Zertifikate |
| **Kontext (key=value)** | `password=…`, `"api_key": "…"`, `token: …`, `export DB_PASSWORD=…`, `<password>…</password>`, `Authorization: Bearer …`, Connection-Strings, auch simple Passwörter wie `hunter2` |
| **Kommandozeile** | `mysql -pGEHEIM`, `--password=…`, `curl -u user:pass`, `sshpass -p`, `net user name pw`, `/p:…`, PowerShell `-Password …`, `ConvertTo-SecureString "…"` |
| **Windows** | SIDs `S-1-5-21-…`, `C:\Users\<Name>\…`, `DOMÄNE\benutzer`, UNC `\\server\share`, NTLM-Hashes (pwdump), `HKEY_USERS\<SID>` |
| **Linux** | `/home/<name>/…`, `/etc/shadow`-Hashes, SSH-Schlüssel, `known_hosts`, Docker-`config.json`, Kubernetes-Secrets (Base64), Shell-Prompts `user@host` |
| **Passwort-Hashes** | `$6$`, `$5$`, `$1$` (MD5-crypt), bcrypt `$2b$`, yescrypt `$y$`, NTLM |
| **Entropie** | unbekannte zufällige Zeichenketten (z. B. Keys ohne bekanntes Format); Ausnahmen für Datei-Hashes, GUIDs, Pfade und Bezeichner |
| **Prüfsummen** | Kreditkarten (Luhn) und IBAN (Modulo 97). Nur gültige Nummern werden ersetzt |
| **Eigene Wortlisten** | Firmennamen, interne Hostnamen, Domains, Benutzer, Projekte, Personennamen |
| **Konsistenz** | Ein erkannter Wert wird überall ersetzt, auch URL-codiert, JSON-/HTML-escaped und in anderer Groß-/Kleinschreibung |

Standardmäßig **nicht** ersetzt (Allowlist): `localhost`, `127.0.0.1`, `0.0.0.0`, `::1`, Netzmasken,
`example.com/.org/.net` sowie symbolische Werte wie `true`, `null`, `********`, `${VAR}`.

## 7. Konfiguration und eigene Regeln

Die Einstellungen liegen im Benutzerordner, nicht im Programmordner:

- Windows: `%APPDATA%\secret_sanitizer\config.json` und `user_rules.json`
- Linux/macOS: `~/.config/secret_sanitizer/`
- Abweichender Ordner (z. B. portabel auf einem USB-Stick): Umgebungsvariable `SECRET_SANITIZER_HOME`

`config.json` (alle Werte haben Standards, fehlende oder ungültige Werte werden ignoriert):

| Schlüssel | Standard | Bedeutung |
|---|---|---|
| `mode` | `"strict"` | `strict`, `normal` oder `loose` |
| `enabled_categories` | alle an | z. B. `{"EMAIL": false}` |
| `output_dir` | `""` | leer = `<eingabeordner>_sanitized` |
| `output_encoding` | `"utf-8"` | oder z. B. `"utf-16"`, `"same"` |
| `max_file_size_mb` | `100` | darüber Rückfrage |
| `max_files_per_run` | `10000` | Obergrenze pro Lauf |
| `max_preview_chars` | `200000` | darüber keine farbige Vorschau |
| `chunk_size` / `chunk_overlap` | `1000000` / `65536` | Blockgröße und Überlappung für große Dateien (Zeichen) |
| `entropy_thresholds` | je Modus | Entropie-Schwellen für `hex`, `base64`, `mixed` |
| `entropy_min_length` | 16 / 20 / 24 | Mindestlänge je Modus |
| `mode_thresholds` | 0.3 / 0.5 / 0.75 | Mindest-Konfidenz je Modus |
| `placeholder_style` | `"[{CATEGORY}_{N}]"` | muss `{CATEGORY}` und `{N}` enthalten |

Eigene Regeln am besten in der Oberfläche anlegen (Reiter „Regeln“). Das Format von `user_rules.json`:

```json
{
  "rules": [
    {"id": "ticket", "name": "Ticketnummer", "description": "Interne Tickets",
     "category": "CUSTOM", "pattern": "TICKET-\\d{4,}", "confidence": 0.9,
     "flags": ["IGNORECASE"], "enabled": true}
  ],
  "wordlists": [
    {"id": "firma", "name": "Firma", "description": "Unsere Namen", "category": "COMPANY",
     "words": ["Muster GmbH", "MusterCorp"], "ignore_case": true, "enabled": true}
  ],
  "allowlist": [
    {"value": "10.0.0.1", "regex": false, "description": "Öffentlich bekanntes Gateway"}
  ]
}
```

Eine eigene Regel mit derselben `id` wie eine mitgelieferte Regel (siehe
`secret_sanitizer/rules/default_rules.json`) ersetzt diese. So lässt sich z. B. mit `"enabled": false` eine
Standardregel abschalten.

## 8. Sicherheit

- **Komplett offline**: keine Netzwerkzugriffe, keine Telemetrie, keine Update-Checks, keine Online-Prüfung
  gefundener Keys. Ein Test stellt sicher, dass kein Netzwerkmodul importiert wird.
- **Keine Originalwerte in Logs, Berichten oder Fehlermeldungen.** Fehlermeldungen nennen nur die Fehlerart
  (z. B. „keine Berechtigung“), nie den Ausnahmetext. Die Trefferliste in der Oberfläche zeigt Werte nur
  gekürzt an.
- **Das Mapping (Wert → Platzhalter) liegt nur im Arbeitsspeicher** und wird nie gespeichert. Eine
  Rückübersetzung gibt es in Version 1 bewusst nicht.
- **Originaldateien werden nie verändert.** Ausgaben landen in einem separaten Ordner. Der Ausgabeordner darf
  nicht der Eingabeordner oder ein übergeordneter Ordner sein. Ausgabedateien werden erst vollständig
  geschrieben und dann umbenannt, halbe Dateien bleiben nicht liegen.
- Der Bericht enthält nur **relative Pfade** und Zähler.

## 9. Grenzen und bekannte Einschränkungen

- **Keine 100-%-Garantie.** Vor allem Personennamen im Fließtext, unübliche Passwörter ohne Schlüsselwort und
  firmenspezifische Bezeichnungen werden nur gefunden, wenn sie in einer **eigenen Wortliste** stehen oder ein
  erkennbares Muster haben. Namenserkennung per KI (NER) ist erst für Version 2 geplant.
- **Dateinamen werden nicht bereinigt.** Dateinamen im Ausgabeordner und im Bericht bleiben wie im Original.
  Sensible Dateinamen vorher umbenennen.
- Der Modus **Locker** lässt bewusst unsichere Treffer stehen, z. B. Benutzernamen aus `DOMÄNE\name` oder
  allgemeine Hostnamen.
- Im Modus Streng werden auch öffentliche Domains wie `github.com` ersetzt. Bei Bedarf in die Allowlist
  aufnehmen.
- Wurde ein Wert einmal erkannt, ersetzt das Tool ihn sicherheitshalber in **jeder** Groß-/Kleinschreibung,
  auch wenn die Wortliste „Groß/klein ignorieren“ ausgeschaltet hat. Die Option wirkt also nur auf die
  Erkennung.
- Dateien mit **gemischten** Zeilenenden werden einheitlich mit dem überwiegenden Zeilenende geschrieben.
- **Tempo**: Bei sehr dichten Logs (mehrere Treffer pro Zeile) schafft das Tool etwa 0,2–0,5 MB pro Sekunde,
  weil jede Datei zweimal gelesen wird (erst lernen, dann ersetzen). Große Ordner brauchen also etwas Zeit.
  Der Fortschritt wird angezeigt, abbrechen ist möglich.
- Archive (`.zip`, `.gz`), Office-Dateien und PDFs werden in Version 1 **nicht** verarbeitet. Binärdateien
  werden übersprungen und im Bericht aufgeführt.
- Drag-and-Drop ist für eine spätere Version geplant.
- Eigene reguläre Ausdrücke können bei ungeschickter Formulierung sehr langsam sein (z. B. `(a+)+`).
- Die Oberfläche braucht Tk 8.6, wie es die Python-Installer von python.org und die .exe mitbringen. Mit
  Python-Builds, die Tk 9 enthalten, startet customtkinter derzeit nicht (Fehler
  `expected integer but got ""`).

## 10. Entwicklung und Tests

```bat
python -m unittest discover -s tests -t .
```

- Die Tests verwenden **ausschließlich erfundene Daten** aus `tests/fake_secrets/`. Erzeugt werden sie mit
  `python tests/fake_data.py`, darunter UTF-16-, cp1252-, CRLF- und Binärdateien.
- Geprüft werden Treffer, Fehlalarme (Hashes, GUIDs, Pfade, Zahlen, Ports), dass Berichte und Fehlermeldungen
  keine Originalwerte enthalten, dass derselbe Wert in mehreren Schreibweisen überall ersetzt wird, die
  blockweise Verarbeitung großer Dateien und die Kommandozeile.
- GUI-Smoke-Test (braucht ein Display und customtkinter): `python tests/gui_smoke.py`

Projektstruktur:

```
secret_sanitizer/
├── __main__.py          Einstieg: GUI oder CLI
├── cli.py               Kommandozeile
├── config.py            APP_NAME, Einstellungen laden/speichern
├── core/                pipeline, models, rules, merger, replacer, encoding, files
├── detectors/           regex, context (+ Kommandozeile), wordlist, entropy, validators
├── rules/               default_rules.json, user_rules.json (Vorlage)
└── gui/                 app, widgets, rule_editor
packaging/               PyInstaller-Spec und Startskripte
tests/                   Tests und fake_secrets/
build_exe.bat            Build der .exe unter Windows
```

Lizenz: noch offen (siehe Projektplan, offene Punkte).
