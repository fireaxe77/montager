"""SONGMAPV2 (V6.9.5): an isolated song-map analysis. Nothing in the app imports this package except the dispatcher
`get_songmap()` in montage.py. V1 (`build_song_map` / `analyse_song`) is untouched.

Three separate analyses: (1) beat grid (grid.py) = where the rhythm is, (2) events (events.py) = what happens on / around the grid,
(3) sections (sections.py) = which part of the song it is. adapter.py turns the result into the exact dict shape V1 produces."""
ALGO_V = "v2.0"                 # bump to invalidate ONLY the V2 cache
CACHE_NAME = "song_cache_v2.json"
CACHE_NS = "songmap_v2"
ANALYSIS_CAP_S = 60.0           # hard cap per song (a 4 minute song takes a few seconds)

from . import timebase, grid, events, sections, adapter   # noqa: E402,F401
try:
    from .build import build_songmap_v2, file_signature, cache_key     # noqa: E402,F401
except ImportError:        # (while the package is being assembled)
    pass
