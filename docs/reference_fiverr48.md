# Reference montage: "Fiverr 48 (2)" (CSGO, someone else's edit)

Measured for V8.4 (notes for future versions). Source file: `E:\Movies\Montages\Fiverr 48 (2).mp4`.
Nobody watched it; everything below comes from decoded frames, ffmpeg scene scores, optical flow, the montager's own killfeed
border tracker and librosa / ffmpeg audio analysis. Each statement is tagged **[measured]** (a number from the file),
**[seen]** (looked at extracted frame strips) or **[guess]** (an interpretation the numbers allow but do not prove).
The per-frame measuring script is `tests/ref84_measure.py`.

## File
- 2720x1530, 60 fps, h264; AAC stereo 48 kHz; 202.9 s (3:23). **[measured]**
- The game HUD is kept in full (radar, money, health, killfeed, chat). Nothing is cropped or covered. **[seen]**

## Structure / pacing
- **0 to ~14 s: free-camera fly-through of a map** with hand-lettered title cards ("... Network presents", then a channel / series name)
  while the picture fades in from black (luma 11 -> 91 over about 2.5 s) and the music starts very quiet (about -19 dB RMS). **[seen] [measured]**
- First HUD gameplay at about 14 s; the first red-outlined kill row (the montager's CS2 border tracker, 33 distinct rows of 0.4 s or more) is at 38 s. **[measured]**
  The first kills land exactly where the music has built up to full level (loudness climbs from -19 dB to -7 dB RMS between 17 s and 40 s). **[measured]**
- 33 kill rows in 203 s: after the intro one every ~5 s; clips are long gameplay stretches, not kill-only snippets. **[measured]**
- Cut rhythm: 48 hard cuts with ffmpeg scene score > 0.25 (median 2.7 s apart; 113 above 0.2, 195 above 0.15 because fast aiming also scores). **[measured]**
  "Big" transitions (below) are 24, median 7.6 s apart (10 / 90 percent: 1.7 s / 13 s). **[measured]**
- From a big transition to the next kill row: median 4.4 s (quartiles 1.4 / 8.1 s); from a kill row to the next big transition: median 5.2 s
  (quartiles 2.5 / 9.4 s). The kill is not held for a fixed tail; many clips contain 2 to 5 kills (kill rows per clip: 9 clips with 1, 4 with 2, 2 with 3, 2 with 5; 7 clips without a visible row). **[measured]**
- Outro: video fades to black over the last ~4 s (luma 72 -> 11) while the music fades out over the last 5 s (-6 dB -> -59 dB). **[measured]**

## Cuts, kills and the beat
- Music tempo about 103 BPM (beat interval 0.58 s; the tracker may also be counting half time). **[measured]**
- **The edit is not beat-locked.** Kill rows within +-0.1 beat of a beat: 18 % (chance is 20 %); cuts within +-0.1 beat: 15 %; big transitions: 12 % (46 % within +-0.2, chance 40 %). **[measured]**
  Our montages are the opposite (every first kill on a beat), so the reference's "feel" does not come from beat-locking. **[guess]**
- Music structure: loudness jumps > 3 dB in 1 s at 17.8, 25.1, 29.6, 37.2 and 78.7 s; clear dips (> 4 dB under the local level, a breakdown before a drop) at 25.1 and 78.6 s. The second drop (78.7 s) has a gameplay kill row at 80.0 s two seconds later; there is no cut or effect measured exactly on either drop. **[measured]**

## Transitions and effects (video)
| Effect | What the frames show | How often | Tied to kills? | Tied to beats? |
|---|---|---|---|---|
| **Mirror-edge zoom-out at a cut** | 1 to 3 frames in which the picture is shrunk to 50 to 80 % and the empty border is filled with mirrored copies of the picture (a 4-way kaleidoscope look of the HUD), then the new clip. Single-frame scale ratio < 0.82 or > 1.3 in the optical-flow fit. **[seen] [measured]** | 24 in 203 s (about every 8 s) | No: 5 of 32 kill rows (after 25 s) are within 1 s of one (16 %; random times: 23 %) | No (12 % within 0.1 beat) |
| **Zoom pulse around a cut** | Frame-to-frame scale ratios such as 1.03, 1.06, 1.12, 1.18 into the cut (accelerating zoom-in) and 1.12, 1.06, 1.03 after it (decelerating): about 8 frames (0.13 s), up to +20 to +50 % scale. 114 groups with a > 4 % single-frame scale change = one every 1.8 s. **[measured]** Ordinary forward movement in the game also scales, so some of these are not an effect. **[guess]** | about every cut | No | No |
| **Brightness jump at the cut** | Mean luma +17 on the first frame of the new clip, frame difference 31 versus a 5 to 10 baseline. **[measured]** Probably just a different clip, not an effect. **[guess]** | every cut | No | No |
| **Zoom / flash / shake on the kill** | Event-triggered averages around the kill row (frame difference, sharpness, global motion, luma) show nothing above the noise. **[measured]** | n/a | **Not found** | n/a |
| **Slow-mo, speed ramps, freezes** | Only 1.8 % of frames have no change at all and the 16 still runs of 0.4 s or more are title cards / black. No sustained low-motion stretch around kills. **[measured]** | none found | no | no |
| **Colour grade / overlays on kills** | Saturation stays about 70 (+-5 around cuts); no tint or vignette change near kills. **[measured]** Title cards in the intro and a few subtitle-style captions ("Show me how it's done fire" at about 24 s). **[seen]** | intro only | no | no |

So **in the reference the effects belong to the cuts, not to the kills.** The kills are shown as they happen, at 1.0x, with the full HUD.
Our current style puts every effect on the kill. **[guess]** that adding the cut-side effects (settle zoom, mirror frames) is what makes the reference feel "edited".

## Audio
- Integrated loudness -4.8 LUFS, loudness range 6.9 LU, true peak +1.1 dBFS (it clips slightly): a very loud master. **[measured]**
- RMS per 10 s after the build-up: -6 to -8 dB, steady. Short-term variation std 5.5 dB. **[measured]**
- **No game audio tied to kills:** the event-triggered RMS / low-band / high-band (> 4 kHz) / onset curves around the 33 kill rows are flat (within +-0.5 dB) and no louder than around random times. Gunshots are not audible in the mix. **[measured]** Most likely game audio is muted or far below the music. **[guess]**
- No ducking of the music around kills (RMS flat). A small dip of about 0.5 dB just before the big transitions. **[measured]**
- The music has a quiet intro (about 38 s of build-up) before it opens up. Our montages start the music at full level (0.3 s fade-in). **[measured]**

## Ideas for our montages (not built yet)
1. Cut-side effects instead of (or besides) kill effects: a short zoom-settle after every cut, a mirror-edge zoom-out on some cuts. (V8.4 EXTRA EFFECTS builds these.)
2. A quiet intro (picture fade-in with a title and the music building), with the first kill on the full-volume entry. Needs a song map "build up" detection and an intro clip: not possible in the current planner without touching beat / song planning.
3. Longer clips with 2 to 5 kills and room before the first kill (median 4.4 s run-up): our takes use 1 to 2 s run-ups.
4. Less than one beat-locked first kill per take: the reference never locks kills to beats yet still feels tight because cuts are short (2.7 s median).
5. A very loud, limited master (-5 LUFS): our mix keeps 2 dB headroom, measure how loud our renders are before changing.
6. Title / caption overlays: not built (text rendering and fonts are not part of the pipeline).

## What V8.4 could and could not copy
- Built (EXTRA EFFECTS): zoom-settle after cuts, mirror-edge zoom-out frames at some cuts (strong beats first), kill flash and kill shake on strong kills that keep the killfeed row untouched, beat-strength-scaled zoom punch.
- Not built, with reasons:
  - **True zoom-through transition across the cut** (outgoing clip zooming in on its last frames): the last 0.4 s of every take must show the kill row unchanged (tail rule), so the outgoing side cannot be scaled.
  - **Title cards / captions / fly-through intro:** no text rendering and no free-camera footage in the pipeline.
  - **Quiet music build-up intro:** the song start and the first-kill-on-a-beat plan are fixed by the planner (frozen).
  - **Per-kill colour grading:** the reference has none; nothing to copy.
  - **Slow-mo / speed ramps like the reference:** the reference has none.

## Raw numbers
- 12,176 frames analysed at 320x180; flow fit reliable on 99 % of frames.
- Scene scores: 438 frames above 0.1, 195 above 0.15, 113 above 0.2, 48 above 0.3, 23 above 0.4, 17 above 0.5.
- Kill rows used: border tracks of 12 or more frames at 30 fps (0.4 s), merged within 0.8 s: 33.
