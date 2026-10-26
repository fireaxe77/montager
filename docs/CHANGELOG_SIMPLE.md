# Montager - what changed (plain language)

Newest first. This is the history shown in Settings. Technical details are in CHANGELOG.md.

## V9.1.1 - 2026-10-26: Quick 4k with an unreadable name now counts all four kills
- A Rainbow Six Siege kill whose victim name is only bars (like "IIIIIIIIIIII") is now found, so a quick 4k is a 4k and its last kill is never cut off by the fade-out
- The montage check now also makes sure the video never fades to black before the last kill
- The sky follows the same rules in every game (only in the high-energy parts of the song); Rainbow Six Siege shows none while its sky switch in Settings is off

## V9.1.0 - 2026-10-26: Strong-beat labels next to the drops
- In the song map you can now mark strong beats next to the drops; each one gets a kill exactly on its time, after the drops, without ever taking a drop's kill
- Drop kills are real kills: CS2 kills over a bright sky or during a hit flash are timed correctly now, and a drop only gets a kill whose row was clearly read
- The sky colour is solid with its moving pattern clearly visible, white is now an ice white, and the sky only appears in the high-energy parts of the song
- High-energy songs cut tighter: speed-ups no longer stretch the run-up, so an energetic montage is never slower than a chill one, and every drop still gets its kill

## V9.0.3 - 2026-10-26: Kills land exactly on the drop you hear
- Every drop in a song now gets a kill exactly on its stored drop time, in Valorant, CS2 and Rainbow Six Siege
- The drop effects (flash, punch, sky, low hit) land on that same moment, so kills and effects no longer come about half a second early
- Every drop still gets a kill; none is skipped

## V9.0.2 - 2026-10-26: Pick the sky colour and intro font in Manual
- Manual has two new dropdowns: Sky colour and Font
- DEFAULT, the first entry, keeps the automatic choice exactly as before
- Any other entry sets the sky colour or the intro title font for that montage only; Auto, weekly and Force New Full montages always choose automatically

## V9.0.1 - 2026-10-24: Every drop gets a kill, also right after the intro
- A drop in the song that comes right after the intro now gets a kill on it, even when the first clip had no room for it before
- The first clip after the intro no longer needs its own run-up, because the intro already shows it
- When a drop cannot be reached, the montage plan now says exactly why instead of skipping it silently
- The ending of a montage now stays in slow motion until it fades out, and the fade starts right after the last kill

## V9.0 - 2026-10-24: An intro and an outro for every montage
- Every montage now opens with a 7 second intro: your first clip, slowed down and blurred while the song fades in and the song title appears over it, then the picture sharpens and speeds up into the clip
- Six looks for the title, chosen from the style of the montage; two of them take their colours from the montage's sky colours. In Manual you can type your own intro text, or untick the intro (Dry plan is now a small button next to it)
- Montages end with a slow-motion release of the last kill, a long smooth fade to black and a longer music tail, using a clip with a few quiet seconds after its last kill
- A montage is never longer than 3 minutes, intro and outro included. A new "Last seed" button next to the seed box in Manual brings back the seed of the last montage you rendered

## V8.8.8 - 2026-10-23: Faster renders and instant clip switching
- Montages render about 35 to 45 percent faster, with exactly the same picture and sound as before
- Switching between CS2, Valorant and Rainbow Six clips is now nearly instant, and the app opens faster
- New "High performance" look in Settings: the same app with a lighter, flat style (Standard stays the default)
- You can choose where the move icon puts clips, and every montage now gets one of all five sky patterns and ten colours, picked from its song

## V8.8.7 - 2026-10-23: Move bad clips out of your montages
- A new arrow icon next to the trash icon in the clip list moves a clip into a folder for its game, so it is never used in a montage again but is not deleted
- Moved clips are kept in E:\Movies\Montager moved clips, with one folder each for Valorant, CS2 and Rainbow Six
- Valorant kills right after a stretch with an empty kill feed are no longer lost when an earlier kill's name could not be read

## V8.8.6 - 2026-10-23: More multikills, real kills only
- Montages are now built from multikills first: every multikill, unused or used before, comes before any single kill, and clips saved right after each other are joined into one fight in every mode and game
- CS2 kills that were already in the kill feed when a clip started are no longer shown as kills, while bots or players killed again later in the same clip now count, so real multikills are no longer dropped
- Full-song montages reach the end of the song again, and the drop no longer turns the music down
- The sky is looked for on more kills and fades out when the camera turns away from it, and it never slides onto a wall

## V8.8.5 - 2026-10-22: Five moving sky patterns, one per song
- The sky now moves smoothly on every frame, and each montage gets one of five patterns picked from its song: flowing bands, drifting amoebas, rippling rings, turning rays or swaying aurora curtains
- The sky colour no longer flashes onto walls or buildings for a frame when it starts, after a cut or when the camera turns
- The final multikill of a montage lands on the beat again, and Auto montages fill the whole song even when most of your clips were used before
- The Game audio level setting changes the game sound again in every game

## V8.8.4 - 2026-10-22: Rainbow Six multikills stay together
- In Rainbow Six every kill in a clip now stays in one take, however far apart the kills are, so no kill is lost any more
- In every game a kill is timed by the moment its kill row appears, and a kill is never dropped just because no gunshot was heard
- The sky colour now clearly changes from top to bottom, following the sky as the camera moves

## V8.8.3 - 2026-10-22: Every montage fills the whole song
- When a song fits the montage length, every mode now runs from the start of the song to its end, adding clips when needed
- Silent stretches at the start and end of a song are cut in every game and every mode
- The sky has one colour family per montage, picked from the song or its album cover, as a clean top-to-bottom gradient
- The sky's pattern is now even, regular bands that move on the beat instead of blotchy shapes

## V8.8.2 - 2026-10-22: Smoother, more colourful sky everywhere
- Valorant, CS2 and Rainbow Six now share one sky look: an even, smooth tint with soft edges instead of blotchy patches
- More sky colours, with a hazy orange sky as a favourite; white or black skies when the song or its cover art suits them and the picture stays clear
- Montages made with Auto fill the whole song and never run into the silence at the start or end of a song
- Every clip's game sound is about equally loud, and renders are faster with the same picture and sound

## V8.8.1 - 2026-10-21: Long montages render again
- Long montages with many clips or long file names no longer fail to start rendering, in every game; the picture and sound are exactly the same as before
- Rainbow Six: every utility kill icon from your icon folder is now left out, wherever the icon sits in the kill row and however long the player names are
- Your whole Rainbow Six library is checked once against all the icons, with progress shown; clips that were checked are skipped afterwards

## V8.8 - 2026-10-21: A sky that hits on every beat
- In CS2 and Rainbow Six the sky now flashes and changes colour on the beat of the song, much wilder than before, and it goes on the drops first: every drop of the song can get one
- Clean 60 fps, full-size clips are picked first; low-quality ones still make it in when the kill is special
- Clips with sound on another audio track are no longer silent, utility kills in Rainbow Six (the skull icon and others) are left out, and fast multikills in CS2 keep all their kills
- Full-song montages skip silence at the start or end of a song and fill the song to the end; clips saved one after another are matched more reliably

## V8.7 - 2026-10-17: A sky that goes wild with hard songs
- The sky now follows the song: hardcore songs get a harsh, flickering sky that strobes, drops to black and jumps to another colour on the beat, chill songs get a calm, slow one
- Sky colours are deeper and richer, never pale; smoke is no longer painted over and the sky no longer blinks on and off
- New switch next to Effects in Settings to turn the sky recolour on or off for each game (off for Rainbow Six by default)
- Fast back-to-back kills at the end of a clip are no longer missed, and the gunshot timing uses the audio track you chose in Settings

## V8.6.3 - 2026-10-17: Manual Auto fixed
- Manual Auto works like before V8.6.1 again and no longer stalls or leaves the montage empty

## V8.6.2 - 2026-10-17: Animated sky, CS2 speed ramp, no more deathmatch clips
- The sky is darker and alive: dark clouds drift and pulse with the beat, and the kill hits with a stronger surge, a push and a shake; a sky that would paint over walls is skipped
- CS2 headline and ending kills now always go slow, fast, slow, and the knife-out gets its own slow-down when the footage allows it
- CS2 deathmatch clips are never picked automatically; clips you tick yourself are never touched
- The music no longer dips at the drop moment
- Manual Auto and planning run about twice as fast, and the log shows collapsed blocks instead of thousands of lines

## V8.6.1 - 2026-10-17: Sky that follows the real sky
- The recoloured sky now follows the real sky shape: rooftops, wires, poles and antennas are cut out cleanly and nothing but sky is coloured
- It is nearly solid (not see-through) in deep red and black, and more skies are found, with the next-best kill used when one has no sky
- Manual Auto only ticks clips the planner can actually place: the montage fills the song and nothing is reported as "didn't fit"

## V8.6 - 2026-10-17: Sky hits on the kill, music and glitch fixes
- The recoloured sky now hits on the kill: it snaps in, flares for a moment, then settles into deep red with dark clouds drifting through it; calm songs get deep blue, teal or violet instead (cover art colours are blended in)
- CS2 headline and ending kills get a speed ramp: slow at the kill, back toward normal, then slow again when the knife comes out
- Fixed: the music was missing in the first part of longer montages
- Fixed: a glitchy, lagging clip in the Valorant montage; clips that freeze while recording are now left out

## V8.5.1 - 2026-10-16: Sky back to the orange look
- The sky recolour is the deep hazy orange again: same picture brightness and detail, only the colour changes, with a soft gradient and a steady edge
- It lands on the kill and stays until the end of that take, never below the middle of the screen
- White flashes: about one per 10 seconds of montage in every style, on the headline, drop and strongest kills first
- The Manual "Auto" button moved next to Song map and Random pick in the song step

## V8.5 - 2026-10-16: Full-length montages, new sky look
- New "Force New Full" button: fills the whole song (up to 2:30) with fitting clips and renders right away
- New "Auto" button in Manual, next to Random pick: ticks enough clips to fill the selected song, nothing is rendered until you click Render
- More kill flashes again, like before V8.4.5
- The recoloured sky now lasts the whole take, in deep hazy colours with a soft gradient, and never goes below the middle of the screen

## V8.4.5 - 2026-10-16: Audio in sync, calmer flashes, better sky
- Game sound no longer drifts early after a clip with a gap in its recording; the same plan now stays in sync to the end
- A clip with a broken, stuttering recording (about 8 frames a second) is no longer used
- The kill flash is a short soft pulse on the drop, the headline and a few strong kills, not on every other kill
- The sky colour follows the song's feel and the clip's colours, and a longer montage can have several recoloured skies
- The drop kill gets a breath before it, a low hit on it and a stronger build-up (EXTRA effects)

## V8.4.4 - 2026-10-16: White flashes and even sky colours
- A render now runs once; if it fails it stops and tells you where, instead of trying again with fewer effects
- The kill flash is back, and it is a clean white flash only
- The sky now turns into one even deep colour, with no blotches, and the rest of the picture stays as it is
- The sky colour is chosen for each montage from the song, so different songs get different colours

## V8.4.3 - 2026-10-16: Extra effects render fix, calmer look
- Montages whose clip has a gap in its sound now finish instead of failing; that part is simply silent
- If a render fails, it now tries at most three times: full effects, fewer effects, then the plain version
- The red and blue colour flashes are gone: no effect covers the picture in a colour any more
- Sky recolour is tried on more kills and still only used where the sky is clear

## V8.4.2 - 2026-10-15: Smarter extra effects, safer renders
- Extra effects are now chosen for each montage from the song and the clips: not every kill gets effects, calm parts stay clean, and beat kills, drops and headline kills get the most
- Two montages with different songs or clips now look different
- Sky recolour is used only a few times per montage and only where the sky is clear
- If one effect ever fails while rendering, only that effect is dropped and the video still finishes
- The log shows which effects were chosen for the montage and why

## V8.4.1 - 2026-10-15: Much more extra effects, per game
- Effects can now be set for each game: CS2, Valorant and R6S (CS2 starts on Extra effects, the others on Default)
- Extra effects now puts a colour flash, zoom and glitch on every kill, stronger on the beat and the drops, with a build-up and afterglow on the drop kill
- Sky recolour on selected kills: the sky takes the colour of the song's feel (red for an aggressive song); it is skipped when there is no clear sky
- Faster run-ups into the kills; the kill itself stays at normal speed and the kill row always stays visible
- Montages can now be up to 180 seconds long

## V8.4 - 2026-10-15: Extra effects mode
- New Effects setting with Default and Extra effects (Default stays the way it was)
- Extra effects adds smoother cuts, flashes and shakes on strong kills, stronger on the beat and the drops
- Kills, their timing and the beat sync are never changed by it, and the kill row always stays visible

## V8.23.1 - 2026-10-15: R6S grenade and gadget kills filtered
- R6S montages now skip grenade and gadget kills, also for clips that were scanned before
- Normal gun kills are not affected

## V8.23 - 2026-10-15: One more R6S gadget kill filtered
- R6S montages no longer show kills made with one more gadget (the one with the small flame-like icon)
- Montages that are already rendered are not affected

## V8.22 - 2026-10-15: Random song pick, faster finish after rendering
- New Random pick button next to the song search: selects one random song from the list shown
- Rendering now finishes as soon as the video is written; the extra quality and sync checks are an optional Settings switch (off by default)
- The plan text no longer lists playlist tracks that have no MP3

## V8.21 - 2026-10-15: CS2 clutch kills no longer cut short
- CS2 montages show the last kill of a clutch
- Game audio level is back as a simple 0 to 1 setting for each game

## V8.2 - 2026-10-15: Smoother cuts, utility kills filtered, faster rendering
- R6S montages no longer show Razorbloom shell, grenade and Caustic gas kills
- Smooth slow-motion now in Valorant and R6S too
- Clips look smooth throughout, not just on the first kill
- The Open video button works as soon as the video is finished
- You can use the rest of the program while rendering
- Faster rendering and scanning
- New per-game audio level under the music

## V8.1.1 - 2026-10-15: CS2 cuts land on the real kills, smoother slow-mo
- Takes no longer start on grenade rows or skip the first real kill
- No more long empty stretches after the last kill
- Slow-mo and effects only play where a kill actually happens
- Slow-motion looks smoother
- Valorant and R6S unchanged

## V8.10 - 2026-10-14: CS2 kills now found by the red border
- Every CS2 kill is now detected by the red border around your row in the killfeed
- Misread names no longer create phantom kills or lose real ones
- Multikills and almost-aces show all their kills
- Assists are no longer counted as kills
- Valorant and R6S unchanged

## V8.0.5 - 2026-10-14: Scan button uses the selected game
- The "Scan all new clips (current region)" button now scans only the game you have selected in the killfeed region section.

## V8.0.4 - 2026-10-14: Scan all new clips button
- New button in Settings (Killfeed region): "Scan all new clips (current region)" scans every clip that has not been scanned yet, for all games, with the killfeed region you have saved.
- Clips that were already scanned are left alone, so the clip counts in Auto, Manual and Random pick update afterwards.

## V8.0.3 - 2026-10-14: R6S utility kills
- Rainbow Six Siege gadget kills (drone, claymore, impact grenade and similar) are now recognised and left out of your montages, like utility kills in Valorant.
- A per-clip switch (right-click a clip in the Manual list) lets you include the gadget kills of that clip.
- The gadget kill icons live in their own icon folder; any image you drop there is used as an extra gadget icon.
- Normal R6S kills are still read from the killfeed text only.

## V8.0.2 - 2026-10-14: Better R6S multikills
- Half-read names on the killfeed (a name that slides in and is first read as only its first letters) no longer turn one R6S kill into two.
- R6S clips saved up to 30 seconds apart can now join into one fight, also chains of three or more, and a later clip never continues a round you died in.
- Every R6S kill of a joined fight is either in the montage or listed with the reason it was left out.
- The two R6S kill icons are supported as an optional extra check; the killfeed text stays the main source.

## V8.0.1 - 2026-10-14: Rainbow Six Siege support
- Rainbow Six Siege is the third game next to CS2 and Valorant: it has its own circle in the Manual list, its own row in Settings and its own output folder.
- Your R6S clips are only read when you tick or pick them, never all at once.
- It works without any icon files: kills are read straight from the killfeed, and icon images in the R6S icons folder are only an extra help.
- Picked clips are always scanned first, then planned, previewed or rendered.

## V7.7.7 - 2026-10-13: CS2 kills now start at the right moment
- A CS2 kill that was already on the killfeed when a clip started is no longer used as the opening kill.
- The last kill of a CS2 multikill is no longer cut off: the take now starts when the kill really appears, not a second or two later.
- Every CS2 take is checked before it is placed, so a take always shows a new kill appearing on the killfeed.

## V7.7.6 - 2026-10-13: Fake CS2 kills and white flashes fixed
- CS2 clips no longer show kills that never happened: old rows still on the killfeed, and one kill counted twice, are now ignored, so montages stop slowing down on an empty killfeed or ending on slow motion of nothing.
- The soft dissolve between two clips no longer flashes white or dips dark: it now blends in even steps.
- More songs are found: an MP3 now matches the playlist by main artist and song title, ignoring featured artists and extras like Remix or Lyrics, and unclear matches are listed instead of guessed.
- The check after each render now counts the CS2 kills correctly and looks for flashes in every transition.

## V7.7.1 - 2026-10-13: SongMap mode, much better music detection
- New SongMap mode setting: V2 (the default) always uses the V2 song map for every song; V2 + V1 Fallback keeps the old safety switch to V1.
- Clips with music already playing are found far more often, and all clips of one fight get the same decision, so a clip never changes volume halfway.
- The amount lowered is now a setting (0 to 60 dB, default 12); the highest value mutes the game sound of that clip completely.

## V7.7.0 - 2026-10-13: Best kill stays on the drop, song lengths
- A strong multikill is no longer dropped from the montage over a tail that ran a few frames too long: the cut is fixed instead, and any clip that still cannot be placed is listed with the exact reason.
- The plan header now tells the truth about which kill sits on which drop, and drops line up with the audible hit of the song.
- Songs show their length in the Songs tab and the Manual list, and the Songs tab can be sorted by date added and by length.
- New option in Settings (off by default): lower the game sound of clips that already have music playing.

## V7.6.1 - 2026-10-12: Far more kills fit, softer cuts
- Clips that end right after the kill are no longer left out: the tail plays in smooth slow motion, so a 70-kill selection no longer shrinks to a 20 second montage. Every event that cannot be placed is listed with the exact reason.
- Almost every drop of the song gets a kill on its exact time (takes can now be re-ordered to reach it), and the main drop is always a real drop of the song.
- Slow motion eases in and out smoothly, cuts between takes dissolve softly where there is footage, and drops are also found where a build-up repeats in the song.
- The song and style in the summary are the ones that get rendered, songs have a trash icon, and the quality check no longer reports false problems.

## V7.6.0 - 2026-10-12: A kill on every drop
- Every drop in the song now gets a kill on its exact time far more often, in CS2 and Valorant, with or without hand-marked drops.
- The montage now ends right after the final kill with a short fade to black, and the unused end of the last clip is cut off.
- The quality check after a render now finds the right frame even when it is a frame or two off, so it no longer reports false quality problems.
- Closing the Song map window early no longer causes an error.

## V7.5.1.2 - 2026-10-08: Drops land on the beat
- CS2 montages now put a kill on every drop in the song where the clips allow it, without needing hand labels.
- Kill timing only moves a kill earlier when the kill row clearly appears on screen at that moment.
- The final fade to black is much shorter and nothing is frozen at the end.

## V7.5.1.1 - 2026-10-08: Kill timing on, editable drops, shorter outro
- CS2 kills are now timed from the moment their row appears on screen.
- In the Song map you can drag a drop line to the real drop, add or remove drops, and press Reset to go back to the automatic map.
- The final fade to black is much shorter, so the last kill stays clearly visible.
- The first clip gets a small zoom punch on the first beat and the last frame is held briefly before the fade.

## V7.5.1 - 2026-10-08: CS2 kill timing groundwork
- The code that dates a CS2 kill from the moment its row appears is stricter now, but it stays switched off for now.
- Nothing in your montages changes.

## V7.5 - 2026-10-08: Headline kill lands on the kick
- When a drop falls between two beats, the headline kill now lands on the kick instead of a beat 0.3 s early.
- All other clips and songs stay exactly as they were.

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
- A first test of a better beat grid and drop map on a set of generated and real songs. Real montages still use the old map.

## V6.9.11 - 2026-10-07: Readable changelog in Settings
- The changelog in Settings now shows this short plain-language history.

## V6.9.10 - 2026-10-07: CS2 phantom kills from stale feed rows removed
- A kill that was already on the killfeed when the clip started is no longer counted again a few seconds in.
- This stops takes that started after the kill or showed a kill twice.

## V6.9.9 - 2026-10-07: Weekly render fix
- Valorant weekly "Force new" can render again; clips saved back to back no longer leave a gap that stopped the render.
- One bad take no longer cancels the whole render; it is skipped and logged.
- Weekly runs no longer report hundreds of "lost" kills that were not lost.

## V6.9.8.1 - 2026-10-07: Smoother clips by default, whole multikills
- Frame smoothing of low-frame-rate clips is now off by default.
- Random and weekly picks keep a multikill whole even when its other clips were used before.

## V6.9.8 - 2026-10-07: Companion clips for random and weekly picks
- Random and weekly picks now pull in the other clips of a multikill, so a 3K stays a 3K (both games).
- CS2: a victim read twice in one clip is one kill (a 2K was shown as a 3K).

## V6.9.7.2 - 2026-10-07: Behind-the-scenes fixes only
- Behind-the-scenes fixes only.

## V6.9.7.1 - 2026-10-07: Clips linked by save time
- Clips saved right after each other are linked by their real save time into one fight and one stitched take.
- Fights inside a long clip stay one fight for up to 30 seconds.
- Valorant utility kills that the OCR read twice are counted once.

## V6.9.7 - 2026-10-07: Kill ledger + per-clip utility kills
- Every kill now ends up as placed, merged duplicate, ranked out or lost, and the log says which.
- Valorant: a per-clip override can count utility kills, and Settings has a switch for low-frame-rate smoothing.
- Clips that show the same fight are merged only when the kills and frames really match.

## V6.9.6 - 2026-10-07: Smarter fps check + stitch order fix
- The low-frame-rate check looks at the frame rate you actually see on screen.
- Stitched CS2 clips are put in the right order.
- Tools added to inspect clip pairs and their order.

## V6.9.5.2 - 2026-10-07: Song map V2 tempo lock
- The V2 beat grid locks to a steady tempo and no longer produces impossible tempos.
- Settings has a new "Songmap V2 (auto, V1 fallback)" choice; the default stays Songmap V1.

## V6.9.5.1 - 2026-10-06: Song map V2 fixes
- Song map V2 no longer crashes on some songs or shows broken loudness numbers.
- If V2 fails on a song during a montage, that song falls back to the old map.
- The comparison tool saves its results after every song.

## V6.9.5 - 2026-10-06: Song map V2 added
- An optional second beat analysis (Songmap V2) can be picked in Settings and compared with the old one. The old map stays the default.

## V6.9.3 - 2026-10-06: Repo cleanup + frame interpolation
- Low-frame-rate clips can be smoothed at render time.
- The project folder is tidied: tests and notes moved into their own folders.

## V6.9 - 2026-10-06: Multikills split across clips
- CS2: when a fight was recorded as 2-3 consecutive clips, the neighbouring clips are pulled in and stitched into one take.

## V6.8.2 - 2026-10-06: CS2 border tracking fixes
- CS2 kill detection around the red outline is more reliable: fewer non-kill shapes, fragments of one row are merged, and rows already on screen at the clip start are not counted.

## V6.8.1 - 2026-10-06: CS2 red-border row tracking
- CS2 kills are now found through the red outline around your killfeed rows.
- Settings can rescan only the clips of one killfeed region group.

## V6.8 - 2026-10-06: Killfeed region picker
- New killfeed region picker in Settings, with a saved default region per game.
- A search bar above the Manual clip list.

## V6.7.6 - 2026-10-06: Valorant killfeed region recovery
- Tools to check and restore the killfeed region of Valorant clips.
- A changed region no longer triggers a Valorant rescan by itself, and the calibration dialog asks for confirmation.

## V6.7.4 - 2026-10-06: Montage title and trash in the clip list
- The "Used" column shows the title of the montage a clip was used in.
- Every clip row has a trash icon that moves the file to the Recycle Bin after you confirm.

## V6.7.2 - 2026-10-05: CS2 kill count on garbled reads
- CS2 rows are tracked by position, so garbled name reads no longer inflate the kill count.
- The 150 s length setting now really gives 150 s.

## V6.7 - 2026-10-05: CS2 kill count fixes
- Garbled name reads no longer inflate the kill count; knife and revive rows are handled.
- The killfeed region is remembered and protected against bad values.

## V6.5.2 - 2026-10-05: Flag a clip as used
- Clicking an empty "used" cell in the Manual list flags the clip as used.

## V6.5.1 - 2026-10-05: Weekly minimum and Unflag all
- Weekly / Auto montages are at least 60 s.
- New "Unflag all" button (with a backup), and clicking a used date unflags that clip.

## V6.5 - 2026-10-05: Exact song matching
- Song files named "Title - Artist1, Artist2" are matched to the right track.

## V6.1.5 - 2026-10-05: One-line Manual status
- The Manual tab shows its summary on one fixed line; the full summary goes to the log.

## V6.1.3 - 2026-10-05: Stable start and clip opening
- The window no longer freezes while clips load at startup.
- Songs still being written are skipped instead of causing errors.
- Song matching is remembered between launches.
- New "Open" column in the Manual list and double-click to open a clip.
- The fixed length slider goes from 80 to 150 s.

## V6.1.2 - 2026-10-05: Song matching remembered
- Matched songs are remembered between launches, and the Manual tab no longer waits for matching.

## V6.2 - 2026-10-05: Behind-the-scenes timing tools
- Behind-the-scenes fixes only: a timing recorder to find slow startup and theme switches.

## V6.1 - 2026-10-05: Loading window and calmer tabs
- A small loading window with a progress bar appears first.
- Switching tabs no longer refills lists.
- The automatic status refreshes in the background, and ffmpeg runs at lower priority so the window stays responsive.

## V6.0 - 2026-10-05: Auto length fits the song
- Auto / weekly length follows the same 80-150 s fit rule as Manual and never goes past the song.
- A silent game audio track is replaced by the loudest one for that clip only.
- New Player names setting.
- Weekly picks only use unused clips, this week's first.

## V5.6 - 2026-10-05: Window appears all at once
- The window is built hidden and shown in one step, and lists fill in one pass instead of row by row.

## V5.58 - 2026-10-05: Live themes
- Changing accent colour or base in Settings applies at once, without a restart.
- Switching tabs no longer reloads them.
- The window title shows V5.58.

## V5.57 - 2026-10-05: Calmer controls and themes back
- The mouse wheel never changes a value any more.
- Settings has a tidy grid with a fixed Save bar at the bottom.
- Accent colours (6) and base (grey or black) are back.
- Buttons show hover, busy and result feedback.

## V5.56 - 2026-10-05: Montager name and audio track pick
- The app is called Montager and has its own taskbar icon.
- Choose which game audio track to use per game; a silent track is never picked.
- Settings save automatically.

## V5.55 - 2026-10-05: New look
- Sun Valley theme, draggable dividers that are remembered, a "used" column and filter.
- Random pick uses the Optimal fit, and Render shows the plan first.

## V5.5 - 2026-10-05: Launcher and safer updates
- A launcher with an icon, and an optional update check on start.
- The kill cache survives updates.
- Valorant knife kills count; a rejected stitch is planned again on the single clip.

## V5.44 - 2026-10-05: Details not recorded
- Details not recorded.

## V5.43 - 2026-10-05: No kill in two takes
- A kill never appears in two takes, and fake duplicate kills are dropped (Valorant and CS2).
- The take's end is only ever extended, never cut early.

## V5.42B - 2026-10-05: Clearer kill rules
- A take always runs at least 0.4 s past the last kill row.
- Two files showing the same kills count as one event.
- Optimal uses 80-150 s and lists clips that did not fit.
- Knife and revive rules apply to Valorant only.

## V5.42 - 2026-10-05: Revives are not kills
- A green victim in the killfeed means a revive, never a kill or death; knife blades are excluded.

## V5.41 - 2026-10-05: Jump-cuts in long multikills
- Long multikills cut out dead air, as much as the music allows.
- Optimal fits the song and lists clips that did not fit.
- Sage resurrect rows are not kills.

## V5.4 - 2026-10-05: Montage fits the song
- A montage is never longer than the song section.
- The status estimate is the real plan, and the style is chosen from the song and the material.
- The plan explains the chosen length and style.

## V5.3 - 2026-10-05: One fight, one take
- One fight is one event and one take; Clove self-revive rows are never kills.

## V5.2 - 2026-10-05: Zoom punches and file names
- Only centred zoom punches remain: no flashes, no zoom or flash cuts.
- Renders no longer stop when a kill row falls outside its take; zoom is smooth with no shake.
- Output files are named SONG_GAME_VERSION_DATE.mp4, and the version shows in the window title.

## V5.1 - 2026-10-04: Frame-exact kills
- Kills are placed frame-exactly and music starts from the first frame.
- The ending slows down with music and picture fading from the final kill.
- Optimal length and Auto style are the defaults.

## V5 - 2026-10-04: Song-map driven montage
- Explicit Valorant and CS2 clip folders.
- Songs get a beat map with downbeats, sections and drops.
- Montages are built from the map: kills on the beat, a strong clip on every drop, and five style recipes.
- Clips of one multikill are stitched; no clip is used twice.

## V4 - 2026-10-04: Kills read with OCR
- Kills are read from the killfeed text instead of image matching.

## V3 - 2026-10-04: Row-first kill detection
- Kills are read row by row (killer and victim), results are cached per clip, and songs are matched one to one.

## V2 - 2026-10-04: Folder-only clips and a rebuilt GUI
- Clips come from folders only, detection checks several scales, and the planner places kills on the song frame-exactly.

## V1 - 2026-10-04: First complete montage builder
- The first complete tool: GUI, kill detection, song analysis, planner and renderer.
