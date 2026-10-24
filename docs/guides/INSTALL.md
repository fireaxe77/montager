# Installing Montager on Windows

Short version: [README > Install](../../README.md#install). This page has the details.

## 1. Python 3.12 (64-bit)

1. Download the **Windows installer (64-bit)** for Python 3.12 from <https://www.python.org/downloads/windows/>.
2. In the installer tick **"Add python.exe to PATH"**, then **Install Now**. The default install includes tcl/tk (tkinter), which Montager's window needs.
3. Check it in a new terminal (cmd):
   ```bash
   python --version
   ```
   It should print `Python 3.12.x`.

- Already have Python but tkinter is missing? Re-run the installer, choose **Modify**, tick **tcl/tk and IDLE**.
- The Microsoft Store Python also works, but the python.org one is what Montager is tested with.

## 2. FFmpeg

Montager calls `ffmpeg` and `ffprobe` for reading clips and rendering. Pick one:

**A) winget (recommended, no admin)**
```bash
winget install --id Gyan.FFmpeg -e --scope user
```
Close and reopen the terminal afterwards so the new PATH is used.

**B) Manual download**
1. Download `ffmpeg-release-essentials.zip` from <https://www.gyan.dev/ffmpeg/builds/>.
2. Unzip it and copy `ffmpeg.exe` and `ffprobe.exe` from its `bin` folder into `montage_data\bin` inside the Montager folder (create the folder if needed). Montager adds that folder to its own PATH; nothing system-wide changes.

Check: `ffmpeg -version` prints a version line.

## 3. Python packages

From the Montager folder:
```bash
python -m pip install --user numpy opencv-python Pillow librosa soundfile scipy mutagen rapidfuzz rapidocr-onnxruntime sv-ttk psutil fonttools
```

| Package | Needed for | Required? |
|---|---|---|
| numpy, scipy | maths | yes |
| opencv-python | reading frames, image work | yes |
| Pillow | intro / outro titles | yes |
| librosa, soundfile | song analysis (beats, drops) | yes |
| mutagen | song tags and lengths | yes |
| rapidfuzz | fuzzy name / song matching | yes |
| rapidocr-onnxruntime | reading the killfeed (OCR; pulls in onnxruntime) | yes |
| sv-ttk | the dark Sun Valley theme | recommended (a plain theme is used without it) |
| psutil | free-memory readings during renders | recommended |
| fonttools | fallback font for titles in other alphabets | recommended |
| Send2Trash | the trash icon uses the Recycle Bin through it | optional (works without it) |

If a required package is missing, Montager offers to install it when it starts.

Versions tested by the developer (October 2026): Python 3.12.10, numpy 2.5, opencv-python 5.0, librosa 1.0, scipy 1.18,
rapidocr-onnxruntime 1.4.4, onnxruntime 1.20, Pillow 12.3, FFmpeg 2025-02 essentials build. Newer versions should work.

## 4. The OCR engine

There is nothing extra to install: `rapidocr-onnxruntime` brings its own models and runs offline on the CPU. The setup check
(`python setup_check.py`) and Troubleshoot > Selfcheck both run a quick test read.

## 5. NVIDIA GPU encoder (optional)

With an NVIDIA GPU and a current driver, Quality **"Fast (NVENC)"** encodes on the GPU. The setup check runs a 0.2 s test
encode. Without NVENC use **"Max (x264)"**: the same montage, encoded on the CPU, slower.

## 6. Montager itself

- **ZIP**: download it from the [latest release](https://github.com/fireaxe77/montager/releases/latest) and unzip it to a normal folder (not inside "Program Files").
- **git**: `git clone https://github.com/fireaxe77/montager.git` (update later with `git pull`).

Then double-click `Start_Montager.bat`.

## What the launcher does

`Start_Montager.bat`:
1. `first_run.py`: only when `montage_data\config.json` does **not** exist yet, creates it from `config.example.json` (your user folder filled in) and creates an empty songs folder `%USERPROFILE%\Music\Montager songs`. An existing config is never touched.
2. `setup_check.py`: read-only check of Python, packages, FFmpeg, OCR, GPU encoder, folders and player names. Problems are listed with a fix, and the window waits for a key.
3. Starts Montager the same way as `Montager.vbs` (`pythonw montage.py`, no console window).

You can also start Montager directly with `Montager.vbs`, or `python montage.py` in a terminal (shows errors there).

## Where your data lives

Everything Montager stores is in `montage_data\` next to `montage.py`: settings (`config.json`), scan caches, song maps,
used-clip flags, logs. Your clips and songs are only read, never changed (except the move / trash icons in the clip list,
which act only when you click them). To start over, close Montager and rename `montage_data`.
