"""V6.1 theme registry check (no ttk dependence, no render):  xvfb-run -a -s "-screen 0 1920x1200x24" python3 test_v61.py

Builds the app, opens a popup created later (changelog), then cycles all 12 accent x base combinations in the SAME window, alternating
grey / black, and after every switch asserts that every classic tk widget has the bg / fg / highlightbackground of its role in the
CURRENT combination. Prints the number of stale widgets (summed over all switches)."""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("MONTAGER_DATA", tempfile.mkdtemp(prefix="montager_v61_"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import tkinter as tk

import montage as M

CLASS_ROLE = {"Tk": "window", "Toplevel": "window", "Frame": "window", "Canvas": "window", "Label": "label", "Text": "text",
              "Entry": "entry", "Spinbox": "entry", "Listbox": "text", "Panedwindow": "pane"}
EXPECT = {"window": {"bg": "bg", "highlightbackground": "bg"}, "label": {"bg": "bg", "fg": "fg", "highlightbackground": "bg"},
          "text": {"bg": "field", "fg": "fg", "highlightbackground": "border"}, "entry": {"bg": "field", "fg": "fg", "highlightbackground": "border"},
          "pane": {"bg": "border"}}
SEQ = [("lime", "grey"), ("yellow", "black"), ("orange", "grey"), ("red", "black"), ("pink", "grey"), ("purple", "black"),
       ("lime", "black"), ("yellow", "grey"), ("orange", "black"), ("red", "grey"), ("pink", "black"), ("purple", "grey")]


def stale(app, pal):
    bad, n = [], 0
    reg = getattr(app, "_reg", {})
    for w in app._tk_widgets():
        role = CLASS_ROLE.get(w.winfo_class())
        if role is None or reg.get(str(w)) == "fixed":
            continue
        n += 1
        for opt, key in EXPECT[role].items():
            try:
                v = str(w.cget(opt)).lower()
            except tk.TclError:
                continue
            if v != pal[key].lower():
                bad.append(f"{w.winfo_class()} {w} {opt}={v} want {pal[key]}")
    return bad, n


def main():
    app = M.App(0, startup=False)
    app.show_changelog()
    app.root.update()
    tk.Frame(app.root)                                            # an unregistered widget created later: class fallback must cover it
    total, widgets = 0, 0
    fails = []
    for acc, base in SEQ:
        app.cfg["accent"], app.cfg["base"] = acc, base
        app.retheme(acc, base)
        app.root.update()
        bad, n = stale(app, M.make_palette(acc, base))
        total += len(bad)
        widgets = n
        if bad:
            fails.append(f"{acc}/{base}: {len(bad)} stale, e.g. {bad[:3]}")
    print(f"classic widgets checked per switch: {widgets}; switches: {len(SEQ)}; stale widget checks in total: {total}")
    for f in fails[:6]:
        print("  ", f)
    print("PASS" if not total else "FAIL")
    app.root.destroy()
    return 0 if not total else 1


if __name__ == "__main__":
    sys.exit(main())
