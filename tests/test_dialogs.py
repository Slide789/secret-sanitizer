"""Tests für die eigenen, übersetzten Dialoge (ersetzen tkinter.messagebox)."""

from __future__ import annotations

import unittest
from pathlib import Path

from tests import helpers  # noqa: F401  (setzt Sprache und Config-Ordner)
from secret_sanitizer import i18n

try:
    import customtkinter as ctk
except Exception:   # pragma: no cover
    ctk = None


def _quiet_destroy(root) -> None:
    """Zerstört das Fenster und bricht vorher dessen offene after-Aufträge ab
    (CTk plant welche nach 200 ms). Sonst meldet Tk später "invalid command name"."""
    try:
        for job in root.tk.splitlist(root.tk.call("after", "info")):
            root.after_cancel(job)
    except Exception:
        pass
    root.destroy()


def _display_available() -> bool:
    if ctk is None:
        return False
    try:
        root = ctk.CTk()
        _quiet_destroy(root)
        return True
    except Exception:
        return False


HAVE_GUI = _display_available()
GUI_DIR = Path(__file__).resolve().parent.parent / "secret_sanitizer" / "gui"


def _button_texts(widget) -> list[str]:
    found = []
    for child in widget.winfo_children():
        if isinstance(child, ctk.CTkButton):
            found.append(child.cget("text"))
        found.extend(_button_texts(child))
    return found


@unittest.skipUnless(HAVE_GUI, "customtkinter oder Display fehlt")
class DialogTests(unittest.TestCase):
    def setUp(self):
        from secret_sanitizer.gui import dialogs
        self.dialogs = dialogs
        self.root = ctk.CTk()
        self.root.geometry("400x300")
        self.root.update()
        self.addCleanup(_quiet_destroy, self.root)
        self.addCleanup(i18n.set_language, "de")

    def test_yes_no_returns_true_false(self):
        self.assertIs(self.dialogs.ask_yes_no("T", "M", self.root, _auto="yes"), True)
        self.assertIs(self.dialogs.ask_yes_no("T", "M", self.root, _auto="no"), False)

    def test_yes_no_cancel_returns_none(self):
        self.assertIs(self.dialogs.ask_yes_no_cancel("T", "M", self.root, _auto="cancel"), None)
        self.assertIs(self.dialogs.ask_yes_no_cancel("T", "M", self.root, _auto="yes"), True)
        self.assertIs(self.dialogs.ask_yes_no_cancel("T", "M", self.root, _auto="no"), False)

    def test_info_returns_none(self):
        self.assertIsNone(self.dialogs.show_info("T", "M", self.root, _auto="ok"))
        self.assertIsNone(self.dialogs.show_error("T", "M", self.root, _auto="ok"))
        self.assertIsNone(self.dialogs.show_warning("T", "M", self.root, _auto="ok"))

    def test_grab_released_and_focus_restored(self):
        self.dialogs.ask_yes_no("T", "M", self.root, _auto="yes")
        self.assertIsNone(self.root.grab_current())
        self.assertEqual([c for c in self.root.winfo_children() if isinstance(c, ctk.CTkToplevel)], [])

    def _texts_while_open(self, language: str, func) -> list[str]:
        i18n.set_language(language)
        seen: list[str] = []

        def inspect():
            for child in self.root.winfo_children():
                if isinstance(child, ctk.CTkToplevel):
                    seen.extend(_button_texts(child))
            if not seen:   # Dialog noch im Aufbau: nochmal versuchen
                self.root.after(5, inspect)
        self.root.after(5, inspect)
        func()
        return seen

    def test_buttons_follow_language(self):
        ask = lambda: self.dialogs.ask_yes_no("T", "M", self.root, _auto="yes")
        self.assertCountEqual(self._texts_while_open("en", ask), ["Yes", "No"])
        self.assertCountEqual(self._texts_while_open("de", ask), ["Ja", "Nein"])
        cancel = lambda: self.dialogs.ask_yes_no_cancel("T", "M", self.root, _auto="cancel")
        self.assertCountEqual(self._texts_while_open("en", cancel), ["Yes", "No", "Cancel"])
        info = lambda: self.dialogs.show_info("T", "M", self.root, _auto="ok")
        self.assertCountEqual(self._texts_while_open("de", info), ["OK"])


class NoMessageboxTests(unittest.TestCase):
    def test_no_messagebox_left(self):
        for path in GUI_DIR.glob("*.py"):
            self.assertNotIn("messagebox.", path.read_text(encoding="utf-8"), path.name)


if __name__ == "__main__":
    unittest.main()
