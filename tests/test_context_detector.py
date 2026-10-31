"""Tests für Kontext-Heuristik und Kommandozeilen-Argumente."""

import unittest

from tests.helpers import SECRETS, SecretAssertions, sanitize

from secret_sanitizer.detectors.context_detector import key_tokens

S = SECRETS


class ContextDetectorTests(SecretAssertions, unittest.TestCase):
    def test_key_tokens(self):
        self.assertEqual(key_tokens("dbPassword"), ["db", "password"])
        self.assertEqual(key_tokens("AWS_SECRET-ACCESS.KEY"), ["aws", "secret", "access", "key"])

    def test_simple_password(self):
        self.assertEqual(sanitize("password=hunter2"), "password=[PASSWORD_1]")
        self.assertEqual(sanitize("Passwort: hunter2"), "Passwort: [PASSWORD_1]")
        self.assertEqual(sanitize("Das Passwort ist hunter2, ok"), "Das Passwort ist [PASSWORD_1], ok")

    def test_formats(self):
        self.assertEqual(sanitize('{"password": "Fake-Pa55w0rd!"}'), '{"password": "[PASSWORD_1]"}')
        self.assertEqual(sanitize("db_pass: 'a b c'"), "db_pass: '[PASSWORD_1]'")
        self.assertEqual(sanitize("<password>geheim99</password>"), "<password>[PASSWORD_1]</password>")
        self.assertEqual(sanitize('<add key="x" password="geheim99"/>'), '<add key="x" password="[PASSWORD_1]"/>')
        self.assertEqual(sanitize("$cfg['dbPassword'] => 'geheim99'"), "$cfg['dbPassword'] => '[PASSWORD_1]'")
        self.assertEqual(sanitize(f"export API_TOKEN=\"{S['env_token']}\""), 'export API_TOKEN="[TOKEN_1]"')
        self.assertEqual(sanitize("https://x.example.com/cb?token=abc123def&x=1"), "https://x.example.com/cb?token=[TOKEN_1]&x=1")

    def test_connection_string(self):
        out = sanitize(f"Server=sqlprod01;Database=Kunden;User Id=sa;Password={S['db_password']};")
        self.assertEqual(out, "Server=[HOSTNAME_1];Database=Kunden;User Id=[USERNAME_1];Password=[PASSWORD_1];")

    def test_passphrase_with_spaces(self):
        self.assertEqual(sanitize("password: correct horse battery staple"), "password: [PASSWORD_1]")
        self.assertEqual(sanitize("Passwort = mein geheimes Kennwort # alt"), "Passwort = [PASSWORD_1] # alt")
        # Schluss beim nächsten key=value, Trenner oder einer Option
        self.assertEqual(sanitize("password=foo bar host=sqlbox7"), "password=[PASSWORD_1] host=[HOSTNAME_1]")
        self.assertEqual(sanitize("password: foo bar, user: svc_app"), "password: [PASSWORD_1], user: [USERNAME_1]")
        self.assertEqual(sanitize("pwd=foo bar; x"), "pwd=[PASSWORD_1]; x")
        self.assertEqual(sanitize("tool --password=geheim99 --x"), "tool --password=[PASSWORD_1] --x")
        # Ein sichererer Treffer dahinter darf das Passwort nicht verdrängen
        self.assertEqual(sanitize("password=geheim99 an bob@firma.example.de"), "password=[PASSWORD_1] an [EMAIL_1]")
        self.assertEqual(sanitize("test pass: 5 of 6"), "test pass: 5 of 6")
        # Andere Treffer im Rest der Zeile bleiben eigenständig (nicht im Passwort-Platzhalter)
        self.assertEqual(sanitize("password=Geheim0x host srv0.corp.local"), "password=[PASSWORD_1] host [HOSTNAME_1]")
        self.assertEqual(sanitize("password=Geheim99 und 10.1.2.3"), "password=[PASSWORD_1] und [IP_1]")

    def test_quote_inside_value(self):
        self.assertEqual(sanitize('password=abc"def123'), "password=[PASSWORD_1]")
        self.assertEqual(sanitize("password=it's9secret"), "password=[PASSWORD_1]")
        self.assertEqual(sanitize('run "--password=geheim99"'), 'run "--password=[PASSWORD_1]"')

    def test_yaml_block_scalar(self):
        text = "db:\n  password: |\n    supersecret\n    zweite zeile\n  host_port: 5432\n"
        self.assertEqual(sanitize(text), "db:\n  password: |\n    [PASSWORD_1]\n  host_port: 5432\n")
        self.assertEqual(sanitize("password: >-\n  geheim99\n"), "password: >-\n  [PASSWORD_1]\n")
        # Blockmarker ohne Inhalt oder mit Variable: nichts ersetzen
        for text in ["password: |-\nnext: 1\n", "password: |\n  ${DB_PASSWORD}\n"]:
            self.assertEqual(sanitize(text), text)

    def test_bearer_scheme_skipped(self):
        out = sanitize(f"authorization: Bearer {S['bearer']}")
        self.assertEqual(out, "authorization: Bearer [TOKEN_1]")

    def test_not_secrets(self):
        for text in ["password_file=/run/secrets/db", "password: ${DB_PASSWORD}", "token_expires_in: 3600",
                     "password: ********", "password: null", "password_min_length = 12", "PWD=/home/[USERNAME_1]",
                     "session: 30", "$pw = ConvertTo-SecureString", "password = get_password(user)", "password: <dein passwort>", "password = %DBPASS%", "author: Fritz"]:
            self.assertEqual(sanitize(text), text, text)

    def test_hostname_and_user_keys(self):
        self.assertEqual(sanitize("host=sqlbox7 user=svc_app"), "host=[HOSTNAME_1] user=[USERNAME_1]")
        self.assertEqual(sanitize("host=sqlbox7", mode="loose"), "host=sqlbox7")


class CommandLineTests(SecretAssertions, unittest.TestCase):
    def test_mysql(self):
        self.assertEqual(sanitize(f"mysql -u root -p{S['mysql_pw']} prod"), "mysql -u root -p[PASSWORD_1] prod")

    def test_long_options(self):
        self.assertEqual(sanitize("tool --password=geheim99 --x"), "tool --password=[PASSWORD_1] --x")
        self.assertEqual(sanitize("tool --password geheim99"), "tool --password [PASSWORD_1]")
        self.assertEqual(sanitize("gh auth --token abcdef123456"), "gh auth --token [TOKEN_1]")

    def test_curl(self):
        out = sanitize(f"curl -u {S['curl_user']}:{S['curl_pw']} https://api.example.com")
        self.assertEqual(out, "curl -u [USERNAME_1]:[PASSWORD_1] https://api.example.com")

    def test_sshpass_and_generic_p(self):
        self.assertEqual(sanitize("sshpass -p 'geh eim' ssh x"), "sshpass -p '[PASSWORD_1]' ssh x")
        self.assertEqual(sanitize("tool -p geheimWert"), "tool -p [PASSWORD_1]")
        self.assertEqual(sanitize("tool -p geheimWert", mode="loose"), "tool -p geheimWert")

    def test_ports_are_not_passwords(self):
        for text in ["docker run -p 8080:80 nginx", "ssh -p 2222 host", "psql -p 5432", "mkdir -p /tmp/x"]:
            self.assertEqual(sanitize(text), text)

    def test_windows_commands(self):
        self.assertEqual(sanitize("net user administrator Geheim9"), "net user administrator [PASSWORD_1]")
        self.assertEqual(sanitize("net user bob *"), "net user bob *")
        self.assertEqual(sanitize("cmdkey /add:srv /user:bob /pass:Geheim9"), "cmdkey /add:srv /user:[USERNAME_1] /pass:[PASSWORD_1]")
        out = sanitize(f'ConvertTo-SecureString "{S["ps_password"]}" -AsPlainText')
        self.assertEqual(out, 'ConvertTo-SecureString "[PASSWORD_1]" -AsPlainText')
        self.assertEqual(sanitize(f"Connect -Password {S['ps_password']}"), "Connect -Password [PASSWORD_1]")
        self.assertEqual(sanitize("New-LocalUser -Password $pw"), "New-LocalUser -Password $pw")

    def test_chpasswd(self):
        self.assertEqual(sanitize("echo 'bob:Geheim9' | chpasswd"), "echo 'bob:[PASSWORD_1]' | chpasswd")


if __name__ == "__main__":
    unittest.main()
