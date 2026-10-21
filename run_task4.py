#!/usr/bin/env python3
"""Run a cache-hierarchy design-space sweep.

Usage:
    ./run_task4.py --pintool ./obj-intel64/memory-hierarchy.so \
        --benchmark-name gcc -- ./gcc-test

The current starter simulator only exposes L1 knobs. The L2 and replacement
arguments are still passed as metadata in the output CSV so this runner is
ready for the completed Task 4 simulator. Until those knobs are implemented,
use --l1-only to run configurations supported by the current code.
"""

import argparse
import csv
import itertools
import os
import subprocess
import sys
from collections import namedtuple
from pathlib import Path

TOTAL_CACHE_BUDGET = 5 * 1024 * 1024


CacheConfig = namedtuple(
    "CacheConfig", ["associativity", "block_size", "size", "replacement"]
)


def parse_sizes(value):
    return tuple(int(item) for item in value.split(","))


def parse_values(value):
    return tuple(item.strip() for item in value.split(",") if item.strip())


def configurations(args):
    l1_values = (
        CacheConfig(a, b, size * 1024, r)
        for a, b, size, r in itertools.product(
            args.l1_associativities,
            args.l1_block_sizes,
            args.l1_sizes,
            args.replacements,
        )
    )

    if args.l1_only:
        for l1 in l1_values:
            yield l1, None
        return

    l2_values = (
        CacheConfig(a, b, size * 1024, r)
        for a, b, size, r in itertools.product(
            args.l2_associativities,
            args.l2_block_sizes,
            args.l2_sizes,
            args.replacements,
        )
    )

    for l1, l2 in itertools.product(l1_values, l2_values):
        if l1.size + l2.size <= TOTAL_CACHE_BUDGET:
            yield l1, l2


def run_configuration(args, l1, l2, output_file):
    command = [
        args.pin,
        "-t",
        str(args.pintool),
        "-o",
        str(output_file),
        "-l1c",
        str(l1.size // 1024),
        "-l1b",
        str(l1.block_size),
        "-l1a",
        str(l1.associativity),
    ]

    if l2 is not None:
        command.extend(
            [
                "-l2c",
                str(l2.size // 1024),
                "-l2b",
                str(l2.block_size),
                "-l2a",
                str(l2.associativity),
                "-l1r",
                l1.replacement,
                "-l2r",
                l2.replacement,
            ]
        )

    command.extend(["--", *args.command])
    print("Running:", " ".join(command), flush=True)
    subprocess.run(command, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pin", default=os.environ.get("PIN", "pin"))
    parser.add_argument("--pintool", type=Path, required=True)
    parser.add_argument("--benchmark-name", required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("task4-results"))
    parser.add_argument("--l1-only", action="store_true")
    parser.add_argument("--l1-associativities", type=parse_sizes, default=(1, 2, 4))
    parser.add_argument("--l1-block-sizes", type=parse_sizes, default=(32, 64))
    parser.add_argument("--l1-sizes", type=parse_sizes, default=(2, 4, 8))
    parser.add_argument("--l2-associativities", type=parse_sizes, default=(4, 8))
    parser.add_argument("--l2-block-sizes", type=parse_sizes, default=(64, 128))
    parser.add_argument("--l2-sizes", type=parse_sizes, default=(256, 512, 1024))
    parser.add_argument(
        "--replacements",
        type=parse_values,
        default=("round-robin",),
        help="Comma-separated policies; use random,lru,plru after implementing them",
    )
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()

    if args.command[:1] == ["--"]:
        args.command = args.command[1:]
    if not args.command:
        parser.error("provide a benchmark command after --")
    if not args.pintool.is_file():
        parser.error("Pin tool not found: " + str(args.pintool))

    args.output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = args.output_dir / (args.benchmark_name + ".csv")
    rows = []

    for run_number, (l1, l2) in enumerate(configurations(args), start=1):
        label = (
            f"{args.benchmark_name}-run{run_number}"
            f"-l1_{l1.size // 1024}kb_{l1.block_size}b_{l1.associativity}way"
            f"-l2_{'none' if l2 is None else str(l2.size // 1024) + 'kb'}"
        )
        stats_path = args.output_dir / (label + ".stats")
        run_configuration(args, l1, l2, stats_path)
        rows.append(
            {
                "run": run_number,
                "benchmark": args.benchmark_name,
                "stats_file": str(stats_path),
                "l1_size_bytes": l1.size,
                "l1_block_size": l1.block_size,
                "l1_associativity": l1.associativity,
                "l1_replacement": l1.replacement,
                "l2_size_bytes": "" if l2 is None else l2.size,
                "l2_block_size": "" if l2 is None else l2.block_size,
                "l2_associativity": "" if l2 is None else l2.associativity,
                "l2_replacement": "" if l2 is None else l2.replacement,
                "total_cache_bytes": l1.size if l2 is None else l1.size + l2.size,
            }
        )

    if not rows:
        print("No configurations satisfy the 5 MB cache budget.", file=sys.stderr)
        return 1

    with csv_path.open("w", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} configuration records to {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
