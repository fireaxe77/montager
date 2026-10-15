# Reference montage: "Fiverr 48 (2)" (CSGO, someone else's edit)

Corrected analysis for V8.4.1 (it replaces the V8.4 notes). Source: `E:\Movies\Montages\Fiverr 48 (2).mp4`, 2720x1530, 60 fps h264, AAC 48 kHz stereo, 202.9 s.
Nobody watched it; everything comes from decoded frames, ffmpeg scene scores, optical flow, audio analysis (librosa, ffmpeg ebur128) and frame strips that were looked at.
Tags: **[measured]** = a number from the file, **[seen]** = looked at extracted frame strips, **[guess]** = an interpretation the data allows but does not prove.

## CORRECTED: what the V8.4 notes got wrong
- **CORRECTED:** "33 kill rows (found with the montager's CS2 border tracker)". The tracker does not work on a CSGO killfeed; the number was wrong and is discarded.
- **CORRECTED:** "the effects belong to the cuts, not the kills". Wrong. It came from those wrong kill times (event averages around times that were not kills show nothing). The frame strips show colour effects on the shots / kills (below).
- **CORRECTED:** "no flash / colour effect tied to kills", "no zoom pulse on kills": the colour effects are there; the zoom numbers still cannot separate an added zoom from in-game camera movement ([guess] below).
- Still true: the file facts, the intro, the music facts, the outro fade, and the mirror-edge zoom-out at cuts.

## What is solid (and what is not)
- **Kills** can be found in this video: the CSGO killfeed marks the player's own kill rows with a **red outline** [seen: crop of the top-right at 40.5, 41.5, 54.8, 68.4 s]. A detector for thin red horizontal lines in a native-resolution crop of the killfeed (rows = lines / 2, persisting >= 25 frames) finds **66 row appearances after 14 s** [measured]. Not every one is verified against the footage, and a row appears slightly after the shot: use them as kill times to about +-0.1 s, not as shot times.
- **Beat grid** of the music: period **0.5882 s = 102.0 BPM**, phase stable within +-10 ms across the whole file [measured: grid fit on onset strength, checked per 20 s window]. (The tracker's 103.4 BPM was an average of a drifting estimate.)
- **Beat relation of the kills: NOT confirmed.** Against that grid the 66 row appearances are spread evenly (circular concentration R = 0.12 at one per beat, chance level 0.12; at 4 per beat 0.14, 6 per beat 0.19, chance 0.12 to 0.14) [measured]. Muzzle-flash detectors (luma rise in the weapon area, yellow pixels) also show no concentration on the beat, on the beat, 1/2, 1/3, 1/4, 1/6 or 1/8 subdivisions [measured]. So I cannot back up "every kill / every bullet lands on a beat" with numbers. Possible reasons: the row appears a variable time after the shot; my shot detector is too crude; or the claim holds for some clips only. **I will not show a number I cannot back up. To measure it I need timestamps from you (below).**
- **Spray timing** [seen]: automatic fire shows a muzzle flash about every 0.09 to 0.10 s (2 frames at 20 fps strips). One sixth of a beat is 0.098 s, so a spray could sit on 1/6-beat triplets [guess]. Not measurable without shot times.

## Kill-tied effects (seen in frame strips, 20 fps, around kill rows at 40.9, 57.3, 98.4 s)
| Effect | What the frames show | Length | Strength | Relation to the kill / beat |
|---|---|---|---|---|
| **Colour glow / bloom flash** [seen] | A large yellow-white (most often), sometimes red or orange wash over the picture, strongest on the right / bright part, with a green-cyan fringe at the peak (a lens-flare / glow look). Peak after 1 frame, then fades. Red glow right on the target at the first shot, yellow wash while the burst fires. | about 0.15 to 0.3 s (3 to 6 frames at 20 fps), fast attack, exponential-looking decay | very strong at the peak: the whole frame goes yellow, the killfeed region tinted too (frame at 41.5 s) | at the shots of a burst; repeated every shot of a spray (every ~0.1 s) [seen] |
| **Luma rise at kills** [measured] | Mean picture brightness rises 5 to 7 levels on average around kill rows (median rise 19.8 vs 12.4 around random times); 26 of 66 kill rows have a rise > 25 within -0.1 to +0.5 s. Part of this is the in-game muzzle light [guess]. | | | |
| **Warm colour wash on the sky area** [measured] | Upper-left picture (sky) moves toward yellow / orange / red by > 35 levels: 21 events after 14 s, hue 4 to 65 degrees (yellow, orange, red), half-width 0.03 to 0.7 s (median 0.25 s); 17 % of kill rows have one within 0.5 s (random times 8 %) | median 0.25 s | up to +124 levels | related to kills but not on all of them |
| **Zoom punch on kills** | The numbers cannot separate a punch from the camera moving [guess: there is none or it is small]. No event-average zoom around kill rows [measured]. | | | |
| **Shake on kills** | No kill-aligned jump in global motion [measured]. | | | |
| **Slow-mo / speed ramps / freezes** | Only 1.8 % of frames repeat the previous frame; no stretch near kills with a sustained drop in motion [measured]. Frame strips around the kills show a normal flowing movement [seen]. **No slow-mo, ramp or freeze found around the kills I looked at.** Between the kills of a multikill the gaps are 0.4 to 1.4 beats [measured], not whole beats, so the gaps are not retimed to the beat [guess: this is the natural spacing]. | | | |

## Sky colour effect
- **Seen:** at 41.5 s the whole upper picture and the killfeed rows go yellow-orange (kill 2 of a 3-kill burst). In other frames the glow is red or orange. The killfeed text and its red outline stay readable, tinted by the same colour [seen].
- **Measured:** 21 warm washes of the sky region (see the table), hues in the yellow / orange / red range only (no blue or green wash found), median length 0.25 s.
- **Not established:** that the colour follows the song's feel (red for a red-feeling song). I cannot judge the song's feel from the numbers. **I cannot tell a deliberate sky recolour from a glow flash and from in-game muzzle light with these data** [guess: the yellow wash at 41.5 s is the colour effect you describe].

## Drops
- Music loudness jumps > 3 dB in 1 s at 17.8, 25.1, 29.6, 37.2 and 78.7 s; clear dips (a breakdown before a drop) at 25.1 and 78.6 s [measured]. The first red-outlined kill row is at 39.7 s, just after the 37.2 s step; the next burst of kills (57.6 to 58.9 s, 66 to 80 s) has no extra effect that I can measure on the drops themselves. **I have no per-drop effect numbers.** Timestamps of the drops from you would settle it.

## Cuts and transitions (unchanged from V8.4)
- 48 hard cuts with scene score > 0.25 (median 2.7 s apart). **[measured]**
- **Mirror-edge zoom-out at some cuts:** 1 to 3 frames shrink the picture to 50 to 80 % and the border is filled with mirrored copies; 24 times in 203 s (about every 8 s). **[seen] [measured]**
- Zoom pulse around cuts (frame-to-frame scale 1.03 / 1.06 / 1.12 / 1.18 into the cut, decelerating after it): 114 groups, about every 1.8 s; ordinary forward movement also scales, so some are not an effect. **[measured] [guess]**

## Intro, outro, music, pacing (unchanged)
- 0 to ~14 s: free-camera fly-through of a map with hand-lettered title cards; picture fades in from black (luma 11 -> 91 over 2.5 s) while the music starts very quiet (about -19 dB RMS) and builds to full level by ~40 s. **[seen] [measured]**
- Outro: picture fades to black over the last ~4 s, music fades over the last 5 s (-6 -> -59 dB). **[measured]**
- Loudness -4.8 LUFS integrated, LRA 6.9 LU, true peak +1.1 dBFS: a very loud master. **[measured]**
- Game audio: no audio events at the kill-row times (flat RMS / low / high band curves), so the game sound is very quiet or absent in the mix. **[measured]** (This used the *wrong* kill times in V8.4 and is therefore re-stated as "not seen at the 66 row times"; shots may still be audible; not re-checked per shot.)
- Pacing: 33 to 66 kill appearances in 203 s depending on the detector (the real number of kills is probably about 40 to 50). Clips are long gameplay stretches with several kills. **[guess]**

## What I need from you to measure the rest
Please give me, for **five clips** of the reference, the times (mm:ss.s) of:
1. the **killing shot** of 5 kills (2 of them in a multikill where every bullet is on the beat; for those, the time of every bullet),
2. 3 kills that carry a **visible effect** (with a word for it: zoom / flash / shake / colour / speed),
3. 1 kill where the **sky colour changes** (start and end of the colour),
4. the **drops** (start time) and what the picture does there,
5. one place with **slow-mo or a speed ramp**, if there is any.
With those I can measure the effect lengths, strength, the beat fraction of each shot and the speed changes properly.

## What V8.4.1 builds from this (see the changelog)
- Colour glow flash and white flash on every kill (the song's feel colour; stronger on the beat and the drop), colour split, zoom punch, build-up and afterglow on the drop kill, sky recolour attempt, settle and mirror cut. All of it is an educated copy of the *seen* effects, not a measured copy.
- **Not built (and why):** speed changes between the kills of a multikill (the reference does not seem to have them; the kills stay at 1.0x anyway); slow-mo in new places (changes the take lengths and the tail fit, planner is frozen); title cards / fly-through intro; the quiet music build-up intro; a zoom-through transition across a cut (the last 0.4 s of every take must show the kill row unchanged).
