"""Wiederverwendbare GUI-Bausteine: Textfeld mit farbiger Markierung,
Kategorie-Schalter und Trefferliste."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import customtkinter as ctk

from ..core.models import CATEGORIES, GROUPS, PERSONAL_CATEGORIES, group_label

MONO_FONT = ("Consolas", 12)
ROWS_PER_GROUP = 5


def _readable_text_color(hex_color: str) -> str:
    """Schwarz oder Weiß, je nachdem was auf der Hintergrundfarbe besser lesbar ist."""
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
    return "#000000" if (0.299 * r + 0.587 * g + 0.114 * b) > 150 else "#ffffff"


class HighlightTextbox(ctk.CTkTextbox):
    """Textfeld, das Bereiche farbig nach Kategorie markieren kann."""

    def __init__(self, master, readonly: bool = False, **kwargs) -> None:
        kwargs.setdefault("font", ctk.CTkFont(family=MONO_FONT[0], size=MONO_FONT[1]))
        kwargs.setdefault("wrap", "none")
        kwargs.setdefault("undo", True)
        super().__init__(master, **kwargs)
        self.readonly = readonly
        for cat in CATEGORIES.values():
            self.tag_config(f"cat_{cat.id}", background=cat.color, foreground=_readable_text_color(cat.color))
        self.tag_config("focus", underline=True, background="#ffff00", foreground="#000000")
        self.tag_config("testhit", background="#f1c40f", foreground="#000000")
        if readonly:
            self.configure(state="disabled")

    def set_text(self, text: str) -> None:
        self.configure(state="normal")
        self.delete("1.0", "end")
        self.insert("1.0", text)
        self.edit_reset()
        if self.readonly:
            self.configure(state="disabled")

    def get_text(self) -> str:
        # Tk hängt immer ein abschließendes \n an
        return self.get("1.0", "end-1c")

    @staticmethod
    def index_of(offset: int) -> str:
        return f"1.0+{offset}c"

    def clear_highlights(self) -> None:
        for cat in CATEGORIES:
            self.tag_remove(f"cat_{cat}", "1.0", "end")
        self.tag_remove("focus", "1.0", "end")
        self.tag_remove("testhit", "1.0", "end")

    def highlight(self, spans) -> None:
        """spans: Iterable aus (start, end, kategorie) als Zeichen-Offsets."""
        self.clear_highlights()
        for start, end, category in spans:
            self.tag_add(f"cat_{category}", self.index_of(start), self.index_of(end))

    def mark(self, spans, tag: str = "focus") -> None:
        self.tag_remove(tag, "1.0", "end")
        first = None
        for start, end in spans:
            self.tag_add(tag, self.index_of(start), self.index_of(end))
            if first is None:
                first = start
        self.tag_raise(tag)
        if first is not None:
            self.see(self.index_of(first))


class CategoryPanel(ctk.CTkFrame):
    """Häkchen je Kategorie, nach Gruppen sortiert. Personenbezogene Daten
    haben zusätzlich einen eigenen Gesamtschalter."""

    def __init__(self, master, enabled: dict, on_change, **kwargs) -> None:
        super().__init__(master, **kwargs)
        self.on_change = on_change
        self.vars: dict[str, tk.BooleanVar] = {}
        self.personal_var = tk.BooleanVar(value=all(enabled.get(c, True) for c in PERSONAL_CATEGORIES))
        col = 0
        for group in GROUPS:
            label = group_label(group)
            frame = ctk.CTkFrame(self, fg_color="transparent")
            frame.grid(row=0, column=col, sticky="nw", padx=6, pady=2)
            col += 1
            if group == "personal":
                ctk.CTkSwitch(frame, text=label, variable=self.personal_var, command=self._toggle_personal,
                              font=ctk.CTkFont(weight="bold"), height=20).grid(row=0, column=0, columnspan=3, sticky="w")
            else:
                ctk.CTkLabel(frame, text=label, font=ctk.CTkFont(weight="bold"), height=20).grid(
                    row=0, column=0, columnspan=3, sticky="w")
            members = [c for c in CATEGORIES.values() if c.group == group]
            for i, cat in enumerate(members):
                var = tk.BooleanVar(value=enabled.get(cat.id, True))
                self.vars[cat.id] = var
                box = ctk.CTkCheckBox(frame, text=cat.label, variable=var, command=self._changed,
                                      checkbox_width=16, checkbox_height=16, border_width=2, height=22,
                                      fg_color=cat.color, hover_color=cat.color, font=ctk.CTkFont(size=12))
                # höchstens fünf Zeilen je Gruppe, damit der Kopfbereich flach bleibt
                box.grid(row=1 + i % ROWS_PER_GROUP, column=i // ROWS_PER_GROUP, sticky="w", padx=(0, 8), pady=1)

    def _toggle_personal(self) -> None:
        for cat in PERSONAL_CATEGORIES:
            self.vars[cat].set(self.personal_var.get())
        self._changed()

    def _changed(self) -> None:
        self.personal_var.set(all(self.vars[c].get() for c in PERSONAL_CATEGORIES))
        self.on_change(self.values())

    def values(self) -> dict:
        return {cat: var.get() for cat, var in self.vars.items()}


def style_treeview(widget: tk.Misc) -> None:
    """ttk.Treeview an helles/dunkles customtkinter-Design anpassen."""
    dark = ctk.get_appearance_mode() == "Dark"
    bg, fg, sel = ("#2b2b2b", "#dce4ee", "#1f538d") if dark else ("#ffffff", "#1a1a1a", "#3a7ebf")
    head_bg = "#3a3a3a" if dark else "#e5e5e5"
    style = ttk.Style(widget)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    style.configure("Treeview", background=bg, foreground=fg, fieldbackground=bg, rowheight=24, borderwidth=0)
    style.map("Treeview", background=[("selected", sel)], foreground=[("selected", "#ffffff")])
    style.configure("Treeview.Heading", background=head_bg, foreground=fg, relief="flat")


class FindingTable(ctk.CTkFrame):
    """Trefferliste: ein Eintrag je ersetztem Wert. Der Originalwert wird nur
    gekürzt angezeigt (z. B. 'hun… (7 Zeichen)'), damit er bei geteiltem
    Bildschirm nicht komplett sichtbar ist."""

    COLUMNS = (("placeholder", "Platzhalter", 150), ("category", "Kategorie", 140), ("preview", "Wert (gekürzt)", 190),
               ("count", "Anzahl", 70), ("detector", "Erkannt durch", 150), ("confidence", "Konfidenz", 90),
               ("status", "Status", 130))

    def __init__(self, master, on_select, on_toggle, **kwargs) -> None:
        super().__init__(master, **kwargs)
        self.on_select = on_select
        self.on_toggle = on_toggle
        style_treeview(self)
        self.tree = ttk.Treeview(self, columns=[c[0] for c in self.COLUMNS], show="headings", height=6,
                                 selectmode="browse")
        for key, label, width in self.COLUMNS:
            self.tree.heading(key, text=label)
            self.tree.column(key, width=width, anchor="w", stretch=key in ("preview", "detector"))
        for cat in CATEGORIES.values():
            self.tree.tag_configure(cat.id, foreground=cat.color)
        self.tree.tag_configure("excluded", foreground="#7f8c8d")
        scroll = ctk.CTkScrollbar(self, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self.tree.bind("<<TreeviewSelect>>", self._selected)
        self.tree.bind("<Double-1>", lambda _e: self._toggle())
        self.tree.bind("<Return>", lambda _e: self._toggle())
        self._keys: dict[str, str] = {}   # Zeilen-ID -> Wert-Schlüssel (nur im Speicher)

    @staticmethod
    def preview(value: str) -> str:
        flat = value.replace("\n", " ")
        if len(flat) <= 4:
            return "…" + f" ({len(value)} Zeichen)"
        return flat[:3] + f"… ({len(value)} Zeichen)"

    def set_rows(self, rows) -> None:
        """rows: Liste von Dicts mit key, placeholder, category, value, count, detectors, confidence, excluded."""
        self.tree.delete(*self.tree.get_children())
        self._keys.clear()
        for i, row in enumerate(rows):
            iid = f"r{i}"
            self._keys[iid] = row["key"]
            cat = CATEGORIES.get(row["category"])
            status = "nicht ersetzt" if row["excluded"] else "wird ersetzt"
            self.tree.insert("", "end", iid=iid, tags=("excluded",) if row["excluded"] else (row["category"],), values=(
                row["placeholder"] if not row["excluded"] else "—", cat.label if cat else row["category"],
                self.preview(row["value"]), row["count"], ", ".join(sorted(row["detectors"])),
                f"{row['confidence']:.2f}", status))

    def selected_key(self) -> str | None:
        sel = self.tree.selection()
        return self._keys.get(sel[0]) if sel else None

    def _selected(self, _event=None) -> None:
        key = self.selected_key()
        if key is not None:
            self.on_select(key)

    def _toggle(self) -> None:
        key = self.selected_key()
        if key is not None:
            self.on_toggle(key)

