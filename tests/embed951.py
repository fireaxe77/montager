r"""V9.5.1 embed check on TEMPORARY COPIES of 2 downloaded songs (real Deezer cover): tags readable by a tag reader, Windows shows the cover (Explorer's own thumbnail +
property columns), the app's exact title + artist matching still counts the copies; the copies are deleted afterwards.
python tests/embed951.py [YYYY-MM-DD]     (MONTAGER_DATA = a folder with a copy of config.json)"""
import datetime
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _root import find_root
sys.path.insert(0, str(find_root(__file__)))
import montage as m
import ytsongs as y

PS_THUMB = r'''
Add-Type -ReferencedAssemblies System.Drawing -TypeDefinition @"
using System; using System.Drawing; using System.Runtime.InteropServices;
public class Th {
  [ComImport, Guid("bcc18b79-ba16-442f-80c4-8a59c30c463b"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  interface IShellItemImageFactory { [PreserveSig] int GetImage(SIZE size, int flags, out IntPtr phbm); }
  [StructLayout(LayoutKind.Sequential)] struct SIZE { public int cx, cy; }
  [DllImport("shell32.dll", CharSet=CharSet.Unicode, PreserveSig=false)]
  static extern void SHCreateItemFromParsingName(string path, IntPtr pbc, ref Guid riid, out IShellItemImageFactory ppv);
  [DllImport("gdi32.dll")] static extern bool DeleteObject(IntPtr h);
  public static string Save(string file, string png, int px) {
    Guid g = new Guid("bcc18b79-ba16-442f-80c4-8a59c30c463b"); IShellItemImageFactory f;
    SHCreateItemFromParsingName(file, IntPtr.Zero, ref g, out f);
    SIZE s = new SIZE(); s.cx = px; s.cy = px; IntPtr hb;
    int hr = f.GetImage(s, 0x0, out hb);   // SIIGBF_RESIZETOFIT, thumbnail allowed
    if (hr != 0) return "HRESULT " + hr;
    Bitmap b = Bitmap.FromHbitmap(hb); b.Save(png, System.Drawing.Imaging.ImageFormat.Png); DeleteObject(hb); return "ok " + b.Width + "x" + b.Height;
  }
}
"@
[Th]::Save($args[0], $args[1], 256)
'''


def main():
    day = sys.argv[1] if len(sys.argv) > 1 else "2026-10-31"
    cfg = m.load_config()
    csvp, rows, _ = m.read_playlist(cfg)
    meta = y.read_meta(csvp)
    audio = [a for a in m.scan_audio(cfg) if datetime.date.fromtimestamp(os.path.getmtime(a["path"])).isoformat() == day]
    matched, _un = m.match_playlist(rows, audio, cfg, loose=False)
    pick = [x for x in matched if x[0]["title"] in ("Heartbreak", "Hey Mama")][:2] or matched[:2]
    td = Path(tempfile.mkdtemp(prefix="embed951_"))
    songs = td / "songs"
    songs.mkdir()
    data = os.environ["MONTAGER_DATA"]
    try:
        for r, a, sc in pick:
            dst = songs / Path(a["path"]).name
            shutil.copy2(a["path"], dst)
            tg = y.track_tags(r, meta)
            cover, src, note = y.cover_for(dict(r, isrc=tg["isrc"]), data)
            added = y.apply_tags(dst, tg, cover)
            from mutagen.id3 import ID3
            t = ID3(str(dst))
            ap = t.getall("APIC")
            print(f"\n{dst.name}\n  cover source: {src} {note}; fields added: {added}")
            print("  tag reader:", {k: str(t[k]) for k in ("TIT2", "TPE1", "TALB", "TCON", "TPUB", "TSRC") if k in t}, "year", str(t.get("TDRC") or t.get("TYER")),
                  "| cover", [(x.type, x.mime, y.image_size(x.data), len(x.data) // 1024) for x in ap])
            png = td / (dst.stem[:20].replace(" ", "_") + ".png")
            psf = td / "thumb.ps1"
            psf.write_text(PS_THUMB, encoding="utf-8")
            r_ = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(psf), str(dst), str(png)], capture_output=True, text=True)
            print("  Windows thumbnail:", (r_.stdout or r_.stderr).strip()[-200:], "->", png if png.exists() else "none")
            if png.exists():
                keep = Path(os.environ.get("EMBED_OUT", td)) / png.name
                if keep != png:
                    shutil.copy2(png, keep)
                    print("  thumbnail copy:", keep)
        # Windows property columns (the Explorer details)
        ps = ("$sh=New-Object -ComObject Shell.Application; $ns=$sh.NameSpace('%s'); foreach($i in $ns.Items()){ $n=$i.Name; "
              "$o=@(); foreach($c in 13,14,15,16,32,21){ $o+=($ns.GetDetailsOf($i,$c)) }; Write-Output ($n + ' | ' + ($o -join ' | ')) }" % str(songs).replace("'", "''"))
        r_ = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, encoding="utf-8", errors="replace")
        print("\nWindows Explorer columns (artist, album, year, track#, genre...):\n" + r_.stdout.strip())
        audio2 = m.scan_audio(dict(cfg, mp3_dir=str(songs)), rescan=True)
        mt, un = m.match_playlist(rows, audio2, cfg, loose=False)
        print("\napp matching on the copies:", [(r["title"], sc) for r, a, sc in mt])
    finally:
        out = os.environ.get("EMBED_OUT")
        shutil.rmtree(songs, ignore_errors=True)
        print("copies deleted:", not songs.exists())


if __name__ == "__main__":
    main()
