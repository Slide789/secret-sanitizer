"""GUI-Smoke-Test (manuell bzw. unter Xvfb): startet das Fenster, bedient die
wichtigsten Funktionen automatisch und beendet sich wieder.

    python tests/gui_smoke.py [screenshot-ordner]

Benötigt customtkinter und ein Display. Verwendet nur Fake-Daten.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = ROOT / "tests" / "_tmp" / "gui_smoke"
shutil.rmtree(TMP, ignore_errors=True)
TMP.mkdir(parents=True)

from secret_sanitizer import config  # noqa: E402

os.environ[config.HOME_ENV_VAR] = str(TMP / "config_home")

from tests.fake_data import FAKE_DIR, SECRETS, generate  # noqa: E402

SHOTS = Path(sys.argv[1]) if len(sys.argv) > 1 else None


def screenshot(app, name: str) -> None:
    if not SHOTS:
        return
    app.update()
    time.sleep(0.3)
    app.update()
    SHOTS.mkdir(parents=True, exist_ok=True)
    subprocess.run(["import", "-window", "root", str(SHOTS / f"{name}.png")], check=False)


def pump(app, seconds: float) -> None:
    end = time.time() + seconds
    while time.time() < end:
        app.update()
        time.sleep(0.02)


def main() -> int:
    from secret_sanitizer.gui.app import App

    errors: list[str] = []
    app = App()
    app.report_callback_exception = lambda *exc: errors.append(repr(exc[1]))
    pump(app, 1.0)

    # 1) Text einfügen -> Vorschau
    sample = (FAKE_DIR / "linux" / "auth.log").read_text(encoding="utf-8") + \
        (FAKE_DIR / "linux" / "env_export.sh").read_text(encoding="utf-8")
    app._set_original(sample, None)
    pump(app, 1.0)
    out = app.clean_box.get_text()
    assert "[PASSWORD_1]" in out, "Vorschau ohne Platzhalter"
    for key in ("db_password", "github", "aws_key", "bearer"):
        assert SECRETS[key] not in out, f"{key} nicht ersetzt"
    rows = app.table.tree.get_children()
    assert rows, "Trefferliste leer"
    screenshot(app, "1_vorschau")

    # 2) Einen Treffer "doch nicht ersetzen"
    ip_row = next(r for r in rows if app.table._keys[r].startswith("[IP_"))
    app.table.tree.selection_set(ip_row)
    pump(app, 0.3)
    app.toggle_selected()
    pump(app, 0.5)
    assert "192.168.178.23" in app.clean_box.get_text() or SECRETS["ipv4_public"] in app.clean_box.get_text(), \
        "Ausnahme wirkt nicht"
    app.copy_result()
    assert app.clipboard_get() == app.result.text
    screenshot(app, "2_ausnahme")

    # 3) Modus und Kategorie umschalten
    app._mode_changed("Locker")
    pump(app, 0.5)
    app.categories.vars["EMAIL"].set(False)
    app.categories._changed()
    pump(app, 0.5)
    assert SECRETS["email"] in app.clean_box.get_text(), "E-Mail-Schalter wirkt nicht"
    app._mode_changed("Streng")
    app.categories.vars["EMAIL"].set(True)
    app.categories._changed()
    pump(app, 0.5)

    # 4) Ordnerlauf
    src = TMP / "daten"
    generate(src)
    app.tabs.set("Dateien & Ordner")
    app.input_var.set(str(src))
    app.start_run()
    for _ in range(300):
        pump(app, 0.1)
        if app._worker and not app._worker.is_alive() and app.start_btn.cget("state") == "normal":
            break
    pump(app, 0.5)
    report = app.report_box.get_text()
    assert "Bearbeitet: 15" in report, report[:400]
    assert (TMP / "daten_sanitized" / "linux" / "auth.log").exists()
    screenshot(app, "3_ordner")

    # 5) Regel-Editor mit Testfeld, Wortliste, Allowlist, speichern
    app.tabs.set("Regeln")
    ed = app.rule_editor
    ed.var_name.set("Ticketnummer")
    ed.var_desc.set("Interne Ticketnummern")
    ed.var_pattern.set(r"TICKET-\d{4,}")
    ed.test_box.set_text("Siehe TICKET-12345 und ticket-9999 sowie TICKET-12")
    pump(app, 0.6)
    assert ed.test_result.cget("text").startswith("2 Treffer"), ed.test_result.cget("text")
    ed._apply_rule()
    ed.wl_box.insert("1.0", "Fakefirma GmbH\nProjekt Phoenix")
    ed.allow_box.insert("1.0", "203.0.113.77")
    ed.save()
    pump(app, 0.5)
    assert config.user_rules_path().exists()
    screenshot(app, "4_regeln")
    app.tabs.set("Text & Vorschau")
    app._set_original("TICKET-4711 bei Fakefirma GmbH von 203.0.113.77", None)
    pump(app, 1.0)
    assert app.clean_box.get_text() == "[CUSTOM_1] bei [COMPANY_1] von 203.0.113.77", app.clean_box.get_text()

    # 6) Einstellungen speichern
    app.tabs.set("Einstellungen")
    app.setting_vars["max_preview_chars"].set("50")
    app.save_settings_form()
    pump(app, 0.3)
    screenshot(app, "5_einstellungen")
    app.tabs.set("Text & Vorschau")
    app._set_original(sample, None)
    pump(app, 1.0)
    assert "Stichproben" in app.clean_box.get_text()
    assert SECRETS["db_password"] not in app.result.text
    screenshot(app, "6_gross")

    app._on_close()
    if errors:
        print("GUI-Fehler:", errors)
        return 1
    print("GUI-Smoke-Test OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
