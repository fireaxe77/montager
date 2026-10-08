# Montager - what changed (plain language)

Newest first. This is the history shown in Settings. Technical details are in CHANGELOG.md.

## V7.4.9 - 2026-10-08: CS2 multikills no longer lose a kill
- A CS2 multikill that showed only two of its three kills now shows all three.
- Valorant and every other clip stay exactly as they were.

## V7.4.8 - 2026-10-08: Later drops found after quiet breaks
- A song that quiets down and comes back at full strength later on now gets that second drop marked.
- Drops that were already found stay exactly where they were.

## V7.4.7 - 2026-10-08: Headline kills land on the real drop
- The big multikill now lands on a real drop of the song, not on a point a few seconds after it.
- The timeline line shows the drop that was actually used.

## V7.4.5 - 2026-10-08: Drops found within a fraction of a second
- Drops now land on the moment the bass really comes back, usually within about a quarter of a second.
- Gentle, slow songs get their drops found too.
- Every detected drop now has a confidence score, shown in the drop check tool.

## V7.4 - 2026-10-08: Drops found earlier and on the beat
- Drops in the first minute of a song are found now, and drops sit on the beat where the bass comes back.
- The montage's main drop is now always a real drop of the song, and you can save your own drop times with "dropsave".
- CS2 Force new reaches 60 seconds.

## V7.3 - 2026-10-08: Drop kills with real impact
- The last kill of a multikill now lands on the drop (the first kill for a double kill), so the payoff hits the beat.
- CS2 "Force new" now fills the montage up to the 60 second minimum, like Valorant.
- Kills added by the utility override get no slow-motion and never end a montage.
- New "dropcheck" tool: shows whether a missed drop is the song map, the planner or the kill timing.

## V7.2 - 2026-10-08: Song map V2 is the default
- Kills now land closer to the beat.
- Drops are found where the kick comes back, so a montage starts on a steady beat instead of a quiet build-up.
- Songs where V2 cannot find a steady beat fall back to the old map automatically. Songmap V1 stays selectable in Settings.

## V7.1 - 2026-10-08: Better beat grid and drops (V2 tuning)
- The beat grid follows the kick more closely, including songs with a drifting or unusual tempo.
- Settings now offers just "Songmap V1" and "Songmap V2".

## V7 - 2026-10-08: Song map V2 test
- A first test of the better beat grid on 19 songs.

## V6.9.11 - 2026-10-07: Readable changelog in Settings
- The changelog in Settings now shows this short plain-language history.

## V6.9.10 - 2026-10-07: CS2 phantom kills from stale feed rows removed
- A kill that was already on the killfeed when the clip started is no longer counted again a few seconds in.
- This stops takes that started after the kill or showed a kill twice.

## V6.9.9 - 2026-10-07: Weekly render fix
- Valorant weekly "Force new" can render again; clips saved back to back no longer leave a gap that stopped the render.
- One bad take no longer cancels the whole render; it is skipped and logged.
- Weekly runs no longer report hundreds of "lost" kills that were not lost.

## V6.9.8 - 2026-10-07: Companion clips for random and weekly picks
- Random and weekly picks now pull in the other clips of a multikill, even if used before, so a 3K stays a 3K (both games).
- CS2: a victim read twice in one clip is one kill (a 2K was shown as a 3K).
- Frame interpolation is now off by default (it caused a repeated slow-mo kill).

## V6.9.7 - 2026-10-07: Kill ledger + per-clip utility kills
- Clips saved right after each other are linked by their real save time and become one fight and one stitched take.
- Every kill now ends up as placed, merged duplicate, ranked out or lost, and the log says which.
- Valorant: a per-clip override can count utility kills.
- Fights inside a long clip stay one fight up to 30 s.

## V6.9.6 - 2026-10-06: Smarter fps check + stitch order fix
- The low-fps check looks at the frame rate you actually see on screen.
- Stitched clips are put in the right order.
- Tools added to inspect clip pairs and their order.

## V6.9.5 - 2026-10-06: Song map V2 (on hold, V1 stays default)
- ON HOLD: an optional new beat analysis with a comparison tool. Not used for real montages.

## V6.9.3 - 2026-10-06: Repo cleanup + frame interpolation (later turned off)
- Low-fps clips could be smoothed at render time. Later abandoned (see top).

## V6.9 - 2026-10-06: Multikills split across clips
- CS2: when a fight was recorded as 2-3 consecutive clips, the neighbouring clips are pulled in and stitched into one take.

## V6.8 - 2026-10-06: CS2 kill detection around the red border
- CS2 kills are found through the red outline of your killfeed rows: more reliable, fewer phantom kills.
- New killfeed region picker in Settings and a search bar in Step 1.

## V6.7 - 2026-10-05: CS2 kill count fixes
- Garbled name reads no longer inflate the kill count; knife and revive rows are handled.
- The killfeed region is remembered and protected against bad values.
- The 150 s length setting now really gives 150 s.

## V6.5 - 2026-10-05: Song matching and weekly length fixes
- Song files named "Title - Artist1, Artist2" are matched to the right track.
- Weekly / Auto montages are at least 60 s.
- Manual list: clicking an empty "used" cell flags the clip, and there is an "Unflag all" button.
- V6.5.2 is the Valorant kill-detection baseline.

## V6.0 - V6.2 - 2026-10-05: Faster start and calmer Manual tab
- Auto / weekly length follows the same 80-150 s fit rule as Manual and never goes past the song.
- Loading window, quicker tab switching and no widgets appearing one by one.
- A silent game audio track is replaced by the loudest one for that clip only.

## V5.x - 2026-10-05: Looks, handling and editing rules
- Sun Valley theme with live accent colour, draggable dividers, "used" column and filter, Random pick, own taskbar icon.
- The mouse wheel never changes a value any more.
- A montage is never longer than the song section; long multikills get adaptive jump-cuts.
- A green victim means revive, not a kill; Clove self-revive is not a kill; zoom punches only.

## V5 - V5.1 - 2026-10-04: Clip folders and frame-exact kills
- Explicit Valorant and CS2 clip folders. Kills are placed frame-exactly.
- Songs get a beat map with downbeats and sections.

## V4 - 2026-10-04: Kills read with OCR
- Kills are read from the killfeed text instead of image matching.

## V3 and earlier - 2026-10-04: First versions
- GUI, clip and kill detection, song matching, planner and renderer. Details not recorded.
