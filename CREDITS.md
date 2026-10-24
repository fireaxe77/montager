# Credits and third-party licenses

Montager is a single Python app. It ships its own code plus six fonts; everything else is installed separately by the user.

## Bundled: fonts (SIL Open Font License 1.1)

Used unmodified for the intro / outro titles. Full license text and copyright lines: [`fonts/OFL.txt`](fonts/OFL.txt).

| Font | Copyright |
|---|---|
| Anton | 2020 The Anton Project Authors |
| Bebas Neue | 2019 The Bebas Neue Project Authors (Dharma Type) |
| Montserrat | 2011 The Montserrat Project Authors |
| Oswald | 2016 The Oswald Project Authors |
| Playfair Display | 2017 The Playfair Display Project Authors (Reserved Font Name "Playfair Display") |
| Unbounded | 2022 The Unbounded Project Authors |

## Not bundled: installed by the user

| Component | Used for | License |
|---|---|---|
| [Python](https://www.python.org) + tkinter | the app and its window | PSF License |
| [FFmpeg](https://ffmpeg.org) | reading clips, rendering | LGPL / GPL (depends on the build) |
| [RapidOCR](https://github.com/RapidAI/RapidOCR) (`rapidocr-onnxruntime`) + ONNX Runtime | reading the killfeed | Apache 2.0 / MIT |
| [NumPy](https://numpy.org), [SciPy](https://scipy.org) | maths | BSD |
| [OpenCV](https://opencv.org) (`opencv-python`) | frames and images | Apache 2.0 (+ MIT wrapper) |
| [librosa](https://librosa.org), [soundfile](https://github.com/bastibe/python-soundfile) | song analysis | ISC / BSD |
| [mutagen](https://github.com/quodlibet/mutagen) | song tags | GPL-2.0-or-later |
| [RapidFuzz](https://github.com/rapidfuzz/RapidFuzz) | fuzzy name / title matching | MIT |
| [Pillow](https://python-pillow.org) | intro titles | MIT-CMU (HPND) |
| [sv-ttk](https://github.com/rdbende/Sun-Valley-ttk-theme) (optional) | the dark theme | MIT |
| [psutil](https://github.com/giampaolo/psutil), [fontTools](https://github.com/fonttools/fonttools), [Send2Trash](https://github.com/arsenetar/send2trash) (optional) | memory readings, font checks, Recycle Bin | BSD / MIT / BSD |

Song lists are exported with [Exportify](https://exportify.app) (a separate website; not part of Montager).

Valorant, Counter-Strike 2 and Rainbow Six Siege are trademarks of their owners (Riot Games, Valve, Ubisoft). Montager is a
fan-made tool and is not affiliated with or endorsed by them.
