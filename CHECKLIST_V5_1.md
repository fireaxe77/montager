# V5.1 progress checklist

Real-data note: no `testdata/` folder exists in the repo or in the build sandbox, so every "real render" check below runs on
generated clips / songs that mimic real ones (killfeed rows, gunshots, multikills, deaths, continuations, sectioned songs).

| # | Step | Status |
|---|------|--------|
| 1 | Engine from V4 (planner, effects, render, audio mix) + clean start, slow-mo ending with aligned fades, output length = plan | done (renders: duration = plan, music from 0, fades from the final kill) |
| 2 | Port proven V5 parts (detection upgrades, clip folders, no reuse, UI scale, sorting, Song map view, SSIM, CLI, smoketest) | done |
| 3 | Duplicates + stitching, verified (frame-matched cut, fallback to best single clip) | done (difference 0.0 at the cut, codes continuous) |
| 4 | Take rules verified on the rendered file | done (detector + barcode on both renders: kills inside, tails 0.2-0.5 s, 1.0x frame-exact) |
| 5 | Song map: selective drops + `songcheck` | done |
| 6 | `synccompare` (V4 vs V5 placement, measured from files) | done (V5 placement wins) |
| 7 | Variety: 5 recipes within V4 effect strength, no shake / blur | done (planner_selftest: 4 seeds differ in order/recipe/transitions) |
| 8 | Optimal length | done (default; GUI Manual + Settings; 30-120 s) |
| 9 | Auto style | done (default; from energy / BPM / drop, seed picks among close recipes) |
| 10 | No-regression checklist, GUI smoke, detectcheck, audio tone check, generated "testdata" renders | done (smoketest PASSED; tone spread 0.23 / 0.55 / 0.60 dB; CS2 + Valorant render checks OK) |
| 11 | Commit + push | done |
