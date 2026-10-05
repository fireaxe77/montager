# Changelog

Newest first. Rebuilt from the git history (commit messages and diffs); nothing here is guessed. Where the history does not say what a
version contained, the entry says "Details not recorded". Dates are the commit dates.

**Rule:** every new version must add an entry at the top of this file (see CLAUDE.md).

## V6.7.2 - 2026-10-05
- CS2 over-count on real garbled reads (CS2-only branches; Valorant kill results untouched). Row tracking first: a CS2 killfeed row is tracked by position. When a new row pushes the list the shift is measured text-independently (the distance most live tracks agree on; a new row at an old height does not count as "nothing moved"), every live track moves with it, and a track survives OCR misses and misreads for 1.5 s; a row that was already on screen in the previous OCR frame at the track's height (or moved with the list) is the same kill however it is read. New kills come only from new appearances. Names are a fallback (`cs2_same_victim`): the V6.7 normalisation plus, for garbled reads only (digits, spaces, mixed capitals), a long common core after folding vowels and the digit / Cyrillic look-alikes (3/з->e, 4/ч->a, 6/б->b, 9->a, 0->o); clean different names (Kristof/Kristina, Nika/Mika) and names differing in one digit (player1/player2) stay different. Fixture of the 8 stored reads of "Replay 2026-06-25 01-27-36.mov" (OO TEKAAB / due TaKAan / ouO TaKAOD / OuG TaKAaB, aapn3akAaM / aapa3kAeM / 3apaa9KAaM, Ruat Cohle): 5-8 kills before, 3 now.
- Length 150 s: the slider (80-150 since V6.1.3) was still clamped inside `plan_montage`: a fixed length was `max(30, min(120, slider))` and the take cap `min(120, target*1.1)`, so 150 reached the planner as 120 (plus the unused `optimal_length` 30-120 and the "120 s" comment). Both now use `LEN_MAX_S` (150). Also, a fixed length stopped well below the slider because only Optimal filled clips in front of the build-up; a fixed length now fills the same way (up to the slider value, never past the song, never padded: with few events it stays shorter). The log shows the real value ("slider 150 s"). Weekly minimum 60 s and Optimal 80-150 s are unchanged. Unused and left as is: `pick_window` (60-120 s song window, no callers).
- New `test_v672.py` (fixtures; real-cache checks run only when montage_data exists). `test_v67.py` now measures against V6.5.2 (031cb64), since origin/main carries V6.7.

## V6.7 - 2026-10-05
- CS2 kill registration only (Valorant results are byte-identical; detection/OCR, planner, effects, zoom, render, theme, song matching and settings untouched; every change is a `game == "cs2"` branch). Knife and revive/resurrect stay Valorant-only.
- Over-count: CS2 victim names are now compared after OCR-confusion normalisation (Latin/Cyrillic look-alikes, l/I/1/|, O/0/D, rn/m, vv/w, case, spaces and punctuation ignored; a difference touching a digit means a different player; similarity >= 82 = the same player). A killfeed row that was already on screen in the previous OCR frame at the same height - or at the height the whole list shifted to when a new row pushed it - is the same kill however it is read; the same victim cannot be killed twice within one round (115 s); duplicate / jumbled re-read and variant merging use the normalised names. Applied from the cached raw OCR rows, so existing clips update without a rescan.
- Under-count: the gunshot check of a CS2 clip now analyses the audio track the clip has sound on (the same pick as the plan: Settings > Audio mode / game audio track, a silent track is never chosen) instead of always track 1 (cached under `o1c<track>`; Valorant keeps `o1`). A CS2 clip with no gunshot on any track no longer rejects a read kill for "no gunshot to confirm it" (the kill is kept, logged as "no gunshot heard (kept)").
- Killfeed region: unchanged. It is a fraction of the content rectangle (CS2 0.58-1.0 x 0.03-0.40), so 1280x960 and 1920x1080 clips crop the same part of the picture.
- New `test_v67.py` (fixtures from the reported reads; compares with origin/main; Valorant kill counts and timestamps must be identical).

## V6.5.2 - 2026-10-05
- Manual clip list: clicking an EMPTY Used cell now flags that clip as used with today's date (the same flag a finished render writes, so the weekly pick - including its reuse of previously used clips - the Used filter and "Include used clips" treat it as used), saves it, refreshes the row and logs "flagged <clip>". Clicking a filled Used cell still unflags it. The click never ticks or unticks the row. New `test_v652.py`.

## V6.5.1 - 2026-10-05
- Weekly / Auto minimum length 60 s (Manual unchanged). Order as before: this week's new clips, then older UNUSED clips (best multikills first, then singles), target 80-150 s. If the unused material cannot reach 60 s, previously used events are reused: best-scoring first among those whose last use is the oldest; never a clip of the game's previous montage (the latest montage in the history) and never a clip twice in one montage. The log gets "reused N previously used clip(s) to reach the 60 s minimum"; if even the whole library cannot reach 60 s the montage is made from what exists and the log says why with numbers. A chosen song with less than 60 s of music is replaced by the next best-ranked song that has it. Reused clips get a new used date only after a successful render (as every clip). Before, only unused clips were ever picked ("only ~23 s of unused material - the montage is shorter" after many test renders), and "no unused clips left" skipped the game.
- Manual clip list: new "Unflag all" button (asks "Unflag all N used clips (Valorant and CS2)?", writes a dated backup `used_flags_backup_<date_time>.json` (and `used_clips_backup_...`) next to the flags file, refreshes the list and logs "unflagged N clips (backup: <file name>)"); clicking the Used date of a row unflags that clip at once (saved, row refreshed, "unflagged <clip>" in the log; an empty Used cell does nothing; the click never ticks or unticks the row). Unflagging also removes the clip from the montage history that would flag it again.
- New `test_v651.py` (generated data, stubbed render).

## V6.5 - 2026-10-05
- Song matching only. Files named "Title - Artist1, Artist2.mp3" were matched to wrong playlist tracks by the fuzzy scorer (WRatio + a global one-to-one assignment that also handed leftover tracks to unrelated files, with scores like 85 shown as "ok"). The rule is now exact: the file name is split on its LAST " - " (title before, artist list after, split on ", " and " & "; the MP3 title / artist tags are used when the name cannot be parsed); both sides are normalised the same way (NFKC, casefold, one kind of quote and dash, characters a file name cannot hold dropped, single spaces; Cyrillic, Japanese and every other character kept). **ok / 100** only when the title is identical AND at least one artist is identical. **CHECK (under 85, score 80)** only when an artist matches and the title is the same after removing bracketed or dash suffixes ("(feat. ...)", "- Radio Edit", "- Remix", "(Sped Up)"); confirm with Change match. Anything else is NO MATCH: never an artist-only or title-only match, never a leftover track. One file per track: of several files that match a track exactly the larger is kept and the others get the flag DUPLICATE (Songs > matches and song_matches.csv). Manual matches ("Change match") are applied first and kept.
- The match cache version is 2: caches written by older versions are ignored, so every automatic match is recomputed once on the next launch (manual matches live in the config and are not affected). The cache now also stores the duplicate flags. Because the rule is exact and cheap, a changed folder / CSV recomputes all matches instead of the incremental match of V6.1.2.
- New `test_v65.py`.

## V6.1.5 - 2026-10-05
- Manual tab: the long multi-line summary above the log is now ONE fixed-height line without wrapping ("30 clips ticked \u00b7 100 kills \u00b7 montage 150 s \u00b7 song: Atlantis \u00b7 hype"), cut with "\u2026" when it does not fit the width, so it never changes the height of anything around it. The full summary (clips that didn't fit, clips that can't form a take and why, song section, usable events) is written to the log as normal lines each time it changes; an identical summary is not written twice in a row. New `test_v615.py`.

## V6.1.3 - 2026-10-05
- Recovery build: starts from V6.2 and carries over only the good fixes of V6.1.2. **The V6.1.2 theme rework is not included** (no theme engine setting, no Fast restyle, no Sun Valley Lite, no shared palette rework): the Sun Valley theme files, fonts, colours, paddings and layout are those of V6.2. `MONTAGE_SIMPLE_THEME=1` works as in V6.2.
- Startup: worker threads use a snapshot of the Tk variables taken on the UI thread (`App.snap_vars`, taken in `run_task`); before, `load_clips` read `m_game` from its worker while the splash ran without a main loop and failed with "main thread is not in main loop", so the first clip load never ran.
- Songs: `scan_audio` computes each file's key once; MP3s modified < 15 s ago, empty or still changing are skipped this run (one log line) and never cached; one bad file no longer aborts a render, the clip load or the song match.
- Song matching: the V6.2 matcher and scoring are unchanged (the faster V6.1.2 matcher mismatched songs and is NOT included). New: a match cache (`montage_data\match_cache.json`, keyed by CSV name / size / mtime, songs folder file count / newest mtime and the overrides): a hit loads at once, a changed key matches only new / unmatched files. The first show no longer waits for matching (Songs list from the cache, or empty with "Matching songs..."; the result is applied once). The 12 s safety timeout stays. test_v612 checks that two songs of one artist match their own titles, that Cyrillic and Japanese text is kept, and that artist-only matches do not score 100.
- Manual clip list: new last column "\u25b6 Open" (click opens the clip in the default player without waiting; never ticks the row) and double-click on a row opens the clip.
- Length: the fixed-length slider (Manual and Settings share it) ranges 80-150 s, like Optimal (V5.42B); saved values below 80 / above 150 are clamped. The old 30-120 came from the two `ttk.Scale(from_=30, to=120)` sliders and the config comment; the planner's Optimal rule was already 80-150.
- Sun Valley fixes without changing the look: the generated `sv.tcl` bound `<<ThemeChanged>>` -> `configure_colors` (tk_setPalette over every widget) again on every sourcing, now once per window; each of the 12 variants is built and sourced at most once and reused by name (theme cache version t4, rebuilt once). Black boxes: the black base used #0b0b0b for the app's classic widgets while the Sun Valley variant draws #000000, so the app's black background is now #000000; and ttk Labels created while Tk's option database held an old palette kept it as their own background, which overrode the theme after Black -> Grey -> Black, so `recolour` clears it.
- perflog: the widget-creation hook called `winfo_class()` before the Tk window existed ("bad window path name .!toplevelN" broke "Calibrate killfeed region" and the Song map); it now uses the Python class name and can never raise.
- Housekeeping: `perflog.txt` untracked, `perflog*.txt` ignored. New `test_v612.py`: workers, audio files, matcher titles, cache, first show, theme, length, open column, and a popup test that opens and closes every window in normal and perflog mode.

## V6.2 - 2026-10-05
- Measurement build (detection, planner, effects and render pipeline untouched; no behaviour change without the switches below). `python montage.py perflog` now also records:
  - a stack sampler (daemon thread, main thread sampled every 10 ms); for every main-loop gap above 50 ms the most frequent stack (top 6 Python frames) is kept and the summary lists the top 10 by total blocked time. If the main thread was inside Tk's C code the entry is labelled "Tk C-level" with the last Python frame;
  - an `ENV` header line: OS / Windows build, Python, Tk patchlevel, sv_ttk version, window size, screen size, `tk scaling`, DPI awareness (process, window and system DPI on Windows) and the theme in use;
  - a STAGE TABLE with the duration of every startup stage (Tk(), apply_theme and its parts, splash, widget build per tab, prerealize, App.startup with every package import, each phase of the clip scan thread, song match, hand-off to the UI thread, first fill, show) plus marks (splash painted, first fill done, window shown) and whether the OCR engine was created before the window was shown;
  - THEME SWITCHES: per switch the stages (theme source / theme_use / ttk style configure / registry recolour / the update_idletasks that follows), the time to the first idle callback and first Expose after it, and the main-loop gaps in the 2 s after it.
- `MONTAGE_SIMPLE_THEME=1` (A/B test only): the app uses the built-in ttk `clam` theme with the same base / accent palette (the existing fallback theme, styles applied with Style configure / map, no sv_ttk image elements). Without the variable nothing changes.
- OCR engine: it is already created lazily (first real OCR call, only when clips need scanning); not changed.

## V6.1 - 2026-10-05
- GUI only (detection, planner, effects and render pipeline untouched). Splash: a small centred "Montager - loading" window with a progress bar is painted first; the main window stays withdrawn. Everything that used to happen after the window appeared now happens behind the splash: divider positions (apply_layout, computed from the window geometry without a late retry), App.startup, the first clip / song cache load and the first fill of the clip, song and Auto status lists. The main window is shown once, after the first fill (safety: after 12 s it is shown with "Loading..." and fills when ready). The main progress bar never changes before the window is shown; scan progress keeps the 4-per-second throttle afterwards.
- Tab switching: App.refresh_songs no longer refills the list or resets the selection (the 50 ms follow-up) when the data is unchanged. Tab switches themselves only show the existing frame (unchanged).
- Theme: one registry for classic tk widgets (`App.reg(widget, role)`; roles window / label / text / entry / list / pane / menu / accent / fixed). `retheme` walks every classic widget (registered by role, the rest by class, including popups, the changelog, the track picker, combobox pop-downs and the splash) and applies the current palette. New `test_v61.py` cycles all 12 accent x base combinations grey/black alternating in one window and checks bg / fg / highlightbackground per role.
- Poll cost (~140 ms on the UI thread): the "done" step of App.poll ran refresh_auto on the UI thread: it re-read the clip and kills caches, built a Detector per game, stat()ed every clip and listed the output folders. It now runs in a worker thread that hands the finished status texts to the UI through the queue, and is skipped when none of the files it reads changed.
- Priority (Windows): ffmpeg / ffprobe child processes start with BELOW_NORMAL_PRIORITY_CLASS so the window stays responsive during scans and renders. Linux unchanged; worker counts and encoder settings unchanged.

## V5.6 - 2026-10-05
- GUI only, no more widgets or lists appearing one after another. The main window stays withdrawn while every tab is built and laid out once, then it is shown in one step (no alpha trick). Popups (changelog, date range, playlist track picker) are created withdrawn, laid out, centred over the main window and then shown.
- Lists (clips, songs, tables) are filled in one pass while the list is unmapped and shown once; no row-by-row growth. While clips are being scanned the lists are not refilled at all: the status line shows "Scanning 51 / 210" and the lists are refilled once when the scan ends.
- Scan progress label and bar update at most 4 times per second (final value always shown). Log lines are collected and inserted every 250 ms in one block; the log keeps the last 2000 lines.
- Tab switching only shows the existing frame (unchanged from V5.58). Detection, planner and render logic are untouched; the clip scan only reports its progress now.

## V6.0 - 2026-10-05
- Auto / weekly length: the Auto path now sizes the montage with the same `optimal_fit` rule as Manual (80-150 s, never past the song, nothing padded). Cause of the 63 s montage: the old Auto sizing counted every fight at its raw length (dead air included, which is jump-cut in the render) and cut events to a "120 s" budget that rendered as ~63 s. Plain singles now top up, best first, until 80 s when the multikills fall short. A fixed length is unchanged.
- Audio: if Auto picks a silent or unusable track for one clip, only that clip uses Legacy (loudest track); the log says "audio fallback for <clip>: <reason>" and Auto stays for the other clips. A failure of the whole render still falls back to Legacy for the whole montage. Gain logic unchanged.
- Settings > Player names (Valorant, CS2): editable names / aliases separated by ";". Defaults are exactly the old ones (fireaxe; CS2 also the CJK recovery name). New scans record the names used. Cached clips with no record count as scanned with the default names, so nothing is rescanned or marked stale by this update. After you change names, clips scanned with other names are marked stale and the app only asks before rescanning (background, cancellable, resumable).
- Weekly pick: clips already used are never reused; this week's new clips come first, older unused clips follow only as needed (best multikills first, then singles); clips are flagged used only after a successful render; with no unused material the run is skipped with a stated reason, with little material the montage is shorter.
- New `python montage.py perflog` (or MONTAGE_PERFLOG=1): timeline recorder, writes perflog.txt on exit or Ctrl+Shift+P. No behaviour change without it. The pop-in fix itself is not part of this version.
- New `test_v60.py` (generated data, no render). Detection, song-map beat logic, effects and render pipeline are unchanged.

## V5.58 - 2026-10-05
- Live themes: changing Accent colour or Base in Settings applies at once, no restart. The theme is re-applied in the running window (one Sun Valley theme per accent x base, loaded once, then reused) and every classic widget that carried an old palette colour (log, dividers, Settings canvas, drop-down lists, changelog popout and its headings) is recoloured. "Applies after restart" removed for these two options (UI scale still applies after restart). Choice is saved in config as before.
- Tab switching without visible reloading: all tabs were already built once; now they are also laid out and mapped while the window is still invisible (alpha 0), the Settings page and the divider positions are sized before the window shows, and the clip / song / table lists are not refilled when the data is unchanged. A tab switch only raises an existing frame. Switch time is measured (`App.switch_ms`).
- Settings audit (no rendering): every Settings and Manual control checked for save + reload, for being read by the code, and for changing the plan or the render parameters. Result in the V5.58 release notes; no dead or mis-wired setting was found among the controls. Detection, planner and render logic are unchanged.
- Window title shows V5.58.
- New `test_v558.py` (live theme, tab switching, settings audit). `test_v557.py` still passes.

## V5.57 - 2026-10-05
- Mouse wheel never changes a value any more (comboboxes, spinboxes, sliders, option menus on every tab); the wheel scrolls the page instead.
- Settings rebuilt on one grid: section headers, a fixed label column, uniform row padding and extra space between sections.
- "Save settings" moved to a fixed footer bar at the bottom of the Settings tab with a status label ("All changes saved" / "Saved ✓"). Autosave stays on.
- Themes are back: accent colour (Lime green, Yellow, Orange, Red, Pink, Purple) and base (Grey, Black), 12 combinations. Default stays grey + lime. Applies after restart.
- "More filters & actions" is now a dropdown (same widget and style as "Show"); its list opens over the layout and never changes the window or clip list size.
- Button feedback: hover and pressed look, busy state while an action runs (no double clicks), short result on the button ("Done ✓", "Ticked 12 clips") and in the status line.
- Random pick fixed: it has its own number box (default 15) that is never shared with "Tick newest", ticks exactly N random clips (all of them, with a status message, if fewer are eligible), respects the filters and "Include used clips".
- Changelog button in Settings opens this file in a popout window.
- Cleanup of GUI labels, messages and column headings (sentence case, typos, alignment).
- New Settings > Audio mode: "Auto (V5.56)" (default) or "Legacy (V5.55)" (the V5.55 audio path: loudest track, per-game "game audio track" ignored). The plan log shows `[audio: auto V5.56]` or `[audio: legacy V5.55]`. If the Auto path fails or gives silent / missing audio, that render falls back to Legacy and shows "Auto audio failed, used Legacy V5.55".
- Detection, planner and render logic are unchanged.

## V5.56 - 2026-10-05
- Montager name and its own taskbar identity.
- Game audio track pick per game (auto / 1 / 2 / 3); audio track choice now uses gunshot onsets and never picks a silent track (replaces "loudest track").
- Settings autosave; scrollable Settings tab.
- Grey + lime theme as the single theme (the theme option, `duck_db` and `game_under_music_db` config keys were removed).
- Collapsible "More filters & actions" section in Manual.
- Resize debounce (no list refills while the window is resized).
- Random pick uses the number box (N).

## V5.55 - 2026-10-05
- Frontend only: Sun Valley theme (fallback: clam), drag dividers with remembered layout, "used" column and filter, Random pick via Optimal, Render shows the plan first.

## V5.5 - 2026-10-05
- pythonw launcher and icon.
- Optional `git pull` on start.
- Kill cache survives updates (re-link + rescan reasons).
- Valorant knife kills count.
- Pre-clip / same-victim duplicate check.
- A rejected stitch is re-planned on the single clip.

## V5.44
Details not recorded. No commit, tag or note in the repository carries this version number.

## V5.43 - 2026-10-05
- Tail rule extends the end only.
- V5.42 ending and order restored.
- No kill in two takes.
- Fake duplicate kills dropped (Valorant + CS2).

## V5.42B - 2026-10-05
Five items, one commit each:
- Item 1: knife and revive/resurrect rules are Valorant-only; CS2 weapon icon = largest long icon (modifier icons never taken for it). The V5.42 green-victim-side revive rule had read CS2 CT-blue names as green and the 5:1 knife rule caught AWP/rifle icons, so CS2 gun kills (including a smoke kill) were dropped. The game is passed through analyse_entry / ocr_rows / classify_row; the smoketest gained a CS2 row check.
- Item 2: CS2 '火斧' counts as my name on either side (kill/death/assist rules unchanged); the plan prints how many rows it recovered.
- Item 3: two files showing the same kills (same victims at matching times) are one event, whatever their file times (2+ shared victims at one consistent offset, or one shared victim whose kill frame is the same footage). Before, only clips recorded within about 60 s of each other were compared, so a re-export or copy was placed twice.
- Item 4: never cut before the kill is seen: a take's tail runs at least 0.4 s after my last kill row appears (measured from the row, not the estimated shot); dead-air jump-cuts also wait for each row; verify_cutlist checks the row tail (death / clip end excepted).
- Item 5: Optimal = optimal_fit(clips, song, style): 80-150 s, never past the song, all usable ticked clips unless they really don't fit (weakest first, listed with why); section chosen to fit, ending on a phrase; a drop is a preference; Manual cut-list repair extends / shifts before dropping.
- Also in this version: `out()` never crashes on a non-UTF-8 console.

## V5.42 - 2026-10-05
- Killfeed colour first: a green victim side is a revive / resurrect, never a kill or death.
- Knife blade excluded.
- Real-row fixtures in the smoketest.

## V5.41 - 2026-10-05
- Adaptive multikill dead-air jump-cuts (the music decides the allowance).
- Optimal fits the song (120 s / music available, lists clips that didn't fit).
- Sage resurrect rows are revives, never kills or deaths.

## V5.4 - 2026-10-05
- Montage never longer than the song section.
- Status estimate = the real planner.
- Manual uses every usable clip.
- Optimal fits the song.
- Auto style from song map + material.
- Length / style WHY in the plan.

## V5.3 - 2026-10-05
- Clove self-revive rows are never kills and end the death lock.
- One fight = one event = one take.

## V5.2 - 2026-10-05
- Effects: V4 centred zoom punches only, no flashes, no zoom/flash cuts.
- Output: `<SONG>_<GAME>_<version>_<date>.mp4` names, plan txt/json in `logs\`, APP_VERSION in the window title.

## Between V5.1 and V5.2 (no version label) - 2026-10-04
- Render never aborts on a kill row outside the take; smooth float zoom, no shake.

## V5.1 - 2026-10-04
- V4 engine (planner, effects, render graph, audio mix) as the base with frame-exact kill placement; game audio 0.6 (V4 0.5); no ducking, no music automation except the 0.3 s fade-in and the final fade-out.
- Clean start (music from frame 0), slow-mo ending with music + video fade from the final kill, output duration = plan.
- Kill moment = refined gunshot (V4 anchored the shot, V5 the killfeed row).
- Ported from V5: OCR upgrades, clip folders, no reuse, UI scale, sorting, Song map, SSIM, light theme, CLI, smoketest; stitch verification with single-clip fallback.
- Song map: selective drops (sustained >= 4 bars, >= 16 bars apart); `songcheck` command.
- `synccompare`, `rendercheck` (detector + barcode 1.0x check on the rendered file).
- Optimal length (30-120 s) and Auto style as defaults, in Manual and Settings.
- Smoketest: GUI Optimal/Auto wiring, audio tone check (steady tone within 1 dB).

## V5 - 2026-10-04
- Clip folders: explicit Valorant / CS2 folder lists (Settings); the list decides the game.
- Song map per song (cached by mtime): beat grid locked to the CSV tempo, downbeats, 4/8-bar phrases, sections (intro / verse / build / drop / breakdown / outro), every drop, accents, rhythm strength, loudness. Songs tab > Song map view draws it.
- Planner built from the map: first kills on the beat, a strong clip on every drop, calm sections with longer run-ups, ramped approaches in builds, soft start, slow-mo ending with the music and video fades starting at the final kill.
- Frame-exact kills (first visible frame at native fps) and timestamp-exact render.
- Effects: zoom punch, shake on bass hits, flash on drops, ramps before kills, slow-mo, ace freeze, transitions (hard, whip, zoom, flash, crossfade in calm sections only), subtle per-montage grade. Five recipes: hype, smooth, cinematic, aggressive, chill.
- Take quality: 0.2-0.5 s tails, never into my death, 1.0x from 1 s before the first kill through the last kill, a kill frame in every take.
- Duplicate and continuation clips merged; a multikill split across clips is stitched into one take. No clip is used twice.
- Knife and utility kills excluded; ranking: ace > 4k > 3k > fast double > flick/HS single > plain.
- Sound: per-clip loudness normalising (picks the loudest audio stream), game audio 4 dB under the music, music ducked 4 dB around kills, limiter with latency compensation.
- Detection: merges OCR variants of the same row, a single sighting under 90 needs a gunshot; `detectcheck` compares V4 and V5 rules on cached data.
- Quality: 1080p clips pass through pixel-exact, NVENC p7 / hq / spatial AQ / cq16, SSIM check after every render.
- GUI: UI scale, taller clip list, click-to-sort columns, Song map buttons.
- Smoketest adds the planner checks and an end-to-end render whose kill-to-beat sync is measured from the output file.

## V4 - 2026-10-04
- Detection: RapidOCR on the killfeed region replaces template and scale matching (15 fps sampling, OCR only when the bright-text mask changed, rows grouped by y-centre and split at the weapon icon). KILL = FIREAXE first on the killer side (rapidfuzz partial_ratio >= 80), assist and utility rejected, DEATH = FIREAXE on the victim side. Rows tracked by content; each row's first visible frame refined by a pixel diff. Raw OCR boxes cached per clip, so rule changes need no rescan.
- Calibration is optional: only the killfeed region per game, with top-right defaults.
- Manual Step 3: Dry plan / Preview / Render packed first and always visible; Steps 1 and 2 shrink instead of clipping.
- BPM: the CSV Tempo is the primary value and shows immediately; Energy and Danceability come from the CSV; librosa only refines the grid.
- Light theme by default; dark stays available in Settings.
- New `smoketest` command (GUI buttons exist, are visible and wired; OCR on generated KILL/DEATH frames). Selfcheck also runs the OCR test.

## V3 - 2026-10-04
- Row-first killer / victim detection, shared kill logic, per-clip atomic cache, real-time kills, one-to-one song matching, CSV tempo, GUI selection tools and theme. (Commit message only; no further details recorded.)

## Megafix (no version number) - 2026-10-04
- Folder-only clips, real multi-scale detection with raw-frame cache, killer-only / gunshot / death rules, song-anchored frame-exact planner, effect fallbacks, sync report, rebuilt GUI. (Commit message only; no further details recorded.)

## First builder (no version number) - 2026-10-04
- "Complete montage builder": GUI, kill detection, song analysis, planner, render engine. (Commit message only; no further details recorded.)

## Stage 0 - 2026-10-04
- `montage.py` with setup, selfcheck, inventory, tag.

## Initial commit - 2026-10-04
Details not recorded.
