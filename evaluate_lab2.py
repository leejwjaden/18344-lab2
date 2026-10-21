#!/usr/bin/env python3
"""Evaluate Lab 2 Tasks 1, 2, and 4 for one benchmark command.

Example:
    ./evaluate_lab2.py --pintool ./obj-intel64/memory-hierarchy.so \
        --benchmark-name gcc --output-dir lab2-results/gcc -- ./gcc-test

The benchmark command after ``--`` is run once for every configuration.
The script writes task1.csv, task2.csv, task4.csv, and one simulator .stats
file per run.
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
    "CacheConfig", ["size_kb", "block_size", "associativity", "replacement"]
)


def comma_ints(value):
    return tuple(int(item) for item in value.split(","))


def comma_strings(value):
    return tuple(item.strip() for item in value.split(",") if item.strip())


def parse_stats(path):
    values = {}
    for line in path.read_text().splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        try:
            values[key.strip()] = float(value.strip())
        except ValueError:
            pass
    return values


def miss_rate(stats, prefix):
    accesses = stats.get(prefix + "accesses", 0)
    return stats.get(prefix + "misses", 0) / accesses if accesses else 0.0


def amat(stats, l1_access_cost, l2_access_cost, dram_cost):
    l1_misses = miss_rate(stats, "")
    l2_misses = miss_rate(stats, "l2_")
    return l1_access_cost + l1_misses * (
        l2_access_cost + l2_misses * dram_cost
    )


def run_pin(args, l1, output, l2=None):
    command = [
        args.pin,
        "-t",
        str(args.pintool),
        "-o",
        str(output),
        "-l1c",
        str(l1.size_kb),
        "-l1b",
        str(l1.block_size),
        "-l1a",
        str(l1.associativity),
        "-l1r",
        l1.replacement,
    ]
    if l2 is not None:
        command.extend(
            [
                "-l2c",
                str(l2.size_kb),
                "-l2b",
                str(l2.block_size),
                "-l2a",
                str(l2.associativity),
                "-l2r",
                l2.replacement,
            ]
        )
    command.extend(["--", *args.command])
    print("Running:", " ".join(command), flush=True)
    subprocess.run(command, check=True)


def record_run(args, task, number, l1, l2=None):
    suffix = (
        f"l1-{l1.size_kb}kb-{l1.block_size}b-{l1.associativity}way"
        f"-{l1.replacement}"
    )
    if l2 is not None:
        suffix += (
            f"-l2-{l2.size_kb}kb-{l2.block_size}b-{l2.associativity}way"
            f"-{l2.replacement}"
        )
    output = args.output_dir / f"{task}-{number:04d}-{suffix}.stats"
    run_pin(args, l1, output, l2)
    stats = parse_stats(output)
    row = {
        "run": number,
        "stats_file": str(output),
        "l1_size_kb": l1.size_kb,
        "l1_block_size": l1.block_size,
        "l1_associativity": l1.associativity,
        "l1_replacement": l1.replacement,
        "l2_size_kb": "" if l2 is None else l2.size_kb,
        "l2_block_size": "" if l2 is None else l2.block_size,
        "l2_associativity": "" if l2 is None else l2.associativity,
        "l2_replacement": "" if l2 is None else l2.replacement,
        "l1_accesses": int(stats.get("accesses", 0)),
        "l1_misses": int(stats.get("misses", 0)),
        "l1_miss_rate": miss_rate(stats, ""),
        "l2_accesses": int(stats.get("l2_accesses", 0)),
        "l2_misses": int(stats.get("l2_misses", 0)),
        "l2_miss_rate": miss_rate(stats, "l2_"),
        "dram_accesses": int(stats.get("dram_accesses", 0)),
        "amat": amat(
            stats, args.l1_access_cost, args.l2_access_cost, args.dram_cost
        ),
    }
    return row


def write_rows(path, rows):
    if not rows:
        return
    with path.open("w", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


def task1_configs(args):
    return (
        CacheConfig(size, block, assoc, "lru")
        for size, block, assoc in itertools.product(
            args.l1_sizes, args.l1_block_sizes, args.l1_associativities
        )
        if (size * 1024 // block) % assoc == 0
    )


def task2_configs(args):
    base = ((2, 64, 1), (4, 64, 2), (8, 64, 4))
    return (
        CacheConfig(size, block, assoc, policy)
        for size, block, assoc, policy in (
            (size, block, assoc, policy)
            for size, block, assoc in base
            for policy in args.replacements
        )
    )


def task4_configs(args):
    l1s = (
        CacheConfig(size, block, assoc, policy)
        for size, block, assoc, policy in itertools.product(
            args.l1_sizes,
            args.l1_block_sizes,
            args.l1_associativities,
            args.replacements,
        )
        if (size * 1024 // block) % assoc == 0
    )
    l2s = (
        CacheConfig(size, block, assoc, policy)
        for size, block, assoc, policy in itertools.product(
            args.l2_sizes,
            args.l2_block_sizes,
            args.l2_associativities,
            args.replacements,
        )
        if (size * 1024 // block) % assoc == 0
    )
    return (
        (l1, l2)
        for l1, l2 in itertools.product(l1s, l2s)
        if (l1.size_kb + l2.size_kb) * 1024 <= TOTAL_CACHE_BUDGET
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pin", default=os.environ.get("PIN", "pin"))
    parser.add_argument("--pintool", type=Path, required=True)
    parser.add_argument("--benchmark-name", required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("lab2-results"))
    parser.add_argument("--l1-sizes", type=comma_ints, default=(2, 4, 8))
    parser.add_argument("--l1-block-sizes", type=comma_ints, default=(32, 64))
    parser.add_argument("--l1-associativities", type=comma_ints, default=(1, 2, 4))
    parser.add_argument("--l2-sizes", type=comma_ints, default=(256, 512, 1024))
    parser.add_argument("--l2-block-sizes", type=comma_ints, default=(64, 128))
    parser.add_argument("--l2-associativities", type=comma_ints, default=(4, 8))
    parser.add_argument(
        "--replacements",
        type=comma_strings,
        default=("random", "lru", "plru"),
    )
    parser.add_argument("--l1-access-cost", type=float, default=1.0)
    parser.add_argument("--l2-access-cost", type=float, default=10.0)
    parser.add_argument("--dram-cost", type=float, default=190.0)
    parser.add_argument(
        "--tasks",
        type=comma_strings,
        default=("task1", "task2", "task4"),
        help="Comma-separated subset of task1,task2,task4",
    )
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()

    if args.command[:1] == ["--"]:
        args.command = args.command[1:]
    if not args.command:
        parser.error("provide the benchmark command after --")
    if not args.pintool.is_file():
        parser.error("Pin tool not found: " + str(args.pintool))
    invalid_tasks = set(args.tasks) - {"task1", "task2", "task4"}
    if invalid_tasks:
        parser.error("unknown tasks: " + ", ".join(sorted(invalid_tasks)))

    args.output_dir.mkdir(parents=True, exist_ok=True)
    for task in args.tasks:
        rows = []
        configurations = task2_configs(args) if task == "task2" else task1_configs(args)
        if task == "task4":
            configurations = task4_configs(args)
        for number, configuration in enumerate(configurations, start=1):
            if task == "task4":
                l1, l2 = configuration
            else:
                l1, l2 = configuration, None
            rows.append(record_run(args, task, number, l1, l2))
        write_rows(args.output_dir / f"{task}.csv", rows)
        print(f"Wrote {len(rows)} rows to {args.output_dir / (task + '.csv')}")


if __name__ == "__main__":
    raise SystemExit(main())
