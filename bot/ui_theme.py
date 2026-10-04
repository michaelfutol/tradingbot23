"""Trade23's presentation-only theme and bundled asset lookup."""

import sys
import ctypes
from pathlib import Path
import tkinter as tk
from tkinter import ttk

BG = "#111214"
SURFACE = "#191c1f"
RAISED = "#24282c"
BORDER = "#343b40"
TEXT = "#edf1f4"
MUTED = "#a0aab2"
ACCENT = "#59dcb2"
SUCCESS = "#47c997"
DANGER = "#ff777d"
FONT = "Segoe UI" if sys.platform == "win32" else "Helvetica"


def asset_path(name):
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    return root / "assets" / name


def apply_window_brand(root):
    if sys.platform == "win32":
        set_app_id = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID
        set_app_id.argtypes = [ctypes.c_wchar_p]
        set_app_id.restype = ctypes.c_long
        set_app_id("FutolTech.Trade23.Paper")
    images = [tk.PhotoImage(master=root, file=str(asset_path(f"ui/mark-{size}.png")))
              for size in (32, 64, 256)]
    root.iconphoto(True, *images)
    root._trade23_icon_images = images


def configure_styles(root):
    root.configure(bg=BG)
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", background=BG, foreground=TEXT, font=(FONT, 10),
                    bordercolor=BG, lightcolor=BG, darkcolor=BG)
    style.configure("TFrame", background=BG)
    style.configure("TLabel", background=BG, foreground=TEXT)
    style.configure("Header.TLabel", font=(FONT, 11, "bold"))
    style.configure("Big.TLabel", font=(FONT, 24, "bold"), foreground=TEXT)
    style.configure("Mode.TLabel", font=(FONT, 10), foreground=ACCENT)
    style.configure("Btn.TButton", background=RAISED, foreground=TEXT,
                    bordercolor=BORDER, lightcolor=RAISED, darkcolor=RAISED,
                    borderwidth=1, relief="flat", padding=(12, 8), font=(FONT, 9))
    style.map("Btn.TButton", background=[("active", "#30363b"), ("disabled", SURFACE)],
              foreground=[("disabled", "#77828b")])
    style.configure("Primary.TButton", background=ACCENT, foreground=BG,
                    bordercolor=ACCENT, lightcolor=ACCENT, darkcolor=ACCENT,
                    padding=(14, 8), font=(FONT, 9, "bold"))
    style.map("Primary.TButton", background=[("active", "#7ae6c3"), ("disabled", RAISED)],
              foreground=[("disabled", MUTED)])
    style.configure("Danger.TButton", background=RAISED, foreground=DANGER,
                    bordercolor=BORDER, lightcolor=RAISED, darkcolor=RAISED,
                    padding=(12, 8), font=(FONT, 9))
    style.configure("Treeview", background=SURFACE, foreground=TEXT,
                    fieldbackground=SURFACE, borderwidth=0, relief="flat",
                    bordercolor=SURFACE, lightcolor=SURFACE, darkcolor=SURFACE,
                    font=("Consolas", 10), rowheight=32)
    style.configure("Treeview.Heading", background=RAISED, foreground=MUTED,
                    borderwidth=0, relief="flat", padding=(8, 9), font=(FONT, 9))
    style.map("Treeview", background=[("selected", "#24483d")],
              foreground=[("selected", TEXT)])
    style.map("Treeview.Heading", background=[("active", "#30363b")])
    style.configure("TNotebook", background=BG, borderwidth=0, bordercolor=BG,
                    lightcolor=BG, darkcolor=BG, tabmargins=(16, 0, 0, 0))
    style.configure("TNotebook.Tab", background=BG, foreground=MUTED, borderwidth=0,
                    bordercolor=BG, lightcolor=BG, darkcolor=BG,
                    padding=(18, 10), font=(FONT, 10))
    style.map("TNotebook.Tab", background=[("selected", SURFACE), ("active", RAISED)],
              foreground=[("selected", ACCENT), ("active", TEXT)],
              expand=[("selected", (0, 0, 0, 0))])
    style.layout("TNotebook.Tab", [("Notebook.padding", {"sticky": "nswe", "children": [
        ("Notebook.label", {"sticky": "nswe"})]})])
    style.configure("TCheckbutton", background=BG, foreground=TEXT, padding=(0, 4),
                    indicatorbackground=RAISED, indicatorforeground=ACCENT)
    style.map("TCheckbutton", background=[("active", BG)],
              indicatorbackground=[("selected", ACCENT)])
    for name in ("TEntry", "Settings.TEntry", "TCombobox", "Settings.TCombobox"):
        style.configure(name, fieldbackground="#f5f7f8", foreground=BG, background="#f5f7f8",
                        arrowcolor=BG, insertcolor=BG, bordercolor=BORDER, padding=(6, 6),
                        selectbackground=ACCENT, selectforeground=BG)
        style.map(name, fieldbackground=[("disabled", RAISED), ("readonly", "#f5f7f8")],
                  foreground=[("disabled", MUTED), ("readonly", BG)])
    style.configure("TSeparator", background=BORDER)
    for name in ("Vertical.TScrollbar", "Horizontal.TScrollbar"):
        style.configure(name, background=RAISED, troughcolor=BG, bordercolor=BG,
                        arrowcolor=MUTED, lightcolor=RAISED, darkcolor=RAISED, borderwidth=0)
    root.option_add("*TCombobox*Listbox.background", "#f5f7f8")
    root.option_add("*TCombobox*Listbox.foreground", BG)
    root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
    root.option_add("*TCombobox*Listbox.selectForeground", BG)
    return style
