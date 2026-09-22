# Measuring SkillKit's runtime cost

The 0.18.0 migration moved repeated work from 17 fleet skills into shared helpers.
All 23 skill suites were exercised with the candidate library. The local benchmark
measures hot paths and fresh-process imports/construction, without a running hub
or speaker. It does not measure network, ASR, TTS, or audio-device startup.

On Linux x86-64 with Python 3.13.14, four fresh processes per revision alternated
baseline/candidate order. Each warm path ran seven timed batches after warmup.
The table shows medians across process medians; the full samples and baseline
commits are in [performance-0.18.json](performance-0.18.json).

| Operation | Before | After | Interpretation |
|---|---:|---:|---|
| Choose three Fart sounds | 91.67 µs | 3.14 µs | About 29× faster; no repeated directory scan |
| Combine Timer regional resources | 1.404 µs | 0.170 µs | About 8× faster; immutable cached result |
| News preview, packaged catalog | 109.29 µs | 111.02 µs | +1.73 µs; overlapping process ranges |
| News OCP search | 95.37 µs | 96.94 µs | +1.57 µs; overlapping process ranges |
| News catalog lookup | 2.294 µs | 2.226 µs | Existing cache retained |
| Weather regional lookup | 0.073 µs | 0.073 µs | Existing outer cache retained |
| Import the five benchmark modules | 241.72 ms | 247.18 ms | +5.46 ms; overlapping process ranges |
| Construct News and Fart | 142.19 ms | 145.80 ms | +3.61 ms; overlapping process ranges |

The measurements show a large gain where repeated filesystem and locale work was
removed, and no material change in the measured News paths. They do not prove
zero overhead or predict timings on a Raspberry Pi. Startup is reported alongside
warm requests so a cache does not hide setup costs. There are no timing thresholds
in CI: contention would make them unreliable. Tests instead enforce no filesystem
scan on a warm asset hit, explicit reload, capacity bounds, isolated deadlines,
response limits and cancellation behavior.

## Reproduce

Prepare baseline and candidate roots, each containing checkouts named
`thalovant-skillkit`, `thalovant-skill-news`, `thalovant-skill-fart`,
`thalovant-skill-timer`, and `thalovant-skill-weather`. Install their dependencies
in one isolated environment. Use the same interpreter for both:

```bash
python scripts/benchmark-skills.py /path/to/baseline before.json
python scripts/benchmark-skills.py /path/to/candidate after.json
```

The script selects those source trees explicitly, isolates XDG state, disables
News warming and replaces its network opener with a failing local stub. Do not
run tests or builds at the same time. Repeat in alternating order. Compare the
same operation and resource set, rather than treating different locale or catalog
sizes as equivalent work.

See [the runtime helper contracts](reference.md#shared-runtime-plumbing) for cache
lifetimes and invalidation. No generic cache of personal or service replies was
introduced. Asset caches contain paths, not audio buffers.
