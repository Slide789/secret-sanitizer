# Secret Sanitizer (`secret_sanitizer`)

[English](README.md)

Wer ein Log, eine Konfiguration, eine Befehlsausgabe oder ein Dokument weitergibt, etwa in ein Ticket, an den
Support, in ein Forum, eine Doku oder einen KI-Chat, gibt dabei oft mehr preis als gedacht: Passwörter,
Tokens, interne Hostnamen, IP-Adressen, Benutzernamen. Secret Sanitizer ist ein Windows-Tool, das solche
Werte vorher findet und durch Platzhalter wie `[PASSWORD_1]`, `[IP_3]` oder `[EMAIL_2]` ersetzt. Oberfläche,
Kommandozeile und Berichte gibt es auf Deutsch und Englisch (siehe [Sprache](#5-sprache)).

Derselbe Wert bekommt dabei immer denselben Platzhalter. Taucht `srv01.corp.local` zehnmal im Log auf, steht
dort zehnmal `[HOSTNAME_1]`. Wer den Text liest, kann also weiterhin nachvollziehen, was zusammengehört, ohne
die echten Daten zu sehen. Eine Antwort mit diesen Platzhaltern lässt sich anschließend im Tool wieder in die
echten Werte zurückübersetzen.

Das Programm selbst läuft unter Windows, kommt aber mit Linux-Material (Logs, Configs, Shell-Ausgaben)
genauso gut zurecht.

> Hinweis: Ergebnisse bitte immer selbst prüfen.

## Inhalt

1. [Installation als .exe](#1-installation-als-exe)
2. [Installation aus dem Quellcode](#2-installation-aus-dem-quellcode)
3. [Die .exe selbst bauen](#3-die-exe-selbst-bauen)
4. [Bedienung der Oberfläche](#4-bedienung-der-oberfläche)
5. [Sprache](#5-sprache)
6. [Kommandozeile](#6-kommandozeile)
7. [Was wird erkannt?](#7-was-wird-erkannt)
8. [Konfiguration und eigene Regeln](#8-konfiguration-und-eigene-regeln)
9. [Sicherheit](#9-sicherheit)
10. [Grenzen und bekannte Einschränkungen](#10-grenzen-und-bekannte-einschränkungen)
11. [Entwicklung und Tests](#11-entwicklung-und-tests)

## 1. Installation als .exe

Die .exe enthält alles, was das Programm braucht. Python muss nicht installiert sein.

1. Die Datei `secret_sanitizer.exe` in einen beliebigen Ordner kopieren, z. B. `C:\Tools\SecretSanitizer\`.
2. Doppelklick auf `secret_sanitizer.exe` startet die Oberfläche.
3. Beim ersten Start zeigt Windows eventuell die Meldung „Der Computer wurde durch Windows geschützt“
   (SmartScreen), weil die Datei nicht digital signiert ist. Klicke auf „Weitere Informationen“ und dann
   auf „Trotzdem ausführen“. In Firmenumgebungen muss die IT die Datei eventuell freigeben.
4. Optional für die Kommandozeile: `secret_sanitizer_cli.exe` daneben legen (siehe [Kommandozeile](#6-kommandozeile)).

Deinstallieren: die .exe-Dateien löschen. Wenn auch die Einstellungen weg sollen, lösch zusätzlich den
Ordner `%APPDATA%\secret_sanitizer` (dazu `%APPDATA%\secret_sanitizer` in die Adresszeile des Explorers eingeben).

## 2. Installation aus dem Quellcode

Voraussetzung: Python 3.10 oder neuer.

1. Python von <https://www.python.org/downloads/windows/> installieren. Im Installer
   „Add python.exe to PATH“ und „tcl/tk and IDLE“ anhaken (Letzteres ist Standard und wird für die
   Oberfläche gebraucht).
2. Eingabeaufforderung (`cmd`) oder PowerShell im Projektordner öffnen, d. h. in dem Ordner, in dem diese
   README liegt.
3. Eine virtuelle Umgebung anlegen und aktivieren:
   ```bat
   python -m venv .venv
   .venv\Scripts\activate
   ```
   (Linux/macOS: `python3 -m venv .venv` und `source .venv/bin/activate`)
4. Abhängigkeiten installieren: `customtkinter` für die Oberfläche, `tkinterdnd2` für Drag & Drop und `pypdf`
   für PDFs. Alle sind fest angepinnt, und `pip` prüft jedes Paket gegen die SHA-256-Prüfsumme in der Datei:
   ```bat
   pip install --require-hashes -r requirements.txt
   ```
5. Starten:
   ```bat
   python -m secret_sanitizer
   ```
   Ohne Argumente startet die Oberfläche, mit Argumenten die Kommandozeile (`python -m secret_sanitizer --help`).

Erkennung, Regeln und Kommandozeile kommen ohne Zusatzpakete aus. Wer nur die Kommandozeile braucht, kann
Schritt 4 überspringen. Ohne `pypdf` werden PDFs übersprungen, ohne `tkinterdnd2` gibt es kein Drag & Drop.
Zur Laufzeit lädt das Programm nie etwas aus dem Internet nach; die Pakete stecken in der .exe.

## 3. Die .exe selbst bauen

Die .exe muss unter Windows gebaut werden. PyInstaller erzeugt immer Programme für das System, auf dem es
läuft. Ein Build unter Linux ergibt keine .exe.

1. Python 3.10+ wie in Abschnitt 2 installieren (Python von python.org verwenden).
2. Im Projektordner ausführen:
   ```bat
   build_exe.bat
   ```
   Das Skript legt eine eigene Build-Umgebung `.venv-build` an, installiert die Pakete aus
   `requirements-build.txt` (nur mit geprüften Prüfsummen, `--require-hashes`), lässt alle Tests laufen und baut
   danach:
   - `dist\secret_sanitizer.exe`: Oberfläche (ohne Konsolenfenster)
   - `dist\secret_sanitizer_cli.exe`: Kommandozeile
3. Danach auf einem sauberen Windows-Rechner ohne Python testen: die .exe starten, Text einfügen, Ordner
   bereinigen.

Manueller Aufruf ohne Skript: `pyinstaller --noconfirm --clean packaging\secret_sanitizer.spec`

Der exe-Name wird aus `APP_NAME` in `secret_sanitizer/config.py` gelesen. Der Programmname steht nur dort.

## 4. Bedienung der Oberfläche

Aufbau des Fensters: oben Modus und Kategorien, darunter der Prüf-Hinweis, in der Mitte links das Original
und rechts die bereinigte Fassung, unten die Trefferliste und der Kopier-Button.

### Oben: Modus und Kategorien

- Modus bestimmt, ab welcher Sicherheit ersetzt wird:
  - Streng (Standard, empfohlen) ersetzt auch Treffer, bei denen sich das Tool nicht sicher ist. Ein
    Platzhalter zu viel schadet weniger als ein übersehenes Passwort.
  - Normal liegt dazwischen.
  - Locker ersetzt nur eindeutige Treffer. Der Text bleibt besser lesbar, es rutscht aber eher etwas durch.
- Kategorien: Jede Kategorie (Passwörter, IP-Adressen, Hostnamen …) lässt sich einzeln an- und abschalten.
  Personenbezogene Daten (E-Mail-Adressen, Personennamen) haben einen eigenen Schalter.
  Mit „Kategorien ▲“ lässt sich der Bereich einklappen.
- Modus und Kategorien werden automatisch gespeichert.

### Reiter „Text & Vorschau“

1. Text in das linke Feld „Originaltext“ einfügen (Strg+V oder „Aus Zwischenablage einfügen“), über
   „Datei öffnen“ eine Textdatei laden oder die Datei einfach ins Fenster ziehen (Drag & Drop).
2. Rechts erscheint sofort die bereinigte Fassung. Die Treffer sind in beiden Feldern farbig nach
   Kategorie markiert.
3. Unten steht die Trefferliste: ein Eintrag pro ersetztem Wert, mit Platzhalter, Kategorie, gekürztem
   Originalwert, Anzahl, erkennendem Verfahren und Konfidenz. Ein Klick auf einen Eintrag markiert die Stellen
   im Text.
4. „Doch nicht ersetzen“ (oder Doppelklick) nimmt einen Wert aus. Das gilt dann für alle Vorkommen
   dieses Werts. Mit „Wieder ersetzen“ wird das rückgängig gemacht. Ausnahmen gelten nur bis zum Schließen und
   werden nicht gespeichert.
   „Immer ignorieren“ übernimmt den markierten Wert nach einer Rückfrage dauerhaft in die Allowlist
   (im Klartext in `user_rules.json`, also nur für Werte, die wirklich kein Geheimnis sind).
5. „Bereinigten Text kopieren“ legt das Ergebnis in die Zwischenablage.
6. War eine Datei geladen, schreibt „Bereinigte Datei speichern“ das Ergebnis in den Ausgabeordner.
   Das Original bleibt unverändert.

Ab 50 000 Zeichen läuft die Analyse im Hintergrund, das Fenster bleibt dabei bedienbar. Sehr große Texte
(mehr als `max_preview_chars` Zeichen, Standard 200 000) zeigt das Tool ohne farbige Vorschau, weil das Textfeld
sonst sehr langsam wird. Stattdessen gibt es eine Zusammenfassung mit Stichproben. Kopieren funktioniert
trotzdem. Ein Archiv (`.zip`, `.gz` …), ein Office-Dokument oder eine PDF, das hier geöffnet oder hineingezogen
wird, wird direkt als Dateilauf bereinigt.

Drag & Drop: Eine Textdatei landet in der Vorschau, ein Ordner im Reiter „Dateien & Ordner“. Zieht man eine
Datei auf den Reiter „Dateien & Ordner“, wird sie dort als Eingabe übernommen. Bitte immer nur ein Element
ablegen (mehrere Dateien am besten in einen Ordner legen).

### Reiter „Dateien & Ordner“

1. „Datei öffnen“ oder „Ordner wählen“ (alle Dateien inklusive Unterordner).
2. Ausgabeordner: leer lassen bedeutet automatisch `<eingabeordner>_sanitized` neben dem Eingabeordner.
   Beispiel: `C:\Logs\Server1` wird zu `C:\Logs\Server1_sanitized`. Bei einer einzelnen Datei
   `C:\Logs\app.log` landet das Ergebnis in `C:\Logs_sanitized\app.log`.
3. „Bereinigen starten“. Die Unterordnerstruktur bleibt erhalten, die Originale werden nie verändert.
4. Danach erscheint der Bericht: bearbeitete, übersprungene (z. B. Binärdateien) und fehlgeschlagene Dateien
   mit Anzahl der Ersetzungen pro Kategorie, ohne Originalwerte. Der Bericht wird auch als
   `secret_sanitizer_bericht.txt` (bei englischer Sprache `secret_sanitizer_report.txt`) in den Ausgabeordner
   geschrieben.
5. Dateien über `max_file_size_mb` (Standard 100 MB) lösen eine Rückfrage aus.
6. Ausschlussmuster: Ordner wie `.git`, `node_modules`, `__pycache__`, `.venv` und frühere
   `*_sanitized`-Ausgaben werden übersprungen und im Bericht aufgeführt (änderbar im Reiter „Einstellungen“).
7. „Ausgabeordner vorher leeren“ entfernt Ergebnisse früherer Läufe. Das passiert nur, wenn der Ordner leer
   ist oder einen Bericht dieses Programms enthält (deutsch oder englisch). Einen fremden Ordner leert das
   Tool nie. Ohne das Häkchen warnt der Bericht vor veralteten Dateien aus früheren Läufen, weil deren
   Platzhalter-Nummern nicht zum aktuellen Lauf passen.
8. „Dateinamen bereinigen“ ersetzt auch in Ordner- und Dateinamen, z. B.
   `backup_srv01.corp.local.log` → `backup_[HOSTNAME_1].log`. Der Bericht zeigt dann nur die bereinigten Namen.
9. Archive (`.zip`, `.tar`, `.tar.gz`/`.tgz`, `.gz`) werden entpackt, bereinigt und wieder eingepackt
   (Häkchen „Archive (.zip, .gz, .tar) bereinigen“, Standard an). Binäre oder verschlüsselte Einträge fehlen
   im neuen Archiv und stehen im Bericht.
10. Word, Excel, PowerPoint (`.docx`, `.xlsx`, `.pptx`) werden direkt bereinigt, Layout und Formatierung
    bleiben erhalten. Bereinigt werden Texte, Tabellen, Kopf-/Fußzeilen, Fußnoten, Textfelder, Zellen, Formeln,
    Folien, Notizen, Diagrammbeschriftungen, Kommentare, Alternativtexte, Link-Ziele und Metadaten. Außerdem:
    - Nachverfolgte Änderungen werden angenommen, sonst steckt gelöschter Text weiter in der Datei.
    - Autorennamen (Dokument, Kommentare, Änderungen) werden geleert.
    - Bilder und eingebettete Objekte werden entfernt, weil das Tool ihren Inhalt nicht prüfen kann (z. B. ein
      Screenshot mit Passwort). Das lässt sich im Reiter „Einstellungen“ abschalten; der Bericht nennt die Anzahl.
    - Dokumente mit Makros (`.docm`, `.xlsm`, `.pptm`) werden übersprungen.
    - Excel: Ein bereinigter Blattname wird zu einem gültigen Namen wie `(HOSTNAME_1)`; Formeln, Druckbereiche
      und Diagramme verweisen auf den neuen Namen.
11. PDFs: Der Text wird gelesen und als bereinigte `<name>.pdf.txt` gespeichert (die PDF selbst wird
    nicht ausgegeben). Gescannte PDFs ohne Text und PDFs mit Kennwort werden übersprungen.
12. Mehrere CPU-Kerne: Ab 4 Dateien und 4 MB werden die Dateien parallel bearbeitet (Einstellung
    „CPU-Kerne“, Standard automatisch). Das Ergebnis ist exakt dasselbe wie mit einem Kern; bei typischen Logs
    ist es etwa 4-mal so schnell (8 Kerne). Der Bericht nennt die Anzahl der Kerne.

Bei einem Ordnerlauf bekommt derselbe Wert in allen Dateien denselben Platzhalter, auch in Archiven,
Office-Dokumenten und PDFs. Die Platzhalter-Nummern laufen über den ganzen Lauf durch.

Textdateien dürfen UTF-8, UTF-16 (z. B. PowerShell-Ausgaben mit `>`), UTF-32, cp1252 oder Latin-1 sein. Die
Kodierung erkennt das Tool selbst, Windows-Zeilenenden (`\r\n`) bleiben erhalten. Die Ausgabe ist
standardmäßig UTF-8.

### Reiter „Antwort zurückübersetzen“

Antworten auf bereinigten Text (vom Support, von Kollegen, von einer KI) enthalten oft dieselben
Platzhalter, etwa „Starte den Dienst auf `[HOSTNAME_1]` neu“. Füge die Antwort links ein, rechts stehen dann
wieder die echten Werte (farbig markiert). Oben wählst du, ob die Platzhalter aus dem Reiter „Text & Vorschau“
oder aus dem letzten Ordnerlauf stammen. Unbekannte Platzhalter meldet das Tool. Das Ganze klappt nur, solange
das Programm offen ist, denn die Zuordnung wird nie gespeichert.

### Reiter „Regeln“

- Eigene Regeln: Name, Beschreibung, Muster (regulärer Ausdruck), Kategorie und Konfidenz eintragen und
  „Regel übernehmen“ klicken. Im Testfeld darunter siehst du beim Tippen sofort, was das Muster findet.
  Tipp: Mit `(?P<value>...)` wird nur ein Teil ersetzt, z. B. `kunde=(?P<value>\w+)` ersetzt nur den
  Kundennamen. Muster mit verschachtelten Wiederholungen wie `(a+)+` können extrem langsam werden; der Editor
  warnt davor und testet sie nicht live.
- Eigene Wortlisten: Kategorie wählen (z. B. Firmennamen, Hostnamen, Benutzernamen, Projektnamen,
  Personennamen) und einen Eintrag pro Zeile eintragen. Diese Wörter werden exakt ersetzt.
- Allowlist: Einträge, die nie ersetzt werden, einer pro Zeile. Mit `re:` am Anfang ist der Eintrag ein
  regulärer Ausdruck.
- „Alle Regeln speichern“ aktiviert die Änderungen.
- Profile (Leiste unten): Mehrere Regelsätze speichern und wechseln, z. B. „Kunde A“ und „Windows-Logs“.
  - Speichern als … legt das aktuelle Profil im Konfigurationsordner ab (mit Wortlisten),
    Laden übernimmt ein gespeichertes Profil.
  - Exportieren … schreibt eine Profildatei zum Weitergeben, z. B. an Kollegen. Die Wortlisten enthalten
    Firmen- und Personennamen im Klartext und werden darum nur auf Nachfrage mitexportiert.
  - Importieren … liest eine Profildatei. Vorher zeigt das Tool, was sich ändert (neue/geänderte Regeln,
    neue Wörter, Allowlist), und fragt: Zusammenführen oder Ersetzen. Ungültige Einträge und
    möglicherweise langsame Muster werden gemeldet und nicht übernommen bzw. markiert.
  - Profile enthalten nur Regeln, Wortlisten, Allowlist sowie Modus und Kategorien, keine Pfade oder
    Befehle.

### Reiter „Einstellungen“

Hier lassen sich alle Werte aus `config.json` bearbeiten: Sprache, Ausgabeordner, Ausgabekodierung, Limits,
Blockgröße, Platzhalterstil, Ausschlussmuster, CPU-Kerne, PDF-Limits, Schwellen der Modi und Entropie-Schwellen.
Häkchen schalten die Verarbeitung von Office-Dokumenten und PDFs sowie das Entfernen von Bildern aus
Office-Dokumenten ein und aus.

Die Sprache (Automatisch, Deutsch oder English) steht ganz oben unter „Allgemein“. Eine Änderung gilt erst nach
einem Neustart der App; das Programm fragt, ob es gleich neu starten soll. Beim Neustart gehen die
Zuordnung für die Rückübersetzung und nicht gespeicherte Eingaben verloren.

## 5. Sprache

Oberfläche, Kommandozeile, Meldungen und Berichte gibt es auf Deutsch und auf Englisch. Die Sprache wird in
dieser Reihenfolge bestimmt, die erste Angabe gewinnt:

1. Kommandozeilen-Option `--lang de` oder `--lang en`
2. Umgebungsvariable `SECRET_SANITIZER_LANG` (`de` oder `en`)
3. Einstellung `language` in der `config.json` (`"auto"`, `"de"` oder `"en"`), in der Oberfläche unter
   „Einstellungen“ → „Allgemein“ → „Sprache“
4. Automatisch: Ist die Sprache von Windows Deutsch, läuft das Programm auf Deutsch, sonst auf Englisch.

Ohne Angabe gilt `"auto"`. Fehlt der Eintrag in einer älteren `config.json` oder steht ein ungültiger Wert
darin, wird ebenfalls `"auto"` verwendet.

Der Bericht im Ausgabeordner heißt auf Deutsch `secret_sanitizer_bericht.txt`, auf Englisch
`secret_sanitizer_report.txt`. Beide werden als Bericht dieses Programms erkannt. Wechselst du die Sprache und
nimmst denselben Ausgabeordner noch einmal, funktioniert „Ausgabeordner vorher leeren“ bzw. `--clean`
weiterhin, und der alte Bericht wird ersetzt.

Platzhalter (`[PASSWORD_1]` …), Kategorie-IDs, Optionsnamen und -werte der Kommandozeile, Rückgabewerte, der
Ordnername `_sanitized` und die Endung `.pdf.txt` sind in beiden Sprachen gleich. Eigene Regeln, Wortlisten
und Profilnamen werden nie übersetzt. Nur der Datei-Dialog von Windows folgt der Windows-Sprache.

## 6. Kommandozeile

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

REM Nur prüfen (nichts schreiben), z. B. vor einem Commit
python -m secret_sanitizer --check src\ config\
```

Wichtige Optionen (alle siehe `--help`):

| Option | Bedeutung |
|---|---|
| `-o ORDNER` | Ausgabeordner |
| `-m strict\|normal\|loose` | Modus |
| `--no-personal` | E-Mail-Adressen und Personennamen nicht ersetzen |
| `--disable KAT,…` / `--enable KAT,…` | Kategorien ab-/anschalten (`--list-categories` zeigt alle) |
| `--output-encoding utf-8\|same\|…` | Kodierung der Ausgabe (`same` = wie Eingabe) |
| `--lang de\|en` | Sprache der Ausgaben (siehe [Sprache](#5-sprache)) |
| `-y` | große Dateien ohne Rückfrage verarbeiten |
| `--check` | nur prüfen, nichts schreiben: listet Dateien mit Treffern (ohne Werte), Rückgabewert `3` bei Treffern |
| `--exclude MUSTER` | zusätzlich überspringen, z. B. `--exclude "*.bak"` (mehrfach möglich) |
| `--no-exclude` | auch die Standard-Ausschlussmuster (`.git`, `node_modules` …) nicht anwenden |
| `--clean` | Ausgabeordner vorher leeren (nur wenn er von einem früheren Lauf stammt) |
| `--sanitize-filenames` | auch Ordner- und Dateinamen bereinigen |
| `--no-archives` | Archive nicht entpacken, sondern wie Binärdateien überspringen |
| `--no-office` / `--keep-office-media` | Office-Dokumente nicht bereinigen / Bilder darin behalten |
| `--no-pdf` | PDFs nicht lesen |
| `--workers N` | CPU-Kerne für Ordnerläufe (Standard automatisch, `1` = nur ein Kern) |
| `--profile NAME\|DATEI` | Regeln (und ggf. Modus/Kategorien) aus einem Profil statt der eigenen Regeln |
| `--export-profile DATEI` | eigene Regeln als Profil exportieren (mit `--with-wordlists` inkl. Wortlisten) |
| `--config DATEI`, `--rules DATEI` | andere config.json / user_rules.json |
| `--no-user-rules` | nur mitgelieferte Regeln |

Hinweis zur Pipe unter Windows: `cmd` gibt Text in der OEM-Codepage (meist cp850) aus. Umlaute können dadurch
in der Ausgabe verfälscht erscheinen, die Erkennung selbst ist davon nicht betroffen. Für saubere Umlaute die
Ausgabe erst in eine Datei schreiben (`ipconfig /all > ip.txt`) und dann die Datei bereinigen.

Rückgabewerte: `0` ok, `1` einzelne Dateien fehlgeschlagen, `2` Bedien- oder Eingabefehler, `3` Treffer
gefunden (nur mit `--check`). Meldungen auf der Konsole enthalten nur Zähler und relative Pfade, keine
Originalwerte.

Beispiel für einen Git-Pre-commit-Hook (`.git/hooks/pre-commit`), der Commits mit Secrets stoppt:

```sh
#!/bin/sh
git diff --cached --name-only --diff-filter=ACM -z | xargs -0 -r secret_sanitizer_cli.exe --check || {
  echo "Möglicherweise Secrets im Commit (siehe oben)."; exit 1; }
```

## 7. Was wird erkannt?

Alle Verfahren laufen parallel. Überlappende Treffer werden zusammengeführt, der Treffer mit der höchsten
Konfidenz gewinnt. Der Modus legt die Mindest-Konfidenz fest.

| Verfahren | Beispiele |
|---|---|
| Bekannte Formate (Regex) | AWS-Keys `AKIA…`, GitHub `ghp_…`, GitLab, Slack, Google, Stripe, OpenAI/Anthropic-Keys, Hugging Face `hf_…`, PyPI `pypi-…`, Discord- und Telegram-Bot-Tokens, JWT, Azure `AccountKey=` und SAS-Signaturen `sig=…`, `user:pass@host` in URLs, E-Mail, IPv4/IPv6 (auch private, aber nicht `Version 1.2.3.4`), MAC, Hostnamen/FQDNs |
| Telefonnummern | `+49 171 2345678`, `+49 (0)30 1234567`, `0171/2345678`, `030 12345678` (Kategorie `PHONE`, personenbezogen) |
| PEM-Blöcke | `-----BEGIN … PRIVATE KEY-----` bis `-----END …-----` als Ganzes, auch abgeschnittene Blöcke; Zertifikate |
| Kontext (key=value) | `password=…`, `"api_key": "…"`, `token: …`, `export DB_PASSWORD=…`, `<password>…</password>`, `Authorization: Bearer …`, Connection-Strings, auch simple Passwörter wie `hunter2`, Passphrasen mit Leerzeichen (`password: correct horse battery`) und YAML-Blockwerte (`password: \|` mit eingerücktem Wert) |
| Kommandozeile | `mysql -pGEHEIM`, `--password=…`, `curl -u user:pass`, `sshpass -p`, `net user name pw`, `/p:…`, PowerShell `-Password …`, `ConvertTo-SecureString "…"` |
| Windows | SIDs `S-1-5-21-…`, `C:\Users\<Name>\…`, `DOMÄNE\benutzer`, UNC `\\server\share`, NTLM-Hashes (pwdump), `HKEY_USERS\<SID>` |
| Linux | `/home/<name>/…`, `/etc/shadow`-Hashes, SSH-Schlüssel, `known_hosts`, Docker-`config.json`, Kubernetes-Secrets (Base64), Shell-Prompts `user@host` |
| Passwort-Hashes | `$6$`, `$5$`, `$1$` (MD5-crypt), bcrypt `$2b$`, yescrypt `$y$`, NTLM |
| Entropie | unbekannte zufällige Zeichenketten (z. B. Keys ohne bekanntes Format); Ausnahmen für Datei-Hashes, GUIDs, Pfade und Bezeichner |
| Prüfsummen | Kreditkarten (Luhn) und IBAN (Modulo 97). Nur gültige Nummern werden ersetzt |
| Eigene Wortlisten | Firmennamen, interne Hostnamen, Domains, Benutzer, Projekte, Personennamen |
| Konsistenz | Ein erkannter Wert wird überall ersetzt, auch URL-codiert, JSON-/HTML-escaped und in anderer Groß-/Kleinschreibung |

Standardmäßig nicht ersetzt (Allowlist): `localhost`, `127.0.0.1`, `0.0.0.0`, `::1`, Netzmasken,
`example.com/.org/.net` sowie symbolische Werte wie `true`, `null`, ``, `${VAR}`.

## 8. Konfiguration und eigene Regeln

Die Einstellungen liegen im Benutzerordner, nicht im Programmordner:

- Windows: `%APPDATA%\secret_sanitizer\config.json` und `user_rules.json`
- Linux/macOS: `~/.config/secret_sanitizer/`
- Abweichender Ordner (z. B. portabel auf einem USB-Stick): Umgebungsvariable `SECRET_SANITIZER_HOME`

`config.json` (alle Werte haben Standards, fehlende oder ungültige Werte werden ignoriert):

| Schlüssel | Standard | Bedeutung |
|---|---|---|
| `mode` | `"strict"` | `strict`, `normal` oder `loose` |
| `language` | `"auto"` | `"auto"`, `"de"` oder `"en"` (siehe [Sprache](#5-sprache)) |
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
| `exclude_patterns` | `.git`, `node_modules`, `*_sanitized` … | Ordner/Dateien im Ordnerlauf überspringen (fnmatch auf Name oder relativen Pfad) |
| `sanitize_filenames` | `false` | auch Ordner- und Dateinamen bereinigen |
| `process_archives` | `true` | `.zip`, `.tar`, `.tar.gz`/`.tgz`, `.gz` entpacken, bereinigen, wieder einpacken |
| `max_archive_mb` | `500` | Obergrenze für den entpackten Inhalt eines Archivs oder Office-Dokuments (Schutz vor Zip-Bomben) |
| `workers` | `0` | CPU-Kerne für Ordnerläufe: `0` = automatisch (Kerne − 1, höchstens 8), `1` = nur ein Kern |
| `process_office` | `true` | `.docx`, `.xlsx`, `.pptx` bereinigen |
| `office_remove_media` | `true` | Bilder und eingebettete Objekte aus Office-Dokumenten entfernen |
| `process_pdf` | `true` | Text aus PDFs als bereinigte `.pdf.txt` ausgeben |
| `pdf_timeout_s` / `pdf_max_memory_mb` | `60` / `1024` | Zeit- und Speicherlimit beim Lesen einer PDF |

Eigene Regeln legst du am einfachsten im Reiter „Regeln“ an. So sieht `user_rules.json` aus:

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

## 9. Sicherheit

- Komplett offline: keine Netzwerkzugriffe, keine Telemetrie, keine Update-Checks, keine Online-Prüfung
  gefundener Keys. Ein Test stellt sicher, dass kein Netzwerkmodul importiert wird.
- Keine Originalwerte in Logs, Berichten oder Fehlermeldungen. Fehlermeldungen nennen nur die Fehlerart
  (z. B. „keine Berechtigung“), nie den Ausnahmetext. Die Trefferliste in der Oberfläche zeigt Werte nur
  gekürzt an.
- Das Mapping (Wert → Platzhalter) liegt nur im Arbeitsspeicher und wird nie gespeichert. Die
  Rückübersetzung von Antworten nutzt genau dieses Mapping und funktioniert deshalb nur, solange das
  Programm geöffnet ist. Beim Schließen wird es verworfen.
- Archive werden in einen Temp-Ordner entpackt, der nach dem Lauf immer gelöscht wird, auch bei Fehlern
  oder Abbruch. Pfade wie `../` im Archiv werden abgelehnt, Größen- und Anzahl-Limits schützen vor Zip-Bomben.
- Office-Dokumente werden auf Textebene bearbeitet, ohne XML-Parser: Es werden keine Entitäten
  expandiert, Dateien mit `DOCTYPE` werden abgelehnt. Bliebe nach dem Entfernen eines Bildes ein Verweis
  darauf übrig, wird lieber gar keine Ausgabe geschrieben als ein beschädigtes Dokument.
- PDFs werden in einem eigenen Prozess gelesen, mit Zeitlimit und hartem Speicherlimit (Windows:
  Job-Objekt). Eine präparierte PDF kann das Programm also weder aufhängen noch den Speicher füllen. Der
  gelesene Text bleibt im Arbeitsspeicher und landet nie in einer Temp-Datei.
- Mehrere CPU-Kerne: Werte wandern nur über interne Pipes zwischen den Prozessen, nie über die Festplatte.
- Profile enthalten nur Daten (keine Pfade, keine Befehle) und werden beim Import streng geprüft.
- Abhängigkeiten sind mit SHA-256-Prüfsummen angepinnt; ein manipuliertes Paket bricht die Installation ab.
- Originaldateien werden nie verändert. Ausgaben landen in einem separaten Ordner. Der Ausgabeordner darf
  nicht der Eingabeordner oder ein übergeordneter Ordner sein. Ausgabedateien werden erst vollständig
  geschrieben und dann umbenannt, halbe Dateien bleiben nicht liegen.
- Der Bericht enthält nur relative Pfade und Zähler (mit „Dateinamen bereinigen“ nur die bereinigten
  Namen).

## 10. Grenzen und bekannte Einschränkungen

- Keine 100-%-Garantie. Vor allem Personennamen im Fließtext, unübliche Passwörter ohne Schlüsselwort und
  firmenspezifische Bezeichnungen werden nur gefunden, wenn sie in einer eigenen Wortliste stehen oder ein
  erkennbares Muster haben. Namenserkennung per KI (NER) ist für Version 2 geplant.
- Dateinamen werden standardmäßig nicht bereinigt. Dafür „Dateinamen bereinigen“ bzw.
  `--sanitize-filenames` einschalten.
- Der Modus Locker lässt bewusst unsichere Treffer stehen, z. B. Benutzernamen aus `DOMÄNE\name` oder
  allgemeine Hostnamen.
- Im Modus Streng werden auch öffentliche Domains wie `github.com` ersetzt. Bei Bedarf in die Allowlist
  aufnehmen.
- Wurde ein Wert einmal erkannt, ersetzt das Tool ihn sicherheitshalber in jeder Groß-/Kleinschreibung,
  auch wenn die Wortliste „Groß/klein ignorieren“ ausgeschaltet hat. Die Option wirkt also nur auf die
  Erkennung.
- Dateien mit gemischten Zeilenenden werden einheitlich mit dem überwiegenden Zeilenende geschrieben.
- Tempo: Bei sehr dichten Logs (mehrere Treffer pro Zeile) schafft das Tool mit einem Kern etwa
  0,2–0,5 MB pro Sekunde, weil jede Datei zweimal gelesen wird (erst lernen, dann ersetzen); mit mehreren Kernen
  entsprechend mehr. Office-Dokumente und PDFs werden immer im Hauptprozess bearbeitet. Der Fortschritt wird
  angezeigt, abbrechen ist möglich.
- Archive in Archiven, alte Office-Formate (`.doc`, `.xls`, `.ppt`), OpenDocument (`.odt` …) und Bilder werden
  nicht verarbeitet. Binärdateien werden übersprungen und im Bericht aufgeführt.
- Office: Bilder werden entfernt, nicht geprüft (keine Texterkennung). Eine Formel, die sich auf einen
  bereinigten Wert verlässt (z. B. ein Passwort als Vergleichswert), rechnet danach mit dem Platzhalter. Ein
  Hinweis wie „Passwort“ in einer Tabellenzelle und der Wert in der Nachbarzelle werden nicht als Paar erkannt
  (nur innerhalb einer Zelle/Zeile, z. B. „Passwort: …“).
- PDF: Keine Texterkennung (OCR) für gescannte PDFs. Die Reihenfolge des Textes folgt der PDF und kann bei
  mehrspaltigem Layout ungewohnt sein.
- Telefonnummern werden nur mit Vorwahl und Trennzeichen erkannt (`030 12345678`), nicht als reine Ziffernfolge.
- Drag & Drop nimmt immer nur ein Element auf einmal an.
- Eigene reguläre Ausdrücke können bei ungeschickter Formulierung sehr langsam sein (z. B. `(a+)+`). Die
  Warnung des Editors ist eine Heuristik und findet die typischen, nicht alle Fälle.
- Die Oberfläche braucht Tk 8.6, wie es die Python-Installer von python.org und die .exe mitbringen. Mit
  Python-Builds, die Tk 9 enthalten, startet customtkinter derzeit nicht (Fehler
  `expected integer but got ""`).

## 11. Entwicklung und Tests

```bat
python -m unittest discover -s tests -t .
```

- Die Tests verwenden ausschließlich erfundene Daten aus `tests/fake_secrets/`. Erzeugt werden sie mit
  `python tests/fake_data.py`, darunter UTF-16-, cp1252-, CRLF- und Binärdateien.
- Geprüft werden Treffer, Fehlalarme (Hashes, GUIDs, Pfade, Zahlen, Ports), dass Berichte und Fehlermeldungen
  keine Originalwerte enthalten, dass derselbe Wert in mehreren Schreibweisen überall ersetzt wird, die
  blockweise Verarbeitung großer Dateien und die Kommandozeile.
- Office- und PDF-Tests bauen ihre Testdokumente selbst (minimales OOXML bzw. PDF). Dass bereinigte Dateien in
  Word, Excel und PowerPoint ohne Reparatur öffnen, wurde zusätzlich mit echten, von Office erzeugten Dateien
  geprüft. Die PDF-Tests brauchen `pypdf`.
- Sprachtests prüfen, dass `de.json` und `en.json` dieselben Schlüssel und Platzhalter enthalten und dass
  Bericht, Meldungen und Kommandozeile in beiden Sprachen funktionieren.
- Mehrkern-Tests vergleichen das Ergebnis byte-genau mit einem Lauf mit einem Kern.
- GUI-Smoke-Test (braucht ein Display und customtkinter, für Drag & Drop tkinterdnd2):
  `python tests/gui_smoke.py`
- Auf GitHub laufen die Tests bei jedem Push automatisch unter Windows und Linux mit Python 3.10 und 3.13
  (`.github/workflows/tests.yml`).

Projektstruktur:

```
secret_sanitizer/
├── __main__.py          Einstieg: GUI oder CLI
├── cli.py               Kommandozeile
├── config.py            APP_NAME, Einstellungen laden/speichern
├── i18n.py              Sprachwahl und Texte (t())
├── locales/             de.json, en.json (alle Texte der Oberfläche, Kommandozeile und Berichte)
├── core/                pipeline, models, rules, merger, replacer, encoding, files, archives,
│                        office, pdf, parallel (mehrere Kerne), profiles
├── detectors/           regex, context (+ Kommandozeile), wordlist, entropy, validators
├── rules/               default_rules.json, user_rules.json (Vorlage)
└── gui/                 app, widgets, rule_editor
packaging/               PyInstaller-Spec und Startskripte
tests/                   Tests und fake_secrets/
build_exe.bat            Build der .exe unter Windows
```

Lizenz: [MIT](LICENSE)
