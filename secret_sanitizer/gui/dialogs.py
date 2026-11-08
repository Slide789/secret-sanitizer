"""Eigene Dialoge statt der Windows-Standarddialoge von tkinter.

Die Buttons (OK/Ja/Nein/Abbrechen) kommen aus dem Sprachkatalog und folgen so
der App-Sprache statt der Windows-Sprache. Rückgabewerte wie bei den tkinter-Dialogen:
ask_yes_no -> bool, ask_yes_no_cancel -> True/False/None.
"""

from __future__ import annotations

import tkinter as tk

import customtkinter as ctk

from ..i18n import t

_ICONS = {"info": "ℹ", "warning": "⚠", "error": "✖", "question": "?"}
_ICON_COLORS = {"info": "#2980b9", "warning": "#e67e22", "error": "#c0392b", "question": "#2980b9"}
_WRAP = 420


class _Dialog(ctk.CTkToplevel):
    def __init__(self, parent, title: str, message: str, kind: str, buttons: list[tuple[str, object]],
                 default_index: int, escape_value: object, auto: str | None, auto_map: dict[str, object]) -> None:
        super().__init__(parent)
        self.withdraw()
        self.result: object = escape_value
        self._escape_value = escape_value
        self._parent = parent
        self.title(title)
        self.resizable(False, False)
        if parent is not None:
            self.transient(parent)

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=20, pady=(18, 8))
        ctk.CTkLabel(body, text=_ICONS[kind], width=40, text_color=_ICON_COLORS[kind],
                     font=ctk.CTkFont(size=30, weight="bold")).pack(side="left", anchor="n", padx=(0, 12))
        ctk.CTkLabel(body, text=message, wraplength=_WRAP, justify="left", anchor="w").pack(
            side="left", fill="both", expand=True)

        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=20, pady=(8, 16))
        self._buttons: list[ctk.CTkButton] = []
        for label, value in reversed(buttons):
            btn = ctk.CTkButton(row, text=label, width=96, command=lambda v=value: self._finish(v))
            btn.pack(side="right", padx=(8, 0))
            self._buttons.insert(0, btn)
        self._default_button = self._buttons[default_index]
        self._default_value = buttons[default_index][1]

        self.bind("<Return>", lambda _e: self._finish(self._default_value))
        self.bind("<KP_Enter>", lambda _e: self._finish(self._default_value))
        self.bind("<Escape>", lambda _e: self._finish(self._escape_value))
        self.protocol("WM_DELETE_WINDOW", lambda: self._finish(self._escape_value))

        self._place()
        self.deiconify()
        self.lift()
        try:
            self.wait_visibility()
            self.grab_set()
        except tk.TclError:
            pass   # Fenster nicht sichtbar (z. B. Elternfenster weg): ohne Grab weiter
        self.focus_force()
        self._default_button.focus_set()
        if auto is not None:
            self.after(50, lambda: self._finish(auto_map[auto]))

    def _place(self) -> None:
        """Mittig über dem Elternfenster (bzw. Bildschirm), im sichtbaren Bereich."""
        self.update_idletasks()
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        p = self._parent
        if p is not None and p.winfo_viewable():
            x = p.winfo_rootx() + (p.winfo_width() - w) // 2
            y = p.winfo_rooty() + (p.winfo_height() - h) // 2
        else:
            x = (self.winfo_screenwidth() - w) // 2
            y = (self.winfo_screenheight() - h) // 2
        x = max(0, min(x, self.winfo_screenwidth() - w))
        y = max(0, min(y, self.winfo_screenheight() - h))
        self.geometry(f"+{x}+{y}")

    def _finish(self, value: object) -> None:
        self.result = value
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()

    def run(self) -> object:
        try:
            self.wait_window(self)
        except tk.TclError:
            pass
        if self._parent is not None:
            try:
                self._parent.focus_force()
            except tk.TclError:
                pass
        return self.result


def _parent_or_default(parent):
    return parent if parent is not None else tk._default_root


def _run(title, message, parent, kind, buttons, default_index, escape_value, auto, auto_map):
    dlg = _Dialog(_parent_or_default(parent), title, message, kind, buttons, default_index,
                  escape_value, auto, auto_map)
    return dlg.run()


def _ok_dialog(title, message, parent, kind, auto):
    _run(title, message, parent, kind, [(t("dialog.ok"), None)], 0, None, auto, {"ok": None})
    return None


def show_info(title: str, message: str, parent=None, *, _auto: str | None = None) -> None:
    _ok_dialog(title, message, parent, "info", _auto)


def show_warning(title: str, message: str, parent=None, *, _auto: str | None = None) -> None:
    _ok_dialog(title, message, parent, "warning", _auto)


def show_error(title: str, message: str, parent=None, *, _auto: str | None = None) -> None:
    _ok_dialog(title, message, parent, "error", _auto)


def ask_yes_no(title: str, message: str, parent=None, *, default: str = "yes",
               _auto: str | None = None) -> bool:
    """Ja/Nein. default="no": Enter löst Nein aus. Escape/Schließen = Nein."""
    buttons = [(t("dialog.yes"), True), (t("dialog.no"), False)]
    return bool(_run(title, message, parent, "question", buttons, 1 if default == "no" else 0,
                     False, _auto, {"yes": True, "no": False}))


def ask_yes_no_cancel(title: str, message: str, parent=None, *, default: str = "yes",
                      _auto: str | None = None) -> bool | None:
    """Ja/Nein/Abbrechen -> True/False/None. Escape/Schließen = Abbrechen."""
    buttons = [(t("dialog.yes"), True), (t("dialog.no"), False), (t("dialog.cancel"), None)]
    index = {"yes": 0, "no": 1, "cancel": 2}.get(default, 0)
    return _run(title, message, parent, "question", buttons, index, None, _auto,
                {"yes": True, "no": False, "cancel": None})
