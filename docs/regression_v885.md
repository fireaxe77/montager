# V8.8.5 regression check (V1 .. V8.8.4)

Every rule and feature from the Settings changelog, the technical changelog, the git history / tags and the existing tests, checked again in V8.8.5.
The checks are permanent: `python tests/test_v885.py` part 4 (rules, one line each with the version that introduced it) and part 6 (every Settings control).
Real data (a COPY of montage_data): `tests/fill883.py`, `tests/render885.py`, `tests/skymask885.py`.

## Found and fixed

| Rule (version) | What was wrong | Since | Fix |
|---|---|---|---|
| Game audio level per game (V8.21) | the song leveling pulled every clip to song - 12 LU whatever the level, so the setting did nothing | V8.8.2 | the leveling target moves with the level; identical at the default 0.6 |
| Fill the whole song in Auto (V8.8.3) | Valorant / CS2 Auto on Perfect Exceeder ended 3.4 - 7 s before the end with a mostly used library | V8.8.3 (data-dependent) | up to 6 fill rounds of at least 8 s of clips |
| Kills on the beat (V5) | a slowed multikill anchored on its first kill (mostly the ending) showed that kill ~2 frames (25 - 34 ms) early | V7.6.1 | the first kill keeps its frame, the last kill comes those frames later |
| Auto 60 s minimum / fixed slider length (V6.5.1, V7.3) | Valorant / R6S Auto never topped up with used clips: 57 s for a 90 or 120 s slider | old (only CS2 had the top-up) | the top-up runs for every game, to 90 % of a fixed length (Valorant 80 / 119 s, R6S 83 / 101 s, CS2 84 / 109 s for 90 / 120 s) |
| Sky mask on the sky only (V8.5 - V8.8.4) | the kill push / shake moved the mask off the sky for ~0.2 s; smoothing / holds carried it over cuts and turns | V8.6.2 / V8.5 | colour pushed inside a fixed mask; render-exact, shot-aware, per-frame guarded masks |
| Auto tab buttons visible in a small window (V5.57) | the Rainbow Six row's buttons were cut off at 920 x 640 | V8.0.0 | buttons above the status text |
| `python montage.py smoketest` | failed 13 checks already on v8.8.4: its songs were skipped as 'still being written', its 4 sync clips became one stitched fight, its click song had no V2 map, a UI snapshot was missing, a UTF-8 child was read in cp1252, old planner / sync / GUI expectations | V6.1.3 - V8.8.4 | test code only; SMOKETEST PASSED, its real render has every kill on its beat (0.0 ms) |

## Real data (a copy of montage_data, song Perfect Exceeder)

- Plans, 3 games x 5 modes (Auto, Force Full, Manual, Manual Auto, fixed 90 s), `tests/render885.py ... 0`: 15 of 15 pass (song covered / fixed length, kills inside takes, kill = kill row, multikills together, no death shown, leveled game sound).
- Real renders, `tests/render885.py ... 1`: Valorant Auto 135.35 s and CS2 Auto 135.75 s, every check passes (length, music in every window, no clipping beyond AAC overshoot, SSIM >= 0.99, drops within 6 ms, sky clean around the kill frame and the cut).
- `python montage.py smoketest`: PASSED (end-to-end sync: every kill 0.0 ms from its beat; music level steady to 0.15 dB).
- `tests/skymask885.py`: V8.8.4 painted off the sky in 2 of 5 Valorant and 4 of 6 CS2 sky takes, V8.8.5 in none.
- `tests/fill883.py`: 12 of 12 game x mode plans fill the song.

## Old test files (V8.0 - V8.8.4) run on a copy of the data

Every failing line was traced: title-bar version / changelog order (every file), "identical to an older tag" checks that later versions changed on purpose (V8.4.3 no glow, V8.5.1 flash budget, V8.8 / V8.8.2 universal beat-locked sky and counts, V8.8.4 kill-row times, V8.23.1 square R6S icons = gadget kills, V8.1 CS2 stitch gap, V8.8.1 R6S icon re-match, V8.8.3 / V8.8.4 families), the 6 known CS2 ground-truth gaps of V8.8 (clips moved / unscanned, one known 13.67 vs 14.6), test mocks without the new `plan=` argument of `sky_take_mask` (the rule itself is in part 4), and the V8.8.2 / V8.8.3 checks of the two values this version changed on purpose (game level target, fill rounds).

## Rules checked (tests/test_v885.py part 4)

- ok: [V5 / V8.8.2] song leveling: every clip's game sound is brought to the same level under the song (song - 12 LU at the default level)
- ok: [V8.21 / V8.8.5] the Game audio level setting still moves the leveled game sound (0.3 = 6 dB under the default, every clip)
- ok: [V8.8.2] at the default level the leveling gains are exactly the v8.8.4 ones
- ok: [V8.8.2] song leveling never clips: a quiet clip's lift stops where its peak reaches -1 dBFS
- ok: [V8.8.2] song leveling: a silent clip stays silent (no lift)
- ok: [V8.8.2] song leveling range: up to +24 dB, down to -12 dB
- ok: [V8.21] game audio level 0 - 1 per game (default 0.6, own key per game)
- ok: [V4 / V8.8.2] +4 dB kill boost around each kill (never above unity for a clip at or under unity)
- ok: [V5.56] audio track: a silent track is never chosen; Settings 1 / 2 / 3 force a live track; auto = most gunshots
- ok: [V7.7.0 / V7.7.1] music over gameplay: off by default, lowers 12 dB, 0 - 60 dB, 60 = mute
- ok: [V8.6.2] the music is never dipped or ducked at a drop
- ok: [V8.6] the drop lift has no exp() that could overflow and silence the music
- ok: [V5.1] music (valorant): sample-exact start, only 2 dB headroom, never ducked or automated
- ok: [V5 / V5.1] mix (valorant): amix without normalising, safety limiter, 0.3 s fade-in, music fade-out from the final kill
- ok: [V4 / V5] game audio (valorant): every take's game sound carries its clip gain and the kill boost
- ok: [V8.4.5] audio holes inside a source range are filled by time (aresample async) only where there is a hole
- ok: [V6.0] a silent game audio track is replaced by the loudest one for that clip only
- ok: [V8.21] game audio level in Settings for each game
- ok: [V5 - V7.7.5] valorant hype default: every take holds its kills, rows inside the footage, 1.0x around the kills, tails, no clip / kill twice (0 problems)
- ok: [V5 - V7.7.5] valorant hype extra: every take holds its kills, rows inside the footage, 1.0x around the kills, tails, no clip / kill twice (0 problems)
- ok: [V5 - V7.7.5] valorant chill default: every take holds its kills, rows inside the footage, 1.0x around the kills, tails, no clip / kill twice (0 problems)
- ok: [V5 - V7.7.5] valorant chill extra: every take holds its kills, rows inside the footage, 1.0x around the kills, tails, no clip / kill twice (0 problems)
- ok: [V5 - V7.7.5] cs2 hype default: every take holds its kills, rows inside the footage, 1.0x around the kills, tails, no clip / kill twice (0 problems)
- ok: [V5 - V7.7.5] cs2 hype extra: every take holds its kills, rows inside the footage, 1.0x around the kills, tails, no clip / kill twice (0 problems)
- ok: [V5 - V7.7.5] cs2 chill default: every take holds its kills, rows inside the footage, 1.0x around the kills, tails, no clip / kill twice (0 problems)
- ok: [V5 - V7.7.5] cs2 chill extra: every take holds its kills, rows inside the footage, 1.0x around the kills, tails, no clip / kill twice (0 problems)
- ok: [V5 - V7.7.5] r6s hype default: every take holds its kills, rows inside the footage, 1.0x around the kills, tails, no clip / kill twice (0 problems)
- ok: [V5 - V7.7.5] r6s hype extra: every take holds its kills, rows inside the footage, 1.0x around the kills, tails, no clip / kill twice (0 problems)
- ok: [V5 - V7.7.5] r6s chill default: every take holds its kills, rows inside the footage, 1.0x around the kills, tails, no clip / kill twice (0 problems)
- ok: [V5 - V7.7.5] r6s chill extra: every take holds its kills, rows inside the footage, 1.0x around the kills, tails, no clip / kill twice (0 problems)
- ok: [V5.1] kills land frame-exactly and the music starts at frame 0 (first take at frame 0, takes contiguous)
- ok: [V5.42B] a take runs at least 0.4 s past the last kill row
- ok: [V5 / V5.43] no clip is used twice and no kill is in two takes
- ok: [V5.4] a montage is never longer than the song
- ok: [V7.6.0] the montage ends right after the final kill with a short fade (from the final kill)
- ok: [V5.1 / V8.4.1] Optimal length 80 - 180 s; default length Optimal, default style Auto
- ok: [V5.1 / V8.8.5] the smoketest's planner self-check passes (cut list, best multikill on the drop, kills on the beat, slow-mo ending with the fades from the final kill)
- ok: [V5 / V7.3] kills on the beat: every take's anchored kill on a beat (frame-exact; a take next to a drop up to 3 frames), the headline's on the drop
- ok: [V8.4.1] maximum montage length 180 s
- ok: [V8.5] Force Full: 2:30 of content (3:00 with the ending), long songs use a 1:30 - 2:30 section
- ok: [V6.5.1] Auto / weekly montages are at least 60 s
- ok: [V5.42B / V8.8.4] the death rule: no kill counted for 8 s after my own death
- ok: [V5] a take never runs into my death
- ok: [V8.8.4] the kill row is the kill time in every game (no gunshot moves it)
- ok: [V8.8.4 / V8.1 / V6.9.7.1] multikills stay one fight: R6S whole clip / group, CS2 one row = one event, Valorant 10 s (30 s in long clips)
- ok: [V5.3 / V8.8.4] valorant: a 4-kill fight (12 s from first to last kill) is ONE take with all 4 kills, each at its row time
- ok: [V5.3 / V8.8.4] cs2: a 4-kill fight (12 s from first to last kill) is ONE take with all 4 kills, each at its row time
- ok: [V5.3 / V8.8.4] r6s: a 4-kill fight (12 s from first to last kill) is ONE take with all 4 kills, each at its row time
- ok: [V8.8.3 / V8.8.5] one fill rule for every game and mode: Auto, Force new, Force Full / New Full, Manual, Manual Auto, dry plan, render (make_plan)
- ok: [V8.8.3] Auto / Manual Optimal and full mode cover the whole (trimmed) song; a fixed slider length does not
- ok: [V8.8.5] the fill keeps adding clips until the end of the song (6 rounds of at least 8 s of clips, end within 3 s)
- ok: [V8.8 / V8.8.3] dead air at the start / end of the song is trimmed in every mode
- ok: [V8.8] dead air: silence at the start / end is found from the song's envelope
- ok: [V8.8] song-end fill: up to 1 s more run-in for some takes when a montage ends a few seconds short (up to 15 s)
- ok: [V6.0] Auto picks unused clips first, this week's first
- ok: [V8.5 / V8.8.2] Manual Auto ticks about 1.3x the song in clips, then tops up with the render's own plan (2 rounds, 6 s tolerance)
- ok: [V8.5] Force New Full: the song is picked first, then ~1.25x its length in clips
- ok: [V6.5.1 / V7.3 / V8.8.5] every game's Auto montage reaches the 60 s minimum and a fixed slider length (90 % of it), topping up with used clips
- ok: [V7.6.1] one song + style pick per job (the summary, the plan and the render share it)
- ok: [V8.6.2] CS2 deathmatch clips are never picked automatically (hand-ticked clips are)
- ok: [V8.4.5 / V8.6] broken recordings (under 20 fps) and stalled clips are left out
- ok: [V8.8] clean 60 fps full-size clips are picked first (quality weight)
- ok: [V6.9.8] random / weekly picks pull in a multikill's other clips (companions)
- ok: [V8.4.1] Effects per game: CS2 Extra, Valorant / R6S Default at first start
- ok: [V8.7] sky recolour switch per game (CS2 / Valorant on, R6S off); off = no sky candidate
- ok: [V8.4.2] every extra effect has its own render switch
- ok: [V8.5.1] white flashes: one per 10 s of montage
- ok: [V8.4.4 / V8.4.5] the kill flash is a clean white pulse (no colour cast, the frame before untouched)
- ok: [V8.8] every drop gets a sky before any drop gets a second one; every kept sky has the montage's one pattern
- ok: [V8.8 / V8.8.2] sky count / spacing: one per 15 s, at most 12, 6 s apart
- ok: [V8.7 / V8.8] strobe, drops to black on the beats and colour jumps are on (beat-locked)
- ok: [V8.8.4] sky: a clear top -> bottom gradient in every family
- ok: [V8.6.1 / V8.6.2] sky: walls are never painted (too dark, too large or running down the picture)
- ok: [V8.5.1 / V8.6] sky lands on the kill frame (3-frame punch) and stays to the end of the take
- ok: [V8.7] smoke / flickering pixels are never part of the sky
- ok: [V7.5.1.1] intro punch on the first beat
- ok: [V7.6.1 / V7.7.6] soft dissolves blend in even steps
- ok: [V8.1.1 / V8.2] smooth slow motion (motion interpolation) in every game
- ok: [V8.2] jitter-free 60 fps clips (frame-number timing)
- ok: [V6.9.8.1] low-frame-rate smoothing is off by default
- ok: [V8.22] post-render checks are an option, off by default
- ok: [V8.6] CS2 headline / ending kills: slow, fast, slow
- ok: [V5.42] revives are never kills or deaths (green victim side)
- ok: [V5.5] Valorant knife kills count
- ok: [V8.0.3 / V8.8.1] R6S utility kills are left out (any utility icon in the row)
- ok: [V6.9.10 / V7.7.7] CS2 kill rows already on screen at the clip start are never kills
- ok: [V8.1] CS2 one physical killfeed row = one kill
- ok: [V8.8] CS2 late rows re-timed (the missed kill of a multikill)
- ok: [V8.1.1] CS2 rows cut by the region's edge dated by their top part
- ok: [V8.0.0] R6S clips are never scanned in bulk
- ok: [V8.8.4] a missing gunshot never removes a kill (soft notes only)
- ok: [V5.2] output files are named SONG_GAME_VERSION_DATE
- ok: [V5.2] the version shows in the window title
- ok: [V6.9.11] Settings shows the readable changelog, newest version first
- ok: [V6.5 / V7.7.6] song matching: exact title + artist, loose match by main artist and title
- ok: [V5.57] accent colours and base theme
- ok: [V5.56] audio track pick per game (auto by default)
- ok: [V6.0] player names per game
- ok: [V7.7.1] SongMap mode setting
- ok: [V8.22] Random pick button
- ok: [V8.5 / V8.5.1] Force New Full and the Manual Auto button
- ok: [V8.0.4 / V8.0.5] Scan all new clips (current region)
- ok: [V6.7.4] trash icon: the clip goes to the Recycle Bin after confirming
- ok: [V8.8.1] long montages render (short input aliases over the command limit)
- ok: [V8.4.4] a render is one attempt; a failure says where
- ok: [V5.57 / V8.8.5] Auto tab: each game's buttons sit above its status text (all three games' buttons stay visible in a small window)
- ok: [V5.1 / V8.8.5] the smoketest's end-to-end sync test: clips saved on their own days (not one stitched fight), its click song mapped, the kill row measured as the kill moment through the slow-down
- ok: [V6.1.3 / V8.8.5] the smoketest's own songs are finished files (the 'still being written' rule skips only songs modified in the last 15 s)

## Settings (tests/test_v885.py part 6: set in the window, saved, loaded in a new window, read by the code)

- ok: saved: mp3_dir
- ok: saved: playlist_dir
- ok: saved: output_root
- ok: saved: clip_dirs
- ok: saved: max_mb
- ok: saved: max_dur_s
- ok: saved: auto_recent_days
- ok: saved: auto_old_per_run
- ok: saved: name_match
- ok: saved: death_lock_s
- ok: saved: week_days
- ok: saved: game_audio_level_valorant
- ok: saved: game_audio_level_cs2
- ok: saved: game_audio_level_r6s
- ok: saved: game_audio_track
- ok: saved: player_names
- ok: saved: length_s
- ok: saved: style
- ok: saved: placement
- ok: saved: audio_mode
- ok: saved: quality
- ok: saved: interpolate_low_fps
- ok: saved: lower_music_clips
- ok: saved: sync_report
- ok: saved: update_on_start
- ok: saved: post_checks
- ok: saved: effects_game
- ok: saved: sky_game
- ok: saved: accent
- ok: saved: base
- ok: saved: music_lower_db
- ok: saved: songmap_mode
- ok: loaded again: mp3_dir
- ok: loaded again: playlist_dir
- ok: loaded again: output_root
- ok: loaded again: clip_dirs
- ok: loaded again: max_mb
- ok: loaded again: max_dur_s
- ok: loaded again: auto_recent_days
- ok: loaded again: auto_old_per_run
- ok: loaded again: name_match
- ok: loaded again: death_lock_s
- ok: loaded again: week_days
- ok: loaded again: game_audio_level_valorant
- ok: loaded again: game_audio_level_cs2
- ok: loaded again: game_audio_level_r6s
- ok: loaded again: game_audio_track
- ok: loaded again: player_names
- ok: loaded again: length_s
- ok: loaded again: style
- ok: loaded again: placement
- ok: loaded again: audio_mode
- ok: loaded again: quality
- ok: loaded again: interpolate_low_fps
- ok: loaded again: lower_music_clips
- ok: loaded again: sync_report
- ok: loaded again: update_on_start
- ok: loaded again: post_checks
- ok: loaded again: effects_game
- ok: loaded again: sky_game
- ok: loaded again: accent
- ok: loaded again: base
- ok: loaded again: music_lower_db
- ok: loaded again: songmap_mode
- ok: applied: Effects per game
- ok: applied: sky recolour per game
- ok: applied: game audio level per game (and it changes the leveled game sound)
- ok: applied: music over gameplay amount
- ok: applied: SongMap mode
- ok: applied: death lock
- ok: applied: post-render checks switch read by the job
- ok: applied: audio track per game read by the audio pick
