"""Erfundene Testdaten (NUR Fakes, keine echten Secrets).

Alle Werte werden mit festem Zufalls-Seed erzeugt. Die Tests importieren die
Konstanten aus SECRETS, um zu prüfen, dass keiner dieser Werte in einer
bereinigten Ausgabe, einem Bericht oder einer Fehlermeldung auftaucht.

Neu erzeugen:  python tests/fake_data.py
"""

from __future__ import annotations

import base64
import random
import string
from pathlib import Path

FAKE_DIR = Path(__file__).resolve().parent / "fake_secrets"

_rng = random.Random(4711)
_ALNUM = string.ascii_letters + string.digits
_CRYPT = "./" + _ALNUM


def _rand(chars: str, n: int) -> str:
    return "".join(_rng.choice(chars) for _ in range(n))


def _b64(n_bytes: int) -> str:
    return base64.b64encode(bytes(_rng.randrange(256) for _ in range(n_bytes))).decode()


def _pem_body(n_bytes: int) -> str:
    raw = _b64(n_bytes)
    return "\n".join(raw[i:i + 64] for i in range(0, len(raw), 64))


# --------------------------------------------------------------------------
# Die Fake-Secrets (alle erfunden)
# --------------------------------------------------------------------------
SECRETS = {
    "aws_key": "AKIA" + _rand(string.ascii_uppercase + string.digits, 16),
    "aws_secret": _rand(_ALNUM + "+/", 40),
    "github": "ghp_" + _rand(_ALNUM, 36),
    "gitlab": "glpat-" + _rand(_ALNUM, 20),
    "slack": "xoxb-" + _rand(string.digits, 12) + "-" + _rand(_ALNUM, 24),
    "google": "AIza" + _rand(_ALNUM + "_-", 35),
    "jwt": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJmYWtlLXVzZXIiLCJleHAiOjk5OTk5fQ." + _rand(_ALNUM + "_-", 43),
    "db_password": "Fake-Pa55w0rd!",
    "simple_password": "hunter2",
    "env_token": _rand(_ALNUM, 32),
    "bearer": _rand(_ALNUM + "-_", 40),
    "mysql_pw": "MyFakeSql99",
    "curl_pw": "curlFake#77",
    "curl_user": "fakeuser",
    "url_pw": "UrlFakePw42",
    "ps_password": "PsFake$ecret1",
    "net_user_pw": "NetUserFake9",
    "ntlm": _rand("0123456789abcdef", 32),
    "lm": _rand("0123456789abcdef", 32),
    "sha512crypt": "$6$" + _rand(_CRYPT, 16) + "$" + _rand(_CRYPT, 86),
    "md5crypt": "$1$" + _rand(_CRYPT, 8) + "$" + _rand(_CRYPT, 22),
    "bcrypt": "$2b$12$" + _rand(_CRYPT, 53),
    "private_key_body": _pem_body(300),
    "cert_body": _pem_body(200),
    "ssh_pub": "AAAAC3NzaC1lZDI1NTE5AAAA" + _rand(_ALNUM + "+/", 43),
    "k8s_b64": base64.b64encode(b"FakeK8sPassw0rd!").decode(),
    "docker_auth": base64.b64encode(b"fakeuser:FakeDockerPw1").decode(),
    "entropy_secret": _rand(_ALNUM, 40),
    "ipv4_private": "192.168.178.23",
    "ipv4_public": "203.0.113.77",
    "ipv6": "2001:db8:85a3::8a2e:370:7334",
    "mac": "00:1A:2B:3C:4D:5E",
    "email": "erika.musterfrau@fake-firma.de",
    "win_user": "ErikaM",
    "linux_user": "jdoe",
    "sid": "S-1-5-21-1004336348-1177238915-682003330-1001",
    "unc": r"\\fileserver01\finanzen$",
    "domain_user": r"FAKECORP\mmuster",
    "hostname": "db01.intra.fake-firma.local",
    "credit_card": "4111 1111 1111 1111",
    "iban": "DE89370400440532013000",
    "company": "Fakefirma GmbH",
    "project": "Projekt Phoenix",
    "person": "Erika Musterfrau",
}

# Werte, die NICHT ersetzt werden dürfen (Fehlalarm-Tests).
FALSE_POSITIVES = [
    "d41d8cd98f00b204e9800998ecf8427e",              # MD5 (Datei-Hash)
    "da39a3ee5e6b4b0d3255bfef95601890afd80709",      # SHA-1
    "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",  # SHA-256
    "3f2504e0-4f89-11d3-9a0c-0305e82c3301",          # GUID
    "{6B29FC40-CA47-1067-B31D-00DD010662DA}",        # GUID mit Klammern
    "/usr/lib/x86_64-linux-gnu/libssl.so.3",         # Pfad
    "C:\\Windows\\System32\\drivers\\etc\\hosts",    # Pfad
    "C:\\Program Files\\Common Files",               # Pfad
    "HKLM\\SOFTWARE\\Microsoft",                     # Registry
    "1234567890",                                    # Zahl
    "2026-10-30T14:12:00Z",                          # Zeitstempel
    "12:30:45",                                      # Uhrzeit
    "getUserNameFromDatabase",                       # Bezeichner
    "test_user_account_2024",                        # Bezeichner
    "README.md",                                     # Dateiname
    "config.json",                                   # Dateiname
    "token_expires_in",                              # Schlüsselname
    "Version 10.0.19045",                            # Version
    "localhost",
    "127.0.0.1",
    "255.255.255.0",
    "-p 8080:80",                                    # Docker-Port
    "ssh -p 2222",                                   # SSH-Port
    "password_file",                                 # Schlüsselname
]


def _files() -> dict[str, tuple[str, str]]:
    s = SECRETS
    files: dict[str, tuple[str, str]] = {}

    files["linux/auth.log"] = ("utf-8", f"""\
Oct 30 08:12:01 db01 sshd[1234]: Accepted publickey for {s['linux_user']} from {s['ipv4_public']} port 51234 ssh2
Oct 30 08:12:05 db01 sudo:   {s['linux_user']} : TTY=pts/0 ; PWD=/home/{s['linux_user']}/projekte ; USER=root ; COMMAND=/usr/bin/systemctl restart nginx
Oct 30 08:13:44 db01 app[999]: connecting to postgres://appuser:{s['url_pw']}@{s['ipv4_private']}:5432/prod
Oct 30 08:13:45 db01 app[999]: Authorization: Bearer {s['bearer']}
Oct 30 08:14:00 db01 kernel: eth0: link up, hwaddr {s['mac']}, inet6 {s['ipv6']}
Oct 30 08:15:00 db01 app[999]: file checksum d41d8cd98f00b204e9800998ecf8427e ok, request id 3f2504e0-4f89-11d3-9a0c-0305e82c3301
Oct 30 08:15:01 db01 app[999]: notify {s['email']} about job on {s['hostname']}
""")

    files["linux/env_export.sh"] = ("utf-8", f"""\
#!/bin/bash
export AWS_ACCESS_KEY_ID={s['aws_key']}
export AWS_SECRET_ACCESS_KEY={s['aws_secret']}
export GITHUB_TOKEN={s['github']}
export API_TOKEN="{s['env_token']}"
export DB_PASSWORD='{s['db_password']}'
export PATH=/usr/local/bin:/usr/bin:/bin
export LANG=de_DE.UTF-8
mysql -u root -p{s['mysql_pw']} -h {s['ipv4_private']} prod < dump.sql
curl -u {s['curl_user']}:{s['curl_pw']} https://api.example.com/v1/status
sshpass -p '{s['db_password']}' ssh {s['linux_user']}@{s['hostname']}
docker run -p 8080:80 nginx
ssh -p 2222 backup@{s['ipv4_private']}
""")

    files["linux/shadow_fake.txt"] = ("utf-8", f"""\
root:{s['sha512crypt']}:19000:0:99999:7:::
daemon:*:19000:0:99999:7:::
{s['linux_user']}:{s['md5crypt']}:19001:0:99999:7:::
webadmin:{s['bcrypt']}:19002:0:99999:7:::
""")

    files["linux/k8s_secret.yaml"] = ("utf-8", f"""\
apiVersion: v1
kind: Secret
metadata:
  name: app-credentials
type: Opaque
data:
  db-pass: {s['k8s_b64']}
  username: YWRtaW4=
""")

    files["linux/docker_config.json"] = ("utf-8", f"""\
{{
  "auths": {{
    "registry.fake-firma.de": {{
      "auth": "{s['docker_auth']}"
    }}
  }}
}}
""")

    files["linux/id_ed25519_fake"] = ("utf-8", f"""\
-----BEGIN OPENSSH PRIVATE KEY-----
{s['private_key_body']}
-----END OPENSSH PRIVATE KEY-----
""")

    files["linux/known_hosts_and_keys.txt"] = ("utf-8", f"""\
{s['hostname']},{s['ipv4_private']} ssh-ed25519 {s['ssh_pub']}
ssh-ed25519 {s['ssh_pub']} {s['linux_user']}@laptop
""")

    files["config/app_settings.json"] = ("utf-8", f"""\
{{
  "database": {{
    "host": "{s['hostname']}",
    "user": "app_svc",
    "password": "{s['db_password']}",
    "password_file": "/run/secrets/db",
    "timeout": 30
  }},
  "api_key": "{s['google']}",
  "token_expires_in": 3600,
  "jwt": "{s['jwt']}",
  "contact": "{s['email']}",
  "slack_webhook_token": "{s['slack']}",
  "gitlab": "{s['gitlab']}"
}}
""")

    files["config/connection_strings.txt"] = ("utf-8", f"""\
Server=sqlprod01;Database=Kunden;User Id=sa;Password={s['db_password']};
DefaultEndpointsProtocol=https;AccountName=fakestorage;AccountKey={s['aws_secret']}==;EndpointSuffix=core.windows.net
redis://:{s['url_pw']}@cache.fake-firma.local:6379/0
""")

    files["config/server.pem"] = ("utf-8", f"""\
-----BEGIN CERTIFICATE-----
{s['cert_body']}
-----END CERTIFICATE-----
-----BEGIN RSA PRIVATE KEY-----
{s['private_key_body']}
-----END RSA PRIVATE KEY-----
""")

    files["windows/powershell_utf16.txt"] = ("utf-16", f"""\
PS C:\\Users\\{s['win_user']}\\Documents> whoami
{s['domain_user']}
PS C:\\Users\\{s['win_user']}\\Documents> whoami /user
Benutzername    SID
=============== =============================================
{s['domain_user'].lower()} {s['sid']}
PS> $pw = ConvertTo-SecureString "{s['ps_password']}" -AsPlainText -Force
PS> New-LocalUser -Name svc_backup -Password $pw
PS> Connect-Thing -Server {s['hostname']} -Password {s['ps_password']}
PS> Get-ChildItem \\\\fileserver01\\finanzen$\\2026
IPv4-Adresse  . . . . . . . . . . : {s['ipv4_private']}
Physische Adresse . . . . . . . . : 00-1A-2B-3C-4D-5E
""")

    files["windows/cmd_cp1252.txt"] = ("cp1252", f"""\
C:\\Users\\{s['win_user']}> net user administrator {s['net_user_pw']}
Der Befehl wurde erfolgreich ausgeführt. Größe: 12 Kb, Grüße an Jürgen
C:\\Users\\{s['win_user']}> net use Z: {s['unc']} /user:{s['domain_user']} /p:{s['net_user_pw']}
C:\\> type C:\\Windows\\System32\\drivers\\etc\\hosts
Registry: HKEY_USERS\\{s['sid']}\\Software\\Microsoft
""")

    files["windows/secretsdump_crlf.txt"] = ("utf-8-crlf", f"""\
Administrator:500:{s['lm']}:{s['ntlm']}:::
Guest:501:aad3b435b51404eeaad3b435b51404ee:31d6cfe0d16ae931b73c59d7e0c089c0:::
ntlm_hash = {s['ntlm']}
""")

    files["mixed/notes.txt"] = ("utf-8", f"""\
Notiz zum Kunden {s['company']} ({s['project']}), Ansprechpartnerin {s['person']}.
Das Passwort ist {s['simple_password']}, bitte nicht weitergeben.
password: {s['simple_password']}
Zahlung per Karte {s['credit_card']} oder IBAN {s['iban']}.
Unbekannter Schlüssel ohne Kontext: {s['entropy_secret']}
Gleicher Wert URL-codiert: https://example.com/?q=Fake-Pa55w0rd%21 und groß: {s['db_password'].upper()}
""")

    files["mixed/false_positives.txt"] = ("utf-8", "\n".join(FALSE_POSITIVES) + "\n" + """\
Die Datei README.md und config.json liegen unter /usr/lib/x86_64-linux-gnu/libssl.so.3.
Build 2026-10-30T14:12:00Z um 12:30:45, Version 10.0.19045, Nummer 1234567890.
Der Aufruf getUserNameFromDatabase liefert test_user_account_2024.
""")

    return files


def generate(target: Path = FAKE_DIR) -> None:
    """Schreibt alle Fake-Dateien nach tests/fake_secrets/."""
    for rel, (encoding, content) in _files().items():
        path = target / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if encoding == "utf-8-crlf":
            path.write_bytes(content.replace("\n", "\r\n").encode("utf-8"))
        elif encoding == "utf-16":
            # UTF-16 LE mit BOM, wie PowerShell "> datei.txt" schreibt.
            path.write_bytes(content.replace("\n", "\r\n").encode("utf-16"))
        else:
            path.write_bytes(content.encode(encoding))
    # Binärdatei (muss übersprungen werden)
    (target / "binary").mkdir(parents=True, exist_ok=True)
    (target / "binary" / "fake_image.png").write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + bytes(range(256)) + b"password=" + SECRETS["db_password"].encode())


if __name__ == "__main__":
    generate()
    print("Fake-Testdaten erzeugt in", FAKE_DIR)
