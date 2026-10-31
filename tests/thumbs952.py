r"""V9.5.2 check of the cover squares with the real songs folder (read-only; thumbnails go to MONTAGER_DATA): both lists, scrolling, row height, background loading.
python tests/thumbs952.py     (MONTAGER_DATA = a folder with a COPY of config.json)"""
import queue
import sys
import time
import warnings
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _root                                                                                  # noqa: E402
sys.path.insert(0, str(_root.find_root()))
warnings.simplefilter("ignore")
import montage as M                                                                           # noqa: E402

app = M.App(0, startup=False)
app.root.geometry("1400x900")
app.root.update()
t0 = time.time()
app.load_matches()
n_done = 0


def pump():
    global n_done
    while True:
        try:
            k, v = app.q.get_nowait()
        except queue.Empty:
            break
        if k == "call":
            v()
            n_done += 1
pump()
app.root.update()
print(f"list filled in {time.time() - t0:.1f} s (rows: Songs tab {len(app.mtree.get_children())}, picker {len(app.stree.get_children())})")
for name, tree in (("Songs tab", app.mtree), ("picker", app.stree)):
    try:
        app.nb.select(app.tabs["Songs"] if name == "Songs tab" else app.tabs["Manual"])
    except Exception as ex:                                                                   # noqa: BLE001
        print("tab select:", ex)
    app.root.update()
    rh = M.ttk.Style().lookup("Treeview", "rowheight")
    kids = tree.get_children()
    t1 = time.time()
    while time.time() - t1 < 12:                      # the visible rows get their squares in the background
        pump()
        app.root.update()
        vis = [tree.identify_row(y) for y in range(0, tree.winfo_height(), 24)]
        vis = [v for v in vis if v]
        if not M.THUMBS_ON[0] or (vis and all(v in app._thumb["photos"] or v == "auto" for v in vis)):
            break
    got = sum(1 for v in vis if str(tree.item(v, "image")) not in ("", str(app._thumb["blank"]))) if M.THUMBS_ON[0] else 0
    print(f"{name}: rowheight {rh}, square {app._thumb['S'] if M.THUMBS_ON[0] else 0} px, {len(vis)} rows in view, {got} with a cover after {time.time() - t1:.1f} s")
    # scrolling: time of one scroll step (update included) over the whole list
    ts = []
    for i in range(60):
        t2 = time.perf_counter()
        tree.yview_moveto(i / 60.0)
        app.root.update()
        ts.append(time.perf_counter() - t2)
    pump()
    print(f"{name}: scroll steps over {len(kids)} rows: median {sorted(ts)[30] * 1000:.1f} ms, worst {max(ts) * 1000:.1f} ms")
if M.THUMBS_ON[0]:
    print("squares made so far:", len(app._thumb["photos"]), "| thumb files:", len(list((M.DATA / 'thumbs').rglob('*.png'))))
app.root.destroy()
