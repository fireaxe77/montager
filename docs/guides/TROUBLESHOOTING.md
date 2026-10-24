# Troubleshooting

Start with the setup check: double-click `Start_Montager.bat`, or run `python setup_check.py` in the Montager folder.
It only reads and lists every problem with its fix. Inside the app: **Troubleshoot > Selfcheck**.

## The app does not start

| Symptom | Fix |
|---|---|
| "Python was not found" | Install Python 3.12 (64-bit) from python.org with "Add python.exe to PATH" ticked. |
| Nothing opens | Run `python montage.py` in a terminal in the Montager folder; the error is printed there. |
| `No module named tkinter` | Re-run the python.org installer > Modify > tick "tcl/tk and IDLE". |
| "Missing packages" dialog | Click Yes (installs for your user only), then restart Montager. |

## Kills are not found (or wrong ones are)

1. **Player names** (Settings > Player names): exactly as the killfeed shows them. Several names separated by `;`.
2. **Troubleshoot > Self-test detection**: shows the rows the OCR read in your scanned clips and why each counted or not.
3. **Killfeed region**: if Self-test reads few or no rows, calibrate it (README > [Killfeed calibration](../../README.md#killfeed-calibration)).
4. **Black bars**: 4:3 / stretched recordings need Troubleshoot > Black bars > Re-measure.
5. **Clip limits**: clips over 60 s or 60 MB are skipped by default (Settings > Scanning and detection).
6. **Rescan one clip**: Troubleshoot > Clips > pick the clip > Rescan this clip.
7. **Clear kill cache** (Troubleshoot) re-scans everything. Slow; only when the above did not help.

## Songs

| Symptom | Fix |
|---|---|
| "no Exportify CSV" | Put the `.csv` from exportify.app into the Exportify CSV folder (Settings > Folders). The newest one is used. |
| Song not in the list | It needs both a file in the MP3 folder and a row in the CSV with the same title and at least one same artist. Songs tab > "Change match for selected file" matches by hand. |
| A song is flagged CHECK | The match is uncertain (score under 85). Play it, then fix it with Change match if it is wrong. |
| Wrong tempo / drops | Songs tab > Song map of selected file shows what was detected. |

## Rendering

| Symptom | Fix |
|---|---|
| `ffmpeg not found` | Install FFmpeg (see [INSTALL.md](INSTALL.md#2-ffmpeg)) and restart Montager. |
| NVENC errors | Update the NVIDIA driver, or Settings / Manual > Quality "Max (x264)". |
| Out of memory / very slow | Close other heavy programs. Effects "Default" and a shorter length use less. A 110 s render with effects can use about 10 GB of RAM. |
| Audio too loud / quiet | Settings > Game audio: the game audio level under the music (0-1, per game) and which audio track is the game sound. |

## Logs

- Troubleshoot > **Open logs**, or `montage_data\logs\montage.log`.
- Each montage has its plan next to it: `<output folder>\<Game>\logs\<montage>.txt`.
- When you report a problem, include the end of `montage.log` and say which game, resolution and recorder you use.
  Check it for anything private (folder names, player names) before sharing.
