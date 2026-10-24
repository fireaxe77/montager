# Third-party software in the Montager download

Montager itself is MIT-licensed (`LICENSE`). The Windows download (installer / portable ZIP) bundles the programs and libraries
below so nothing else has to be installed. All of them allow redistribution. Each package's own license file is included
in `_internal\<package>-<version>.dist-info\` (and `_internal\ffmpeg\LICENSE` for FFmpeg).

| Component | License | Notes |
|---|---|---|
| Python 3.12 runtime, tkinter, Tcl/Tk | PSF License; Tcl/Tk BSD-style | bundled by PyInstaller |
| FFmpeg + ffprobe (gyan.dev essentials build, includes x264) | **GPL-3.0** | separate programs, unmodified; source: `_internal\ffmpeg\FFMPEG_SOURCE.txt` |
| RapidOCR (`rapidocr-onnxruntime`) + its OCR models (PaddleOCR) | Apache-2.0 | the killfeed OCR engine, runs offline |
| ONNX Runtime | MIT | runs the OCR models |
| OpenCV (`opencv-python`) | Apache-2.0 (wrapper MIT) | includes FFmpeg libraries (LGPL) inside OpenCV |
| NumPy, SciPy | BSD-3-Clause | |
| librosa | ISC | song analysis |
| numba, llvmlite | BSD-2-Clause (llvmlite: BSD + LLVM Apache-2.0 with exceptions) | used by librosa |
| scikit-learn, joblib, threadpoolctl | BSD-3-Clause | used by librosa |
| soundfile (+ libsndfile) | BSD-3-Clause (libsndfile LGPL-2.1, as a separate DLL) | |
| soxr (python-soxr + libsoxr) | LGPL-2.1+ | resampling, used by librosa |
| audioread, pooch, lazy_loader, decorator, msgpack | MIT / BSD | used by librosa |
| mutagen | GPL-2.0-or-later | song tags |
| RapidFuzz | MIT | |
| Pillow | MIT-CMU (HPND) | |
| fontTools | MIT | |
| sv-ttk (Sun Valley theme) | MIT | |
| psutil | BSD-3-Clause | |
| PyYAML, Shapely, pyclipper, six | MIT / BSD / Boost | used by RapidOCR |
| Fonts: Anton, Bebas Neue, Montserrat, Oswald, Playfair Display, Unbounded | SIL OFL 1.1 | `fonts\OFL.txt` |
| PyInstaller bootloader | GPL-2.0 with the bootloader exception | allows any license for the packaged app |

Because the download contains GPL components (FFmpeg as separate programs, mutagen as a library), the download as a whole can be
redistributed under the GPL's terms; Montager's own source code stays MIT and is public at https://github.com/fireaxe77/montager.

Valorant, Counter-Strike 2 and Rainbow Six Siege are trademarks of Riot Games, Valve and Ubisoft. Montager is not affiliated with them.
