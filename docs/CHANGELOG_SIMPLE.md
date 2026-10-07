# Montager - short history (plain language)

Newest first. The full technical history is `CHANGELOG.md`. Not shown in the app.

## Known issues / on hold
- **ON HOLD:** SONGMAPV2 (new beat grid). Songmap V1 is the default and the only one used for real montages.
- **ABANDONED:** frame interpolation for slow-motion. Off by default (setting kept, code kept).
- **KNOWN ISSUE:** the CS2 "sync report" after a render undercounts kills on slow-mo and zoom takes. The montage itself is fine.
- **KNOWN ISSUE:** CS2 clip `2026.02.10 - 19.09.46.22` shows its kill dated late (killfeed shape filter), so the take starts after the kill. Not fixed.
- **KNOWN ISSUE:** the Valorant 4K `21.04.36.03` often cannot form a take (it does not fit the song's beats).
- **KNOWN ISSUE:** low-bitrate OBS clips need a kill-detection check; killfeed text can be misread.
- **KNOWN ISSUE:** a stale kill whose victim is read very differently (for example `s0ul` / `$oul`) can still count once as a new kill.

## V6.9.10 - 2026-10-07
- CS2: a kill that was already on the killfeed when the clip started is no longer counted again a few seconds in (it made takes start after the kill or with kills already showing).

## V6.9.9 - 2026-10-07
- Valorant weekly "Force new" can render again: clips saved back to back no longer leave a hole that made the whole render stop.
- One bad take no longer cancels the render; it is skipped and logged. The kill ledger no longer reports hundreds of "lost" kills in weekly runs.

## V6.9.8.1 - 2026-10-07
- Frame interpolation is OFF by default (it caused a repeated slow-mo kill).
- Random pick and weekly picks now pull in the other clips of a multikill even if they were used before, so a 3K stays a 3K (both games).

## V6.9.8 - 2026-10-07
- CS2: a victim read twice in one clip is one kill (a 2K was planned as a 3K).
- Random / weekly picks add the neighbouring clips of a multikill for Valorant too.

## V6.9.7 - V6.9.7.2 - 2026-10-07
- Clips are linked by their real save time: clips saved right after each other become one fight and one stitched take (Valorant OBS clips, CS2 DVR clips).
- Kill ledger: every kill ends as placed, merged duplicate, ranked out or lost, with a log line. Per-clip override to count utility kills (Valorant). Settings checkbox for interpolation.
- Fights inside a long clip stay one fight up to 30 s.

## V6.9.6 - 2026-10-07
- Repository tidied (tests and docs in their own folders); tools to inspect clip pairs and their order. No behaviour change.

## V6.9.5 - V6.9.5.2 - 2026-10-06/07
- ON HOLD: Songmap V2 added as a separate, optional beat analysis with a comparison tool. Default stays Songmap V1.

## V6.9.3 - 2026-10-06
- Low-fps clips could be interpolated at render time (later abandoned, see top).

## V6.9 - 2026-10-06
- CS2: when a fight was recorded as 2-3 consecutive clips, the neighbour clips are pulled into the selection and stitched into one take.

## V6.8 - V6.8.2 - 2026-10-06
- CS2 kill detection reworked around the red border of your killfeed rows (more reliable, fewer phantom kills). Settings region picker, search bar in Step 1, a row-debug tool.

## V6.7 - V6.7.6 - 2026-10-05/06
- CS2: garbled name reads no longer inflate the kill count; knife and revive rows handled.
- The killfeed region is remembered and protected against bad values.

## V6.5 - V6.5.2 - 2026-10-05
- Song matching fixed for files named "Title - Artist1, Artist2".
- Weekly / Auto montages are at least 60 s (reused clips only if needed).
- V6.5.2 = the Valorant kill-detection baseline: later versions must give the same Valorant kills.

## V6.0 - V6.2 - 2026-10-05
- Auto / weekly length uses the same fit rule as Manual (80-150 s, never past the song).
- Faster start (loading window, one-step window build), calmer Manual tab summary line, a performance log.

## V5.x - 2026-10-05
- Looks and handling: Sun Valley theme with live accent colour, draggable dividers, "used" column and filter, Random pick, plan shown before rendering, own taskbar icon, launcher, mouse wheel never changes values.
- Editing rules: montage never longer than the song section; adaptive jump-cuts in long multikills; green victim = revive, not a kill; Clove self-revive is not a kill; zoom punches only (no flashes); render never aborts on a kill row outside the take.

## V5 - V5.1 - 2026-10-04
- Explicit Valorant / CS2 clip folders. The V4 engine became the base with frame-exact kill placement.

## V4 - 2026-10-04
- Kills are read from the killfeed with OCR (replaces image matching): a kill is a row with your name first.

## V3, megafix, first builder, stage 0 - 2026-10-04
- First versions: GUI, clip and kill detection, song matching, planner and renderer. Details not recorded.
