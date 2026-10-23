# Lab 2: automatic data collection

Copy **this whole project**, including `tests/` and the updated C++ files, to the
Linux ECE machine. In the same course environment you used for previous Pin/SPEC
runs, run:

```bash
cd /path/to/18344-lab2
python3 script.py
```

Python 3.6+ is supported. No pip packages, plotting packages, or root access are
required. `g++`, `make`, the Pin SDK, and licensed SPEC2017 executables/input files
must be available. If Destiny is missing, the runner clones the authors' public
mirror into `lab2-output/tools/` and builds it with `make` (requires git/network).
It does not install or modify system software.

For a long SSH run, use a persistent terminal such as tmux, or:

```bash
nohup python3 -u script.py > collection.log 2>&1 &
tail -f collection.log
```

The default sequential staged search runs roughly 140 configurations for each
benchmark, times the number of inputs in its SPEC command file. Runtime depends
on the workloads and machine. It runs entire **test-size** workloads by default,
without sampling or an instruction limit. It uses private per-job input copies;
allow disk space for these as well as raw logs. Keep the source SPEC run folders
unchanged during collection. Do not launch multiple collectors in the same
output directory.

## What gets collected

1. Build and run deterministic cache tests, then force a fresh Linux Pin build.
2. Task 1: 18 LRU configurations (2/4/8 KB, 32/64 B, 1/2/4 ways), both benchmarks.
3. Task 2: random, LRU, **bit-PLRU**, and round-robin on three cache configurations.
4. Tasks 3/4: search L1 geometry, then L2 geometry, then all 16 independent
   policy pairs on four promising geometry pairs. Enforce the 5 MiB data budget.
5. Collect Destiny cache hit/miss/write latency, energy, area, tag area, leakage.
6. Compute AMAT using the handout formula and **9.5 ns** DRAM latency.
7. Select the lowest mean gcc/leela AMAT, breaking exact ties by area then power;
   compute a three-objective Pareto set (AMAT, area, estimated total power).
8. Run controlled L2 size and associativity sensitivity experiments.
9. Generate CSV tables, SVG plots, a recommendation, and an HTML analysis draft.

The search is a bounded staged search, **not an exhaustive global optimization**.
Every selected input command for both `602.gcc_s` and `641.leela_s` runs for each
design. Within a benchmark, counters are summed across commands before computing
miss rates; design ranking gives each benchmark equal weight.

## Output and resume

`lab2-output/LATEST.txt` points to the result session. That directory contains:

```text
session-.../
  part1/     # Single-cache measurements, hardware table, run index
    plots/   # AMAT versus associativity and block size, for gcc and leela
  part2/     # Replacement-policy measurements, hardware table, run index
    plots/   # Policy miss-rate comparisons, for gcc and leela
  part4/     # Two-level search, Pareto results, recommendation
    plots/   # Pareto frontiers, per-benchmark AMAT bars, L2 sensitivity plots
  runs/      # Shared raw runs used by the per-part run indexes and resume
  destiny/   # Shared raw hardware-model configurations and output
  report.html
```

Each part has its own `measurements.csv`, `hardware.csv`, and `runs.csv`.
The runner automatically generates the figures in each part's `plots/` folder
after collection completes; no separate plotting command or package is needed.
Measurement tables are updated as configurations finish. Paths in `runs.csv` are
relative to that part's folder and point to the shared raw statistics and logs.
A configuration used in both Parts 1 and 2 appears in both tables without rerunning
the benchmark. Part 3's two-level implementation is exercised by the Part 4 runs.

| File/directory | Contents |
| --- | --- |
| `manifest.json` | Tool/source hashes, settings, exact inputs and commands, environment |
| `runs/` | Per-input commands, simulator statistics, program logs, completion markers |
| `destiny/` | Exact SRAM configs, cell files, raw Destiny output, parsed metrics |
| `measurements.csv` | All per-benchmark measurements and derived values |
| `hardware.csv` | Latency, energy, area, leakage, tag area for each geometry |
| `part4/design_space.csv`, `part4/pareto.csv` | Aggregate design comparison and Pareto set |
| `part4/recommended.json` | Best measured hierarchy |
| `part4/sensitivity_anchor.json` | Fixed configuration used for sensitivity experiments |
| `part1/plots/*.svg`, `part2/plots/*.svg`, `part4/plots/*.svg` | Each part's plots |
| `report.html` | Analysis draft with figures, observations, and assumptions |
| `COMPLETE.json` | Written only after all collection and reporting succeeds |

Rerun `python3 script.py` after interruption. Completed valid runs are reused.
Changed sources/tools/inputs/settings generate a separate session. Old results
are preserved, including the original `results/task1-3/` folder, whose tree-PLRU
and single-level AMAT data should not be used as the corrected final results.

## Environment discovery

The repository's original files do not specify absolute ECE SPEC/Destiny paths.
The checked-in binary does identify the course Pin installation at
`/afs/ece.cmu.edu/class/ece344/opt/pin/inst`, which is a built-in discovery candidate.
Discovery uses PATH; `PIN`, `PIN_ROOT`, `SPEC`, `SPEC_ROOT`, `DESTINY`,
`DESTINY_ROOT`, and `DESTINY_CELL`; `ECE344_HOME`; the course's
`/scratch/ece344-<current-user>` directory; and current course tool installations.
It reads `output_root` from your selected personal SPEC configuration and searches
there too. It does not search old course semesters or unrelated `/opt` and
`/usr/local` trees. The newest usable **base/test SPECspeed** run directory is selected
and its identity is recorded. Existing Pin-wrapped benchmark commands are rejected
to avoid instrumenting the wrapper instead of the benchmark.

Discovery follows installation symlinks with cycle protection and revisits
overlapping search roots when doing so can reach deeper run directories.
If it cannot find the requested workload, inspect the setup without building or
running anything:

```bash
python3 script.py --diagnose
```

This lists gcc/leela command files (including other input sizes or the rate suite),
parser errors, and search problems. Full paths and the relevant environment are
saved to `lab2-output/discovery-diagnostics.json`, including when normal discovery
fails. A missing match can mean the run directory is absent, inaccessible, outside
the search, or prepared for a different input size. It does not mean that no
previous experiment data exists. `spec_root` in `lab2_config.json` can identify a
SPEC installation directly; `search_roots` can identify a separate SPEC output tree.

SPEC configuration selection checks `spec_config` in the JSON override, then
`SPEC_CONFIG`, then the course's **`ECE344_SPEC_CONFIG`** environment variable.
Otherwise it looks for a unique personal `18344-*-<current-user>.cfg` in the course
home, nearby directories, or the installed SPEC config directory. Multiple matches
are listed rather than guessed.

If SPEC has not been prepared, the script automatically calls `runcpu --action=runsetup`
with that configuration for gcc and leela. This sources the installation's `shrc`
in a child shell and disables the course's submit wrapper for SPECspeed. Setup
output goes to `/scratch/ece344-<current-user>` (override with `spec_output_root`),
and the runner searches that exact output location afterward. Neither the shared
course config nor your shell files are edited. Setup may build missing executables.
It cannot obtain licensed SPEC software or guess a compiler configuration.
If the environment is unavailable it stops with an actionable error;
it never substitutes synthetic benchmark data or invented Destiny costs.

Optional overrides go in `lab2_config.json`; they are read automatically on the
same `python3 script.py` command. **Do not copy these illustrative paths literally.**

```json
{
  "pin": "/path/to/pin/pin",
  "pin_root": "/path/to/pin",
  "destiny": "/path/to/destiny/destiny",
  "destiny_cell": "/path/to/destiny/config/sample_SRAM.cell",
  "benchmarks": {
    "gcc": "/path/to/602.gcc_s/run/run_base_test_config.0000/speccmds.cmd",
    "leela": "/path/to/641.leela_s/run/run_base_test_config.0000/speccmds.cmd"
  },
  "input_size": "test",
  "process_nm": 65,
  "accesses_per_second": 1000000000,
  "timeout_seconds": 0
}
```

All fields are optional. `search_roots` accepts additional directory paths;
`spec_config` selects a SPEC config for runsetup; `output_dir` changes the result
location. `input_size` may be `test`, `train`, or `ref` (use corresponding run
directories when explicitly specifying benchmark paths). `l1_sizes_kb` and
`l2_sizes_kb` customize the search capacity lists. `timeout_seconds: 0` means
unlimited. `python3 script.py --check` performs discovery (and may build/download
Destiny) without running the experiments.

## Modeling and interpretation

The cache is a demand-only, cold-start, data-cache model. Loads/stores both allocate;
L1 misses fetch through L2. L2 blocks must be at least as large as L1 blocks and
an integer multiple. There is no enforced inclusion/exclusion policy. Dirty
writebacks, coherence, instruction-cache traffic, prefetching, and parallel memory
requests are not modeled. This is sufficient to explore demand misses; it is not
a cycle-accurate processor or full write-policy implementation.

Destiny is configured for 2D SRAM, 65 nm, LOP, 350 K, normal access, and read-latency
optimization. AMAT uses separate Destiny hit/miss latencies, not the old script's
fixed 1/10/190 costs. Write latency/energy are collected separately. Estimated
cache dynamic energy includes demand lookup/write and fill-write energy; it excludes
dirty writebacks, DRAM energy, and replacement logic. Dynamic power uses an explicit
fixed offered access rate (1 billion accesses/s by default), **not Pin wall time**.
This is an analytical comparison, not measured processor power. Vary the rate if
your writeup uses another workload throughput assumption.

The budget counts data bytes. Metadata bytes are reported separately for a 64-bit
address model; Destiny's modeled tag area is also reported. Controller cost is not
included in Destiny estimates, so implementation arguments must acknowledge that.

The script attempts to disable ASLR using `setarch -R`; if the machine disallows
this, the report flags address-layout noise. Random replacement uses a fixed seed.
Benchmark success requires a zero exit code and consistent, nonzero statistics;
the script does **not** perform SPEC's reference-output comparison or certify SPEC
scores. Review results and the implementability discussion, then incorporate the
plots/tables in your final PDF. The generated HTML can be printed to PDF in a
browser, but still needs your review and final conclusions.

## Verification

```bash
python3 -m unittest discover -s tests -v
g++ -std=c++11 -Wall -Wextra -pedantic -I. cache.cpp tests/cache_test.cpp -o cache_test
./cache_test
```

The Python tests use explicit mock external-tool output, never real lab results.
The collector runs the C++ tests on the ECE machine before experiments.

Tool format references:
- [Destiny author mirror](https://github.com/sparsh0mittal/destiny_3d_cache)
- [SPEC2017 utilities](https://www.spec.org/cpu2017/Docs/utility.html)
- [Course setup: ECE344_SPEC_CONFIG and scratch output](https://course.ece.cmu.edu/~ece344/course_documents/18344-f25-recitation0.pdf)
