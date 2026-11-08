# Secret Sanitizer (`secret_sanitizer`)

[Deutsch](README.de.md)

When you paste a log, a config file, command output or a document into a ticket, a support request, a forum
post, some documentation or an AI chat, you often give away more than you meant to: passwords, tokens,
internal hostnames, IP addresses, usernames. Secret Sanitizer is a Windows tool that finds these values
before you share the text and replaces them with placeholders like `[PASSWORD_1]`, `[IP_3]` or `[EMAIL_2]`.
The GUI, the command line and the reports come in English and German (see [Language](#5-language)).

The same value always gets the same placeholder. If `srv01.corp.local` shows up ten times in a log, the
sanitized log says `[HOSTNAME_1]` ten times. Whoever reads it can still tell what belongs together without
seeing the real data. When a reply comes back using those placeholders, the tool can turn it back into the
real values.

The program itself runs on Windows, but it handles Linux material (logs, configs, shell output) just as well.

> Note: Always check the results yourself.

## Contents

1. [Installation as .exe](#1-installation-as-exe)
2. [Installation from source](#2-installation-from-source)
3. [Building the .exe yourself](#3-building-the-exe-yourself)
4. [Using the GUI](#4-using-the-gui)
5. [Language](#5-language)
6. [Command line](#6-command-line)
7. [What is detected?](#7-what-is-detected)
8. [Configuration and custom rules](#8-configuration-and-custom-rules)
9. [Security](#9-security)
10. [Limits and known restrictions](#10-limits-and-known-restrictions)
11. [Development and tests](#11-development-and-tests)

## 1. Installation as .exe

The .exe contains everything the program needs. Python does not have to be installed.

1. Copy the file `secret_sanitizer.exe` to any folder, e.g. `C:\Tools\SecretSanitizer\`.
2. Double-click `secret_sanitizer.exe` to start the GUI.
3. On the first start, Windows may show the message "Windows protected your PC" (SmartScreen) because the file
   is not digitally signed. Click "More info" and then "Run anyway". In company environments, IT may have to
   allow the file.
4. Optional for the command line: put `secret_sanitizer_cli.exe` next to it (see [Command line](#6-command-line)).

Uninstall: delete the .exe files. If you also want to remove the settings, additionally delete the folder
`%APPDATA%\secret_sanitizer` (enter `%APPDATA%\secret_sanitizer` in the Explorer address bar to get there).

## 2. Installation from source

Requirement: Python 3.10 or newer.

1. Install Python from <https://www.python.org/downloads/windows/>. In the installer, tick
   "Add python.exe to PATH" and "tcl/tk and IDLE" (the latter is the default and is needed for the GUI).
2. Open a command prompt (`cmd`) or PowerShell in the project folder, i.e. the folder that contains this
   README.
3. Create and activate a virtual environment:
   ```bat
   python -m venv .venv
   .venv\Scripts\activate
   ```
   (Linux/macOS: `python3 -m venv .venv` and `source .venv/bin/activate`)
4. Install the dependencies: `customtkinter` for the GUI, `tkinterdnd2` for drag & drop and `pypdf` for PDFs.
   All of them are pinned, and `pip` checks every package against the SHA-256 checksum in the file:
   ```bat
   pip install --require-hashes -r requirements.txt
   ```
5. Start:
   ```bat
   python -m secret_sanitizer
   ```
   Without arguments the GUI starts, with arguments the command line (`python -m secret_sanitizer --help`).

Detection, rules and the command line work without extra packages. For command-line use only, you can
therefore skip step 4. Without `pypdf`, PDFs are skipped; without `tkinterdnd2` there is no drag & drop. At
runtime the program never downloads anything from the internet; the packages are inside the .exe.

## 3. Building the .exe yourself

The .exe has to be built on Windows. PyInstaller always produces programs for the system it runs on. A build
on Linux does not give you an .exe.

1. Install Python 3.10+ as described in section 2 (use Python from python.org).
2. Run this in the project folder:
   ```bat
   build_exe.bat
   ```
   The script creates its own build environment `.venv-build`, installs the packages from
   `requirements-build.txt` (only with verified checksums, `--require-hashes`), runs all tests and then builds:
   - `dist\secret_sanitizer.exe`: GUI (no console window)
   - `dist\secret_sanitizer_cli.exe`: command line
3. Then test on a clean Windows machine without Python: start the .exe, paste text, sanitize a folder.

Manual call without the script: `pyinstaller --noconfirm --clean packaging\secret_sanitizer.spec`

The exe name is read from `APP_NAME` in `secret_sanitizer/config.py`. The program name is defined only there.

## 4. Using the GUI

Window layout: mode and categories at the top, below them the check reminder, in the middle the original on
the left and the sanitized version on the right, at the bottom the list of findings and the copy button.

### Top: mode and categories

- Mode determines how certain a match must be before it is replaced:
  - Strict (default, recommended) also replaces matches the tool is not sure about. One placeholder too many
    does less harm than a missed password.
  - Normal sits in between.
  - Loose replaces only clear matches. The text stays more readable, but something is more likely to slip
    through.
- Categories: Every category (passwords, IP addresses, hostnames …) can be switched on and off individually.
  Personal data (email addresses, personal names) has its own switch.
  "Categories ▲" collapses the area.
- Mode and categories are saved automatically.

### Tab "Text & preview"

1. Paste text into the left field "Original text" (Ctrl+V or "Paste from clipboard"), load a text file with
   "Open file", or simply drag the file into the window (drag & drop).
2. The sanitized version appears on the right immediately. Matches are highlighted in color by category in both
   fields.
3. At the bottom is the list of findings: one entry per replaced value, with placeholder, category, shortened
   original value, count, detection method and confidence. Clicking an entry highlights the places in the
   text.
4. "Don't replace" (or a double-click) excludes a value. This then applies to all occurrences of that value.
   "Replace again" undoes it. Exceptions only last until you close the program and are not saved.
   "Always ignore" adds the selected value to the allowlist permanently after a confirmation
   (in plain text in `user_rules.json`, so only for values that are really not secret).
5. "Copy sanitized text" puts the result on the clipboard.
6. If a file was loaded, "Save sanitized file" writes the result to the output folder. The original stays
   unchanged.

From 50,000 characters, the analysis runs in the background and the window stays usable. Very large texts
(more than `max_preview_chars` characters, default 200,000) are shown without the colored preview because the
text field would otherwise become very slow. Instead you get a summary with samples. Copying still works. An
archive (`.zip`, `.gz` …), an Office document or a PDF that is opened or dragged in here is sanitized directly
as a file run.

Drag & drop: a text file goes to the preview, a folder goes to the "Files & folders" tab. If you drop a file
onto the "Files & folders" tab, it becomes the input there. Drop one item at a time; if you have several
files, put them in a folder first.

### Tab "Files & folders"

1. "Open file" or "Choose folder" (all files including subfolders).
2. Output folder: if you leave it empty, the tool uses `<input folder>_sanitized` next to the input folder.
   Example: `C:\Logs\Server1` becomes `C:\Logs\Server1_sanitized`. For a single file `C:\Logs\app.log`, the
   result ends up in `C:\Logs_sanitized\app.log`.
3. "Start sanitizing". The subfolder structure is kept, the originals are never changed.
4. Afterwards the report appears: processed, skipped (e.g. binary files) and failed files with the number of
   replacements per category, without original values. The report is also written to the output folder as
   `secret_sanitizer_report.txt` (`secret_sanitizer_bericht.txt` when the language is German).
5. Files above `max_file_size_mb` (default 100 MB) trigger a confirmation prompt.
6. Exclude patterns: Folders such as `.git`, `node_modules`, `__pycache__`, `.venv` and earlier
   `*_sanitized` outputs are skipped and listed in the report (can be changed in the "Settings" tab).
7. "Clear output folder first" removes results of earlier runs. It only does this if the folder is empty or
   contains a report from this program (German or English), so it never clears a folder that isn't its own.
   Without the checkbox, the report warns about stale files from earlier runs, because their placeholder
   numbers don't match the current run.
8. "Sanitize file names" also replaces in folder and file names, e.g.
   `backup_srv01.corp.local.log` → `backup_[HOSTNAME_1].log`. The report then shows only the sanitized names.
9. Archives (`.zip`, `.tar`, `.tar.gz`/`.tgz`, `.gz`) are extracted, sanitized and packed again
   (checkbox "Sanitize archives (.zip, .gz, .tar)", on by default). Binary or encrypted entries are left out
   of the new archive and listed in the report.
10. Word, Excel and PowerPoint files (`.docx`, `.xlsx`, `.pptx`) are sanitized in place, keeping layout and
    formatting. This covers text, tables, headers and footers, footnotes, text boxes, cells, formulas, slides,
    notes, chart labels, comments, alt text, link targets and metadata. On top of that:
    - Tracked changes are accepted, since deleted text would otherwise stay in the file.
    - Author names (document, comments, changes) are cleared.
    - Images and embedded objects are removed because the tool can't check what's in them (a screenshot with a
      password, for example). You can turn this off in the "Settings" tab; the report gives the count.
    - Documents with macros (`.docm`, `.xlsm`, `.pptm`) are skipped.
    - Excel: A sanitized sheet name becomes a valid name like `(HOSTNAME_1)`; formulas, print areas and charts
      point to the new name.
11. PDFs: The text is read and saved as a sanitized `<name>.pdf.txt` (the PDF itself is not output). Scanned
    PDFs without text and password-protected PDFs are skipped.
12. Multiple CPU cores: From 4 files and 4 MB, the files are processed in parallel (setting "CPU cores for
    folder runs", default automatic). The result is exactly the same as with one core; for typical logs it is
    about 4 times as fast (8 cores). The report states the number of cores.

In a folder run, the same value gets the same placeholder in all files, including archives, Office documents
and PDFs. The placeholder numbers keep counting up across the whole run.

Text files can be UTF-8, UTF-16 (e.g. PowerShell output redirected with `>`), UTF-32, cp1252 or Latin-1. The
tool detects the encoding itself and keeps Windows line endings (`\r\n`). Output is UTF-8 by default.

### Tab "Restore reply"

Replies to sanitized text (from support, colleagues, an AI) often use the same placeholders, for example
"Restart the service on `[HOSTNAME_1]`". Paste the reply on the left and the real values show up on the
right, highlighted in color. At the top you pick whether the placeholders come from the "Text & preview" tab
or from the last folder run. The tool tells you about placeholders it doesn't know. This only works while the
program is open, because the mapping is never saved.

### Tab "Rules"

- Custom rules: Enter name, description, pattern (regular expression), category and confidence and click
  "Apply rule". In the test field below, you immediately see what the pattern finds as you type.
  Tip: With `(?P<value>...)` only a part is replaced, e.g. `customer=(?P<value>\w+)` replaces only the
  customer name. Patterns with nested repetitions like `(a+)+` can become extremely slow; the editor warns
  about this and does not test them live.
- Custom word lists: Choose a category (e.g. company names, hostnames, usernames, project names, personal
  names) and enter one entry per line. These words are replaced exactly.
- Allowlist: Entries that are never replaced, one per line. With `re:` at the start, the entry is a regular
  expression.
- "Save all rules" activates the changes.
- Profiles (bar at the bottom): Save and switch between several rule sets, e.g. "Customer A" and "Windows
  logs".
  - "Save as …" stores the current profile in the configuration folder (with word lists),
    "Load" applies a saved profile.
  - "Export …" writes a profile file for passing on, e.g. to colleagues. The word lists contain company and
    person names in plain text and are therefore only exported if you confirm.
  - "Import …" reads a profile file. First the tool shows what would change (new or changed rules, new words,
    allowlist) and asks whether to merge or replace. Invalid entries are reported and skipped; patterns that
    might be slow are flagged.
  - Profiles contain only rules, word lists, allowlist as well as mode and categories, no paths or commands.

### Tab "Settings"

Here you can edit all values from `config.json`: language, output folder, output encoding, limits, block
size, placeholder style, exclude patterns, CPU cores, PDF limits, mode thresholds and entropy thresholds.
Checkboxes turn the processing of Office documents and PDFs on and off, as well as the removal of images from
Office documents.

The language (Automatic, Deutsch or English) is at the very top under "General". A change only takes effect
after the app restarts; the program asks whether it should restart right away. On restart, the mapping for
restoring replies and unsaved input are lost.

## 5. Language

The GUI, the command line, messages and reports are available in English and German. The language is
determined in this order, the first one given wins:

1. Command-line option `--lang de` or `--lang en`
2. Environment variable `SECRET_SANITIZER_LANG` (`de` or `en`)
3. Setting `language` in `config.json` (`"auto"`, `"de"` or `"en"`), in the GUI under "Settings" → "General" →
   "Language"
4. Automatic: If the Windows language is German, the program runs in German, otherwise in English.

Without any setting, `"auto"` applies. If the entry is missing in an older `config.json` or contains an
invalid value, `"auto"` is used as well.

The report in the output folder is called `secret_sanitizer_report.txt` in English and
`secret_sanitizer_bericht.txt` in German. Both are recognized as a report of this program. If you switch the
language and use the same output folder again, "Clear output folder first" or `--clean` still works, and the
old report is replaced.

Placeholders (`[PASSWORD_1]` …), category IDs, command-line option names and values, return codes, the folder
name `_sanitized` and the extension `.pdf.txt` are the same in both languages. Custom rules, word lists and
profile names are never translated. Only the Windows file dialog follows the Windows language.

## 6. Command line

From source with `python -m secret_sanitizer …`, with the .exe as `secret_sanitizer_cli.exe …`.

```bat
REM Sanitize a folder -> logs_sanitized\
python -m secret_sanitizer C:\Logs\logs

REM File into a specific output folder
python -m secret_sanitizer app.log -o C:\Temp\sanitized

REM Via pipe (stdin -> stdout), e.g. sanitize command output directly
ipconfig /all | python -m secret_sanitizer - > ipconfig_sanitized.txt

REM Mode, categories
python -m secret_sanitizer --mode normal --no-personal --disable HOSTNAME,IP file.txt

REM Check only (write nothing), e.g. before a commit
python -m secret_sanitizer --check src\ config\
```

Important options (see `--help` for all):

| Option | Meaning |
|---|---|
| `-o FOLDER` | Output folder |
| `-m strict\|normal\|loose` | Mode |
| `--no-personal` | Do not replace email addresses and personal names |
| `--disable CAT,…` / `--enable CAT,…` | Switch categories off/on (`--list-categories` shows all) |
| `--output-encoding utf-8\|same\|…` | Output encoding (`same` = like input) |
| `--lang de\|en` | Language of the output (see [Language](#5-language)) |
| `-y` | Process large files without asking |
| `--check` | Check only, write nothing: lists files with matches (without values), return code `3` on matches |
| `--exclude PATTERN` | Additionally skip, e.g. `--exclude "*.bak"` (can be repeated) |
| `--no-exclude` | Do not apply the default exclude patterns (`.git`, `node_modules` …) either |
| `--clean` | Clear the output folder first (only if it comes from an earlier run) |
| `--sanitize-filenames` | Also sanitize folder and file names |
| `--no-archives` | Do not extract archives, skip them like binary files |
| `--no-office` / `--keep-office-media` | Do not sanitize Office documents / keep images in them |
| `--no-pdf` | Do not read PDFs |
| `--workers N` | CPU cores for folder runs (default automatic, `1` = one core only) |
| `--profile NAME\|FILE` | Rules (and mode/categories if present) from a profile instead of your own rules |
| `--export-profile FILE` | Export your own rules as a profile (with `--with-wordlists` including word lists) |
| `--config FILE`, `--rules FILE` | Different config.json / user_rules.json |
| `--no-user-rules` | Only the bundled rules |

Note on pipes under Windows: `cmd` outputs text in the OEM code page (usually cp850). Umlauts can therefore
appear garbled in the output; the detection itself is not affected. For clean umlauts, first write the output
to a file (`ipconfig /all > ip.txt`) and then sanitize the file.

Return codes: `0` ok, `1` individual files failed, `2` usage or input error, `3` matches found (only with
`--check`). Console messages contain only counters and relative paths, no original values.

Example of a Git pre-commit hook (`.git/hooks/pre-commit`) that stops commits containing secrets:

```sh
#!/bin/sh
git diff --cached --name-only --diff-filter=ACM -z | xargs -0 -r secret_sanitizer_cli.exe --check || {
  echo "Possible secrets in the commit (see above)."; exit 1; }
```

## 7. What is detected?

All methods run in parallel. Overlapping matches are merged, the match with the highest confidence wins. The
mode sets the minimum confidence.

| Method | Examples |
|---|---|
| Known formats (regex) | AWS keys `AKIA…`, GitHub `ghp_…`, GitLab, Slack, Google, Stripe, OpenAI/Anthropic keys, Hugging Face `hf_…`, PyPI `pypi-…`, Discord and Telegram bot tokens, JWT, Azure `AccountKey=` and SAS signatures `sig=…`, `user:pass@host` in URLs, email, IPv4/IPv6 (also private, but not `Version 1.2.3.4`), MAC, hostnames/FQDNs |
| Phone numbers | `+49 171 2345678`, `+49 (0)30 1234567`, `0171/2345678`, `030 12345678` (category `PHONE`, personal data) |
| PEM blocks | `-----BEGIN … PRIVATE KEY-----` to `-----END …-----` as a whole, also truncated blocks; certificates |
| Context (key=value) | `password=…`, `"api_key": "…"`, `token: …`, `export DB_PASSWORD=…`, `<password>…</password>`, `Authorization: Bearer …`, connection strings, also simple passwords like `hunter2`, passphrases with spaces (`password: correct horse battery`) and YAML block values (`password: \|` with an indented value) |
| Command line | `mysql -pSECRET`, `--password=…`, `curl -u user:pass`, `sshpass -p`, `net user name pw`, `/p:…`, PowerShell `-Password …`, `ConvertTo-SecureString "…"` |
| Windows | SIDs `S-1-5-21-…`, `C:\Users\<name>\…`, `DOMAIN\user`, UNC `\\server\share`, NTLM hashes (pwdump), `HKEY_USERS\<SID>` |
| Linux | `/home/<name>/…`, `/etc/shadow` hashes, SSH keys, `known_hosts`, Docker `config.json`, Kubernetes secrets (Base64), shell prompts `user@host` |
| Password hashes | `$6$`, `$5$`, `$1$` (MD5-crypt), bcrypt `$2b$`, yescrypt `$y$`, NTLM |
| Entropy | unknown random strings (e.g. keys without a known format); exceptions for file hashes, GUIDs, paths and identifiers |
| Checksums | Credit cards (Luhn) and IBAN (modulo 97). Only valid numbers are replaced |
| Custom word lists | Company names, internal hostnames, domains, users, projects, personal names |
| Consistency | A detected value is replaced everywhere, also URL-encoded, JSON/HTML-escaped and in different upper/lower case |

Not replaced by default (allowlist): `localhost`, `127.0.0.1`, `0.0.0.0`, `::1`, netmasks,
`example.com/.org/.net` and symbolic values like `true`, `null`, ``, `${VAR}`.

## 8. Configuration and custom rules

The settings are stored in the user folder, not in the program folder:

- Windows: `%APPDATA%\secret_sanitizer\config.json` and `user_rules.json`
- Linux/macOS: `~/.config/secret_sanitizer/`
- Different folder (e.g. portable on a USB stick): environment variable `SECRET_SANITIZER_HOME`

`config.json` (all values have defaults, missing or invalid values are ignored):

| Key | Default | Meaning |
|---|---|---|
| `mode` | `"strict"` | `strict`, `normal` or `loose` |
| `language` | `"auto"` | `"auto"`, `"de"` or `"en"` (see [Language](#5-language)) |
| `enabled_categories` | all on | e.g. `{"EMAIL": false}` |
| `output_dir` | `""` | empty = `<input folder>_sanitized` |
| `output_encoding` | `"utf-8"` | or e.g. `"utf-16"`, `"same"` |
| `max_file_size_mb` | `100` | above this, a confirmation prompt |
| `max_files_per_run` | `10000` | upper limit per run |
| `max_preview_chars` | `200000` | above this, no colored preview |
| `chunk_size` / `chunk_overlap` | `1000000` / `65536` | block size and overlap for large files (characters) |
| `entropy_thresholds` | per mode | entropy thresholds for `hex`, `base64`, `mixed` |
| `entropy_min_length` | 16 / 20 / 24 | minimum length per mode |
| `mode_thresholds` | 0.3 / 0.5 / 0.75 | minimum confidence per mode |
| `placeholder_style` | `"[{CATEGORY}_{N}]"` | must contain `{CATEGORY}` and `{N}` |
| `exclude_patterns` | `.git`, `node_modules`, `*_sanitized` … | skip folders/files in a folder run (fnmatch on name or relative path) |
| `sanitize_filenames` | `false` | also sanitize folder and file names |
| `process_archives` | `true` | extract `.zip`, `.tar`, `.tar.gz`/`.tgz`, `.gz`, sanitize, repack |
| `max_archive_mb` | `500` | upper limit for the extracted content of an archive or Office document (protection against zip bombs) |
| `workers` | `0` | CPU cores for folder runs: `0` = automatic (cores − 1, at most 8), `1` = one core only |
| `process_office` | `true` | sanitize `.docx`, `.xlsx`, `.pptx` |
| `office_remove_media` | `true` | remove images and embedded objects from Office documents |
| `process_pdf` | `true` | output text from PDFs as a sanitized `.pdf.txt` |
| `pdf_timeout_s` / `pdf_max_memory_mb` | `60` / `1024` | time and memory limit when reading a PDF |

It is best to create custom rules in the GUI (tab "Rules"). The format of `user_rules.json`:

```json
{
  "rules": [
    {"id": "ticket", "name": "Ticket number", "description": "Internal tickets",
     "category": "CUSTOM", "pattern": "TICKET-\\d{4,}", "confidence": 0.9,
     "flags": ["IGNORECASE"], "enabled": true}
  ],
  "wordlists": [
    {"id": "company", "name": "Company", "description": "Our names", "category": "COMPANY",
     "words": ["Example Ltd", "ExampleCorp"], "ignore_case": true, "enabled": true}
  ],
  "allowlist": [
    {"value": "10.0.0.1", "regex": false, "description": "Publicly known gateway"}
  ]
}
```

A custom rule with the same `id` as a bundled rule (see `secret_sanitizer/rules/default_rules.json`) replaces
it. This way you can, for example, switch off a default rule with `"enabled": false`.

## 9. Security

- Completely offline: no network access, no telemetry, no update checks, no online verification of found
  keys. A test makes sure that no network module is imported.
- No original values in logs, reports or error messages. Error messages name only the kind of error
  (e.g. "permission denied"), never the exception text. The list of findings in the GUI shows values only in
  shortened form.
- The mapping (value → placeholder) lives only in memory and is never saved. Translating replies back uses
  exactly this mapping and therefore only works while the program is open. It is discarded on closing.
- Archives are extracted into a temp folder that is always deleted after the run, also on errors or
  cancellation. Paths like `../` in an archive are rejected, size and count limits protect against zip bombs.
- Office documents are processed at text level, without an XML parser: no entities are expanded, files with
  `DOCTYPE` are rejected. If removing an image would leave a dangling reference, the tool writes no output
  instead of a broken document.
- PDFs are read in a separate process, with a time limit and a hard memory limit (Windows: job object). A
  crafted PDF can therefore neither hang the program nor fill the memory. The extracted text stays in memory
  and never ends up in a temp file.
- Multiple CPU cores: Values travel only through internal pipes between the processes, never via disk.
- Profiles contain only data (no paths, no commands) and are strictly checked on import.
- Dependencies are pinned with SHA-256 checksums; a tampered package aborts the installation.
- Original files are never changed. Outputs go to a separate folder. The output folder must not be the input
  folder or a parent folder. Output files are written completely first and then renamed, so half-written
  files do not remain.
- The report contains only relative paths and counters (with "Sanitize file names" only the sanitized names).

## 10. Limits and known restrictions

- No 100% guarantee. Personal names in running text, unusual passwords without a keyword and company-specific
  terms in particular are only found if they're in a custom word list or follow a recognizable pattern. Name recognition with AI (NER) is only planned for version 2.
- File names are not sanitized by default. For that, turn on "Sanitize file names" or
  `--sanitize-filenames`.
- Loose mode deliberately leaves uncertain matches in place, e.g. usernames from `DOMAIN\name` or generic
  hostnames.
- In Strict mode, public domains like `github.com` are replaced as well. Add them to the allowlist if needed.
- Once a value has been detected, the tool replaces it in every upper/lower case to be safe, even if the word
  list has "Ignore case" switched off. So the option only affects detection.
- Files with mixed line endings are written uniformly with the predominant line ending.
- Speed: For very dense logs (several matches per line), the tool manages about 0.2–0.5 MB per second with one
  core, because every file is read twice (learn first, then replace). More cores make it faster. Office
  documents and PDFs always run in the main process. You see the progress and can cancel at any time.
- Archives within archives, old Office formats (`.doc`, `.xls`, `.ppt`), OpenDocument (`.odt` …) and images are
  not processed. Binary files are skipped and listed in the report.
- Office: Images are removed, not checked (no text recognition). A formula that relies on a sanitized value
  (e.g. a password as a comparison value) calculates with the placeholder afterwards. A hint like "password"
  in one table cell and the value in the neighboring cell are not recognized as a pair (only within one
  cell/row, e.g. "Password: …").
- PDF: No text recognition (OCR) for scanned PDFs. The order of the text follows the PDF and can look
  unusual with multi-column layouts.
- Phone numbers are only detected with an area code and separators (`030 12345678`), not as a plain digit
  sequence.
- Drag & drop accepts only one item at a time.
- Custom regular expressions can be very slow if phrased carelessly (e.g. `(a+)+`). The editor warning is a
  heuristic and finds the typical cases, not all of them.
- The GUI needs Tk 8.6, as shipped by the python.org installers and the .exe. With Python builds that contain
  Tk 9, customtkinter currently does not start (error `expected integer but got ""`).

## 11. Development and tests

```bat
python -m unittest discover -s tests -t .
```

- The tests use only invented data from `tests/fake_secrets/`. They are generated with
  `python tests/fake_data.py`, including UTF-16, cp1252, CRLF and binary files.
- The tests check matches, false alarms (hashes, GUIDs, paths, numbers, ports), that reports and error
  messages contain no original values, that the same value in several spellings is replaced everywhere,
  block-wise processing of large files and the command line.
- Language tests check that `de.json` and `en.json` contain the same keys and placeholders and that the report,
  messages and command line work in both languages.
- Office and PDF tests build their own minimal OOXML and PDF documents. Sanitized files were also checked
  against real files created by Office: they open in Word, Excel and PowerPoint without needing repair. The
  PDF tests need `pypdf`.
- Multi-core tests compare the result byte for byte with a run using one core.
- GUI smoke test (needs a display and customtkinter, for drag & drop tkinterdnd2):
  `python tests/gui_smoke.py`
- On GitHub, the tests run automatically on every push on Windows and Linux with Python 3.10 and 3.13
  (`.github/workflows/tests.yml`).

Project structure:

```
secret_sanitizer/
├── __main__.py          Entry point: GUI or CLI
├── cli.py               Command line
├── config.py            APP_NAME, load/save settings
├── i18n.py              Language selection and texts (t())
├── locales/             de.json, en.json (all texts of the GUI, command line and reports)
├── core/                pipeline, models, rules, merger, replacer, encoding, files, archives,
│                        office, pdf, parallel (multiple cores), profiles
├── detectors/           regex, context (+ command line), wordlist, entropy, validators
├── rules/               default_rules.json, user_rules.json (template)
└── gui/                 app, widgets, rule_editor
packaging/               PyInstaller spec and start scripts
tests/                   Tests and fake_secrets/
build_exe.bat            Build of the .exe on Windows
```

License: not decided yet.
