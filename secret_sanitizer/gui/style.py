"""Farben und Theme der Oberfläche (Logo-Set „kobalt“ der Marke slide).

Ink und Weiß tragen den Text, Flächen sind leichte Abstufungen davon. Kobalt
ist nur Akzent: die Hauptaktion je Reiter, angehakte Kästchen, Schalter und
Fortschritt. Die übrigen Werte stehen in theme.json.
"""

from __future__ import annotations

from pathlib import Path

THEME_FILE = Path(__file__).with_name("theme.json")

KOBALT = "#3B5BFF"
KOBALT_HOVER = "#2E4AE6"

# (hell, dunkel)
INK_WHITE = ("#15151B", "#FFFFFF")
MUTED = ("#5B5B5F", "#B4B4B6")
SURFACE_2 = ("#EFEFF0", "#28282D")
BORDER = ("#E3E3E4", "#313136")
WARN = "#E6A23C"

# Hauptaktion je Reiter: Kobalt mit weißer Schrift, ohne Rahmen
PRIMARY = {"fg_color": KOBALT, "hover_color": KOBALT_HOVER, "text_color": "#FFFFFF",
           "border_width": 0}
# Gefährliche Aktion (Abbrechen, Löschen)
DANGER = {"fg_color": "#C0392B", "hover_color": "#A93226", "text_color": "#FFFFFF",
          "border_width": 0}
