# montager
Valorant / CS2 kill-montage builder. Run `python montage.py` (GUI). Setup instructions are in the comment block at the top of `montage.py`. Kills are read from the killfeed with RapidOCR (offline): `python -m pip install --user rapidocr-onnxruntime`. `python montage.py smoketest` checks the GUI buttons and the OCR.

V5: song map (beat grid, sections, drops) drives the cut; `python montage.py smoketest` includes a real render whose kill-to-beat sync is measured from the output file; `python montage.py detectcheck` compares V4 and V5 kill detection on your cached OCR data. V4 stays restorable: `git checkout v4-backup`.
