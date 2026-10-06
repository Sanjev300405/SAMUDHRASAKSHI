// Re-exports the generated mirror of contracts/contracts.py (ARCHITECTURE.md
// §4 + §8.2). Do not redeclare these shapes here — edit contracts.py and run
// `python contracts/generate_ts.py`, which regenerates contracts.generated.ts.
//
// `BestRelease.simulated_geometry` is a real field on the Python contract
// (see BestRelease's docstring in contracts.py) — the spec names BestRelease
// only inline ("winning (time, lon, lat, hit_rate, iou)") without a frozen
// shape, and the swipe comparator (§7.7) cannot draw the simulated slick
// without its polygon, which M6 already computes.

export * from './contracts.generated';
