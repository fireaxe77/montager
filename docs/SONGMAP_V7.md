# SONGMAP V7 test (branch v7-songmapv2, not merged)

Goal: a better song map (beat grid, downbeats, drops, honest confidence) in V1's exact shape; Songmap V1 stays the default.

## B0 facts

- V1 BPM = the playlist CSV tempo when there is one (`bpm0 = csv`, tracker tightness 400), else librosa; phase from librosa onsets on the same ffmpeg decode the renderer uses. A wrong CSV tempo therefore gives a wrong V1 grid (Silicon XX: V1 115, audio 175).
- The planner reads: beats, down, drops/drop, sections (start_t), energy, level, dur, steady, bpm, phrase4, section_of_beat.

## Song-level baseline (before) vs after, beat-to-kick median ms on an independent detector (cov = share of beats with a kick within 15 % of a beat)

| song | V1 BPM | V2 before BPM / conf / median | V2 after BPM / conf / median | gate (auto) |
|---|---|---|---|---|
| Silicon XX - S3RL, Nikolett.mp3 | 115.01 / 37.11 | 114.81 / 0.20 / 35.94 | 175.0 / 0.75 / 5.03 | v1 |
| pretty afternoon - Andrah.mp3 | 142.97 / 31.5 | 138.87 / 0.14 / 31.35 | 136.5 / 0.30 / 29.61 | v1 |
| prety - Riversmelt.mp3 | 92.2 / 25.64 | 180.95 / 0.14 / 25.26 | 114.88 / 0.36 / 21.38 | v2 |
| Beautiful Now - Zedd, Jon Bellion. | 174.97 / 23.26 | 128.0 / 0.80 / 5.54 | 128.0 / 0.80 / 5.6 | v2 |
| Beautiful Now - Yosuf.mp3 | 91.05 / 43.94 | 183.98 / 0.17 / 24.06 | 154.87 / 0.37 / 20.41 | v1 |
| life kinda sucks - korin.mp3 | 140.13 / 24.86 | 140.64 / 0.13 / 38.39 | 187.53 / 0.31 / 23.39 | v1 |
| too much (hardtekk) - bullish.mp3 | 143.56 / 17.39 | 143.72 / 0.29 / 31.94 | 142.41 / 0.46 / 23.17 | v2 |
| #eurodab - Käärijä, Baby Lasagna.m | 138.99 / 34.13 | 139.88 / 0.20 / 33.16 | 115.89 / 0.26 / 33.46 | v1 |
| ALWAYS BEEN MINE - nervexx, K4tami | 118.8 / 11.27 | 118.99 / 0.79 / 4.51 | 118.99 / 0.77 / 5.42 | v2 |
| 530 - DONDA, Kanye West, Ye.mp3 | 156.6 / 28.7 | 160.03 / 0.49 / 23.09 | 160.05 / 0.55 / 21.8 | v2 |
| 24 songs - Six Zeta.mp3 | 127.0 / 33.71 | 125.03 / 0.11 / 33.27 | 168.0 / 0.58 / 12.54 | v2 |
| AI Slop - Remzcore, S3RL.mp3 | 159.97 / 22.43 | 159.19 / 0.11 / 27.87 | 95.01 / 0.42 / 29.59 | v1 |
| 16 - Baby Keem.mp3 | 94.03 / 23.32 | 188.0 / 0.49 / 16.62 | 94.0 / 0.49 / 15.81 | v2 |
| A Bar Song - Supermassive.mp3 | 88.34 / 14.33 | 176.0 / 0.46 / 8.99 | 175.99 / 0.41 / 9.13 | v2 |
| (nendest) narkootikumidest ei tea  | 140.04 / 33.07 | 145.0 / 0.79 / 6.37 | 145.0 / 0.78 / 6.57 | v2 |

## Plan-level (existing dry planner, same takes/seed/song): first kill of each take + last kill of each multikill vs nearest independent kick, ms

| song | map used | V1 median / p95 | V2-auto median / p95 |
|---|---|---|---|
| Silicon XX - S3RL, Nikolett | V2 | 38.4 / 394.4 | 20.0 / 370.1 |
| pretty afternoon - Andrah | V1 | 39.8 / 624.8 | 39.8 / 624.8 |
| prety - Riversmelt | V1 | 27.7 / 486.2 | 27.7 / 486.2 |
| Beautiful Now - Zedd, Jon Bellion | V2 | 34.8 / 1885.9 | 163.9 / 2340.2 |
| Beautiful Now - Yosuf | V1 | 26.8 / 1365.5 | 26.8 / 1365.5 |
| life kinda sucks - korin | V1 | 130.8 / 2600.2 | 130.8 / 2600.2 |
| too much (hardtekk) - bullish | V1 | 32.0 / 677.5 | 32.0 / 677.5 |
| #eurodab - Käärijä, Baby Lasagna | V1 | 32.0 / 287.8 | 32.0 / 287.8 |
| ALWAYS BEEN MINE - nervexx, K4tami | V2 | 11.1 / 25.1 | 30.8 / 6038.1 |
| 530 - DONDA, Kanye West, Ye | V2 | 61.8 / 406.3 | 31.7 / 364.4 |
| 24 songs - Six Zeta | V2 | 481.2 / 4430.8 | 206.0 / 4558.1 |
| AI Slop - Remzcore, S3RL | V1 | 50.2 / 903.2 | 50.2 / 903.2 |
| 16 - Baby Keem | V1 | 23.5 / 167.0 | 23.5 / 167.0 |
| A Bar Song - Supermassive | V1 | 91.2 / 3975.3 | 91.2 / 3975.3 |
| (nendest) narkootikumidest ei tea  | V2 | 26.0 / 4339.8 | 294.1 / 5182.6 |
| No Time To Die - Billie Eilish | V1 | 36.0 / 94.6 | 36.0 / 94.6 |
| Better Now - Post Malone | V1 | 132.4 / 5038.4 | 132.4 / 5038.4 |
| 2 time zones - bbno$, Night Lovell | V1 | 56.2 / 1659.8 | 56.2 / 1659.8 |
| INSONAMIA - Angelcore - Ronald Fig | V2 | 47.5 / 200.2 | 17.7 / 127.1 |

## Verdict

- Genre suite (14 generated genres, known truth): all targets met (grid error < 10 ms / < 20 ms for swing and drift, p95 < 25 / 40 ms, tempo, downbeats, no NaN; ambient gives no grid).
- At plan level V2-auto is NOT clearly better: where the gate picked V2 it was better on Silicon XX, DONDA, INSONAMIA, Six Zeta (median), worse on (nendest), ALWAYS BEEN MINE, Beautiful Now (Zedd). The grid itself is closer to the kicks, but V2's section/start choice puts the montage in different parts of the song (sometimes kick-less), which dominates the plan-level numbers. Success rule B8 is not met; the default stays V1 and nothing is merged.
- Likely next step if wanted: make V2 sections/drops agree with V1's window choice (or ship only the beat grid with V1's sections).
- Test note: the old frozen tests (test_v695 / v6951 / v6952) still pass their functional checks; their git-diff-against-old-base and byte-identical-data checks fail by design today (old bases, running app rewrites caches).