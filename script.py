#!/usr/bin/env python3
"""Collect Lab 2 experiments on Linux: python3 script.py (Python >= 3.6).

Standard library only. See README.md for discovery, model assumptions, and
optional lab2_config.json overrides. Existing results are never overwritten.
"""
import argparse
import csv
import hashlib
import html
import itertools
import json
import math
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import subprocess
import sys
import time
from collections import namedtuple

ROOT = Path(__file__).resolve().parent
Cache = namedtuple('Cache', 'kb block ways policy')
POLICIES = ('random', 'lru', 'plru', 'round-robin')
BUDGET = 5 * 1024 * 1024
DRAM_NS = 9.5
VERSION = 1


def log(message):
    print(time.strftime('[%H:%M:%S] ') + str(message), flush=True)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()[:20]


def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
    temp.replace(path)


def run(command, cwd, logfile, stdin=None, env=None, timeout=None):
    """No shell interpretation. Keep logs and terminate children on interruption."""
    logfile = Path(logfile)
    logfile.parent.mkdir(parents=True, exist_ok=True)
    with logfile.open('wb') as out:
        inp = open(str(stdin), 'rb') if stdin else open(os.devnull, 'rb')
        try:
            process = subprocess.Popen([str(x) for x in command], cwd=str(cwd),
                                       stdin=inp, stdout=out, stderr=subprocess.STDOUT,
                                       env=env, start_new_session=(os.name == 'posix'))
            try:
                code = process.wait(timeout=timeout)
            except BaseException:
                if os.name == 'posix':
                    import signal
                    os.killpg(process.pid, signal.SIGTERM)
                else:
                    process.terminate()
                process.wait()
                raise
        finally:
            inp.close()
    if code:
        raise RuntimeError('Command failed (exit {}): {}\nSee {}'.format(
            code, ' '.join(map(str, command)), logfile))


def walk_find(roots, names, max_depth=7, limit=5000, issues=None):
    """Bounded discovery; never walk all of AFS or the whole filesystem."""
    found, visited, seen_files = [], {}, set()
    issues = issues if issues is not None else []
    for root in roots:
        count = 0
        root = Path(root).expanduser()
        if not root.is_dir():
            continue
        def onerror(error):
            issues.append(str(error))
        for directory, dirs, files in os.walk(str(root), followlinks=True, onerror=onerror):
            p = Path(directory)
            depth = len(p.relative_to(root).parts)
            remaining = max_depth - depth
            try:
                resolved = str(p.resolve())
            except (OSError, RuntimeError) as error:
                issues.append(str(error))
                dirs[:] = []
                continue
            # A broad earlier root may have hit its depth limit here. A later,
            # more specific root must be allowed to search farther below it.
            # The remaining-depth comparison also breaks symbolic-link cycles.
            if visited.get(resolved, -1) >= remaining or resolved in (
                    '/', '/afs', '/home', '/proc', '/sys', '/dev'):
                dirs[:] = []
                continue
            visited[resolved] = remaining
            count += 1
            if count > limit:
                issues.append('Directory limit ({}) reached under {}'.format(limit, root))
                break
            dirs[:] = sorted(d for d in dirs if not d.startswith('.') and d not in (
                'node_modules', '__pycache__', 'src', 'data', 'Docs', 'doc',
                'build', 'result', 'results', 'lab2-output')) if depth < max_depth else []
            for name in names:
                if name in files and (resolved, name) not in seen_files:
                    found.append(p / name)
                    seen_files.add((resolved, name))
    return found


def discovery_roots(settings):
    roots = [ROOT, ROOT.parent, Path.home() / 'Private' / '18344',
             Path.home() / '18344', Path.home() / 'Private', Path.home()]
    roots += [Path(x) for x in settings.get('search_roots', [])]
    for key in ('SPEC', 'SPEC_ROOT', 'PIN_ROOT', 'DESTINY_ROOT'):
        if os.environ.get(key):
            roots.insert(0, Path(os.environ[key]))
    if settings.get('spec_root'):
        roots.insert(0, Path(settings['spec_root']))
    for name in ('pin', 'runcpu', 'destiny'):
        exe = shutil.which(name)
        if exe:
            roots.extend([Path(exe).resolve().parent, Path(exe).resolve().parent.parent])
    # The checked-in .so embeds this course Pin installation path. Include
    # installation symlinks as explicit roots (os.walk does not follow them).
    course_roots = [Path('/afs/ece.cmu.edu/class/ece344'), Path('/afs/ece/class/ece344')]
    for course in course_roots:
        opt = course / 'opt'
        if opt.is_dir():
            roots.extend(p / 'inst' for p in opt.iterdir() if (p / 'inst').is_dir())
        roots.append(course)
    roots.extend([Path('/opt'), Path('/usr/local')])
    return list(dict.fromkeys(str(p) for p in roots))


def discover_files(settings, out):
    roots = discovery_roots(settings)
    issues = []
    names = ('pin', 'destiny', 'sample_SRAM.cell', 'speccmds.cmd', 'runcpu', 'shrc')
    found = walk_find(roots, names, issues=issues)
    # Search installations directly as well as from their ancestor directories.
    installations = [p.parent.parent for p in found if p.name == 'runcpu']
    installations += [p.parent for p in found if p.name == 'shrc']
    specific = [str(p / 'benchspec/CPU') for p in installations if (p / 'benchspec/CPU').is_dir()]
    if specific:
        found += walk_find(specific, ('speccmds.cmd',), issues=issues)
        roots += specific
    found = list(dict.fromkeys(found))
    size = settings.get('input_size', 'test')
    workloads = []
    for p in found:
        if p.name != 'speccmds.cmd' or not re.search(r'(gcc|leela)', str(p), re.I):
            continue
        expected = any(n in str(p) for n in ('602.gcc_s', '641.leela_s'))
        entry = {'path': str(p), 'requested_speed_and_size': expected and 'run_base_' + size in str(p)}
        try:
            entry['commands'] = len(parse_speccmds(p))
        except (RuntimeError, ValueError, OSError) as error:
            entry['error'] = str(error)
        workloads.append(entry)
    report = {'searched_roots': roots, 'requested_input_size': size,
              'environment': {k: os.environ.get(k, '') for k in ('SPEC', 'SPEC_ROOT', 'SPEC_CONFIG', 'PIN_ROOT')},
              'tools': {name: [str(p) for p in found if p.name == name] for name in names if name != 'speccmds.cmd'},
              'workload_candidates': workloads, 'search_issues': issues}
    save_json(out / 'discovery-diagnostics.json', report)
    return roots, found, report


def print_discovery(report, out):
    log('Requested workloads: 602.gcc_s and 641.leela_s, base/' + report['requested_input_size'])
    for name in ('runcpu', 'shrc'):
        log('{}: {}'.format(name, ', '.join(report['tools'][name]) or 'not found'))
    if not report['workload_candidates']:
        log('No gcc/leela speccmds.cmd files found in the searched directories.')
    for entry in report['workload_candidates']:
        reason = entry.get('error') or ('matches requested input' if entry['requested_speed_and_size']
                                       else 'different input size or SPEC suite')
        log('{}: {}'.format(entry['path'], reason))
    for issue in report['search_issues'][:10]:
        log('Search issue: ' + issue)
    log('Full search details: ' + str(out / 'discovery-diagnostics.json'))


def parse_speccmds(path):
    """Parse SPEC's command file, including per-command cwd and input redirects."""
    path = Path(path).resolve()
    current = path.parent
    commands = []
    for line in path.read_text().splitlines():
        tokens = shlex.split(line, comments=True)
        if not tokens:
            continue
        opts = {}
        while tokens and tokens[0].startswith('-'):
            flag = tokens.pop(0)
            if flag not in ('-c', '-o', '-e', '-i', '-C') or not tokens:
                raise RuntimeError('Unsupported SPEC command option {} in {}'.format(flag, path))
            opts[flag] = tokens.pop(0)
        if '-c' in opts:
            candidate = Path(opts['-c'])
            current = candidate if candidate.is_absolute() else path.parent / candidate
        if not tokens:
            continue
        if any(t in ('>', '<', '2>', '|', ';', '&&') for t in tokens):
            raise RuntimeError('Shell-wrapped SPEC command in {}; use an uninstrumented runsetup'.format(path))
        exe = Path(tokens[0])
        exe = exe if exe.is_absolute() else current / exe
        if not exe.is_file():
            raise RuntimeError('Benchmark executable missing: ' + str(exe))
        if not re.search(r'(gcc|leela)', exe.name, re.I):
            raise RuntimeError('Expected a direct gcc/leela executable, found ' + str(exe))
        commands.append({'argv': [str(exe.resolve())] + tokens[1:],
                         'cwd': str(current.resolve()), 'stdin': opts.get('-i'),
                         'source': str(path)})
    if not commands:
        raise RuntimeError('No benchmark commands in ' + str(path))
    return commands


def discover(settings, out):
    log('Discovering Pin, SPEC run directories, and Destiny...')
    roots, found, diagnostics = discover_files(settings, out)
    def executable(key, envkey):
        value = settings.get(key) or os.environ.get(envkey) or shutil.which(key)
        if not value and key == 'pin':
            course_pin = Path('/afs/ece.cmu.edu/class/ece344/opt/pin/inst/pin')
            if course_pin.is_file():
                value = str(course_pin)
        if not value and key == 'pin' and os.environ.get('PIN_ROOT'):
            value = str(Path(os.environ['PIN_ROOT']) / 'pin')
        if not value and key == 'destiny' and os.environ.get('DESTINY_ROOT'):
            candidate = Path(os.environ['DESTINY_ROOT']) / 'destiny'
            if candidate.is_file():
                value = str(candidate)
        matches = [p for p in found if p.name == key and os.access(str(p), os.X_OK)]
        return Path(value).expanduser().resolve() if value else (matches[0].resolve() if matches else None)
    pin = executable('pin', 'PIN')
    if not pin or not pin.is_file():
        raise RuntimeError('Pin not found. Load the course environment, or set PIN_ROOT/PIN. '
                           'Discovery searched: ' + ', '.join(roots))
    pin_root = Path(settings.get('pin_root') or os.environ.get('PIN_ROOT') or pin.parent)
    if not (pin_root / 'source/tools/Config/makefile.config').is_file():
        raise RuntimeError('Cannot locate the Pin SDK. Set PIN_ROOT to its directory (not the pin binary).')
    size = settings.get('input_size', 'test')
    if size not in ('test', 'train', 'ref'):
        raise ValueError('input_size must be test, train, or ref')
    benchmarks = {}
    for name, number in (('gcc', '602'), ('leela', '641')):
        explicit = settings.get('benchmarks', {}).get(name)
        if explicit:
            if 'run_base_' + size not in str(explicit) or number + '.' + name + '_s' not in str(explicit):
                raise ValueError('Benchmark override must identify the {} {} SPECspeed run directory: {}'.format(name, size, explicit))
            benchmarks[name] = parse_speccmds(explicit)
            continue
        candidates = [p for p in found if p.name == 'speccmds.cmd'
                      and (number + '.' + name + '_s') in str(p)
                      and ('run_base_' + size) in str(p)]
        # Prefer the most recently prepared base run; record the exact choice.
        candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        errors = []
        for candidate in candidates:
            try:
                benchmarks[name] = parse_speccmds(candidate)
                break
            except RuntimeError as error:
                errors.append(str(error))
        if name not in benchmarks:
            runcpu = executable('runcpu', 'RUNCPU')
            config = settings.get('spec_config') or os.environ.get('SPEC_CONFIG')
            if runcpu and config:
                run([runcpu, '--config=' + config, '--action=runsetup', '--size=' + size,
                     '--tune=base', '--iterations=1', '--threads=1', number + '.' + name + '_s'],
                    ROOT, out / ('setup-' + name + '.log'))
                more = walk_find(roots, ('speccmds.cmd',))
                candidates = sorted([p for p in more if number + '.' + name + '_s' in str(p)
                                     and 'run_base_' + size in str(p)],
                                    key=lambda p: p.stat().st_mtime, reverse=True)
                if candidates:
                    benchmarks[name] = parse_speccmds(candidates[0])
            if name not in benchmarks:
                print_discovery(diagnostics, out)
                raise RuntimeError('No usable {} SPECspeed {} run directory. Run the course SPEC '
                                   'runsetup for 602.gcc_s and 641.leela_s, or set SPEC_CONFIG '
                                   'and load SPEC first. You can point benchmarks.{} in lab2_config.json '
                                   'at speccmds.cmd. Discovery details are saved in {}. {}'.format(
                                       name, size, name, out / 'discovery-diagnostics.json', '; '.join(errors)))
    destiny = executable('destiny', 'DESTINY')
    cells = [p for p in found if p.name == 'sample_SRAM.cell']
    cell = settings.get('destiny_cell') or os.environ.get('DESTINY_CELL')
    if not destiny:
        location = out / 'tools/destiny'
        if not (location / 'Makefile').exists() and not (location / 'makefile').exists():
            log('Destiny not installed; downloading the authors\' public mirror locally.')
            run(['git', 'clone', '--depth', '1',
                 'https://github.com/sparsh0mittal/destiny_3d_cache.git', location],
                ROOT, out / 'destiny-download.log')
        run(['make', '-j2'], location, out / 'destiny-build.log')
        destiny = location / 'destiny'
        cells.insert(0, location / 'config/sample_SRAM.cell')
    if not cell:
        nearby = [destiny.parent / 'config/sample_SRAM.cell', destiny.parent / 'sample_SRAM.cell']
        cell = next((p for p in nearby + cells if p.is_file()), None)
    if not cell or not Path(cell).is_file():
        raise RuntimeError('Destiny SRAM cell file missing. Set DESTINY_CELL or destiny_cell in lab2_config.json.')
    return {'pin': str(pin), 'pin_root': str(pin_root.resolve()),
            'destiny': str(destiny.resolve()), 'cell': str(Path(cell).resolve()),
            'benchmarks': benchmarks, 'input_size': size}


def parse_stats(path, two_level):
    stats = {}
    for line in Path(path).read_text().splitlines():
        if ':' in line:
            key, value = line.split(':', 1)
            if key.strip().endswith('miss_rate'):
                continue
            stats[key.strip()] = int(value.strip())
    for prefix in ('', 'l2_') if two_level else ('',):
        required = ('accesses', 'hits', 'misses', 'reads', 'writes', 'read_hits', 'write_hits')
        if any(prefix + k not in stats for k in required):
            raise ValueError('Missing counters in ' + str(path))
        s = {k: stats[prefix + k] for k in required}
        if (min(s.values()) < 0 or s['hits'] + s['misses'] != s['accesses']
                or s['reads'] + s['writes'] != s['accesses']
                or s['read_hits'] > s['reads'] or s['write_hits'] > s['writes']
                or s['read_hits'] + s['write_hits'] != s['hits']):
            raise ValueError('Inconsistent counters in ' + str(path))
    if stats['accesses'] <= 0:
        raise ValueError('Benchmark generated no accesses: ' + str(path))
    if two_level and stats['l2_accesses'] != stats['misses']:
        raise ValueError('L2 accesses do not equal L1 misses: ' + str(path))
    if stats.get('dram_accesses') != stats['l2_misses' if two_level else 'misses']:
        raise ValueError('Incorrect DRAM accounting: ' + str(path))
    return stats


def destiny_config(cache, node):
    return '\n'.join([
        '-DesignTarget: cache', '-CacheAccessMode: Normal',
        '-Associativity (for cache only): ' + str(cache.ways),
        '-ProcessNode: ' + str(node), '-Capacity (KB): ' + str(cache.kb),
        '-WordWidth (bit): ' + str(cache.block * 8), '-DeviceRoadmap: LOP',
        '-LocalWireType: LocalAggressive', '-LocalWireRepeaterType: RepeatedNone',
        '-LocalWireUseLowSwing: No', '-GlobalWireType: GlobalAggressive',
        '-GlobalWireRepeaterType: RepeatedNone', '-GlobalWireUseLowSwing: No',
        '-Routing: H-tree', '-InternalSensing: true',
        '-MemoryCellInputFile: sram.cell', '-Temperature (K): 350',
        '-OptimizationTarget: ReadLatency', '-EnablePruning: Yes',
        '-BufferDesignOptimization: latency', '-StackedDieCount: 1',
        '-PrintLevel: 1', ''])


def parse_destiny(text):
    # Parse the cache summary, not subarrays or intermediate optimization results.
    if 'CACHE DESIGN -- SUMMARY' not in text:
        raise ValueError('Destiny produced no valid cache summary')
    section = text.split('CACHE DESIGN -- SUMMARY')[-1].split('CACHE DATA ARRAY DETAILS')[0]
    fields = {
        'area_mm2': ('Total Area', 'mm^2'),
        'tag_area_mm2': ('Tag Array Area', 'mm^2'),
        'hit_ns': ('Cache Hit Latency', 'ns'),
        'miss_ns': ('Cache Miss Latency', 'ns'),
        'write_ns': ('Cache Write Latency', 'ns'),
        'hit_nj': ('Cache Hit Dynamic Energy', 'nJ'),
        'miss_nj': ('Cache Miss Dynamic Energy', 'nJ'),
        'write_nj': ('Cache Write Dynamic Energy', 'nJ'),
        'leakage_mw': ('Cache Total Leakage Power', 'mW')}
    result = {}
    number = r'([0-9]+(?:\.[0-9]*)?(?:[eE][+-]?[0-9]+)?)'
    for key, (label, unit) in fields.items():
        line = next((line for line in section.splitlines() if label + ' ' in line or label + '=' in line), '')
        # Tag-area line contains dimensions followed by area; take the area unit.
        match = re.search(number + r'\s*' + re.escape(unit), line)
        if not match:
            raise ValueError('Missing Destiny field: ' + label)
        result[key] = float(match.group(1))
        if not math.isfinite(result[key]) or result[key] <= 0:
            raise ValueError('Invalid Destiny field: ' + label)
    return result


def amat(stats, h1, h2=None):
    m1 = stats['misses'] / stats['accesses']
    lower = DRAM_NS
    if h2 is not None:
        m2 = stats['l2_misses'] / stats['l2_accesses'] if stats['l2_accesses'] else 0.0
        lower = (1 - m2) * h2['hit_ns'] + m2 * (h2['miss_ns'] + DRAM_NS)
    return (1 - m1) * h1['hit_ns'] + m1 * (h1['miss_ns'] + lower)


def overhead(cache):
    # Analytical 64-bit address tag + valid bit + replacement storage (no dirty bit).
    lines = cache.kb * 1024 // cache.block
    sets = lines // cache.ways
    tag_bits = 64 - int(math.log2(cache.block)) - int(math.log2(sets))
    replacement = {'lru': cache.ways * int(math.log2(cache.ways)),
                   'plru': cache.ways, 'random': 0,
                   'round-robin': int(math.log2(cache.ways))}[cache.policy]
    return (lines * (tag_bits + 1) + sets * replacement + 7) // 8


def label(cache):
    return '{}K-{}B-{}way-{}'.format(*cache)


def valid_pair(l1, l2):
    return l2 is None or ((l1.kb + l2.kb) * 1024 <= BUDGET
                         and l2.block >= l1.block and l2.block % l1.block == 0)


def write_csv(path, rows):
    if not rows:
        return
    fields = list(dict.fromkeys(k for row in rows for k in row))
    with Path(path).open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


class Experiment:
    def __init__(self, settings, tools, out):
        self.settings, self.tools, self.out = settings, tools, out
        self.env = dict(os.environ, OMP_NUM_THREADS='1', LC_ALL='C')
        self.timeout = settings.get('timeout_seconds', 0) or None
        self.hardware_cache, self.rows, self.scores = {}, [], {}
        self.pintool = ROOT / 'obj-intel64/memory-hierarchy.so'
        self.aslr = []
        setarch = shutil.which('setarch')
        if setarch:
            probe = subprocess.call([setarch, platform.machine(), '-R', 'true'],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if probe == 0:
                self.aslr = [setarch, platform.machine(), '-R']
        if not self.aslr:
            log('NOTE: ASLR cannot be disabled; address-layout noise will be disclosed in the report.')
        self.manifest = {'version': VERSION, 'settings': settings, 'tools': tools,
                         'source_sha256': {p: file_hash(ROOT / p) for p in
                                           ('cache.h', 'cache.cpp', 'memory-hierarchy.cpp', 'script.py')},
                         'tool_sha256': {p: file_hash(tools[p]) for p in ('pin', 'destiny', 'cell')},
                         'aslr_disabled': bool(self.aslr), 'machine': platform.platform(),
                         'environment': {k: self.env.get(k, '') for k in
                                         ('OMP_NUM_THREADS', 'LC_ALL', 'LD_LIBRARY_PATH', 'PATH')}}
        self.session = None

    def prepare(self):
        log('Compiling and testing the cache model, then rebuilding the Pin tool...')
        compiler = shlex.split(os.environ.get('CXX', 'g++'))
        run(compiler + ['-std=c++11', '-Wall', '-Wextra', '-pedantic', '-I' + str(ROOT),
                        ROOT / 'cache.cpp', ROOT / 'tests/cache_test.cpp',
                        '-o', self.out / 'cache_test'], ROOT, self.out / 'cache-test-build.log')
        run([self.out / 'cache_test'], ROOT, self.out / 'cache-test.log')
        run(['make', '-B', 'PIN_ROOT=' + self.tools['pin_root'],
             'obj-intel64/memory-hierarchy.so'], ROOT, self.out / 'pin-build.log')
        # Linker build IDs/timestamps may change on an otherwise identical rebuild.
        # Source hashes identify resume compatibility; retain the binary hash as
        # execution provenance without making it part of the session identity.
        binary_sha = file_hash(self.pintool)
        # Copy benchmark inputs into private sandboxes. Keep sibling run paths
        # out of argv: the executable has already been resolved to an absolute path.
        workloads = {}
        for name, commands in self.tools['benchmarks'].items():
            workloads[name] = []
            for index, command in enumerate(commands):
                src = Path(command['cwd'])
                identity = []
                for p in sorted(src.rglob('*')):
                    if p.is_file():
                        identity.append((str(p.relative_to(src)), file_hash(p)))
                workloads[name].append({'command': command, 'files': identity,
                                        'executable_sha256': file_hash(command['argv'][0])})
        self.manifest['workloads'] = workloads
        self.session = self.out / ('session-' + digest(self.manifest))
        self.session.mkdir(parents=True, exist_ok=True)
        self.manifest['pintool_sha256'] = binary_sha
        save_json(self.session / 'manifest.json', self.manifest)
        (self.out / 'LATEST.txt').write_text(str(self.session) + '\n')
        log('Results: ' + str(self.session))

    def hardware(self, cache):
        key = (cache.kb, cache.block, cache.ways)
        if key in self.hardware_cache:
            return self.hardware_cache[key]
        folder = self.session / 'destiny' / ('{}K-{}B-{}way'.format(*key))
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / 'metrics.json'
        if target.exists():
            metrics = json.loads(target.read_text())
        else:
            shutil.copyfile(self.tools['cell'], str(folder / 'sram.cell'))
            (folder / 'cache.cfg').write_text(destiny_config(cache, self.settings.get('process_nm', 65)))
            log('Destiny: ' + folder.name)
            run([self.tools['destiny'], 'cache.cfg'], folder, folder / 'destiny.log',
                env=self.env, timeout=self.timeout)
            try:
                metrics = parse_destiny((folder / 'destiny.log').read_text(errors='replace'))
            except ValueError as error:
                raise RuntimeError('{}; inspect {}'.format(error, folder / 'destiny.log'))
            save_json(target, metrics)
        self.hardware_cache[key] = metrics
        return metrics

    def collect(self, name, l1, l2):
        totals = {}
        for index, command in enumerate(self.tools['benchmarks'][name]):
            key = digest([name, index, l1, l2])
            folder = self.session / 'runs' / name / key
            folder.mkdir(parents=True, exist_ok=True)
            done = folder / 'complete.json'
            stats_path = folder / 'cache.stats'
            if done.exists() and stats_path.exists():
                stats = parse_stats(stats_path, l2 is not None)
                if json.loads(done.read_text()).get('stats') != stats:
                    raise ValueError('Saved statistics differ from completion record: ' + str(folder))
            else:
                work = folder / 'work'
                if not work.exists():
                    shutil.copytree(command['cwd'], str(work), symlinks=False)
                # Every job gets its own pristine source copy, including on retries.
                # A retry refreshes inputs but does not delete user or source files.
                else:
                    for source in Path(command['cwd']).rglob('*'):
                        if source.is_file():
                            target = work / source.relative_to(command['cwd'])
                            target.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(str(source), str(target))
                args = self.aslr + [self.tools['pin'], '-t', str(self.pintool), '-o', str(stats_path)]
                for level, cache in ((1, l1), (2, l2)):
                    if cache:
                        for knob, value in zip(('c', 'b', 'a', 'r'), cache):
                            args.extend(['-l{}{}'.format(level, knob), str(value)])
                args += ['--'] + command['argv']
                save_json(folder / 'command.json', {'argv': args, 'cwd': str(work), 'source': command})
                log('{} input {}: {} / {}'.format(name, index + 1, label(l1), label(l2) if l2 else 'DRAM'))
                start = time.time()
                stdin = command.get('stdin')
                if stdin:
                    stdin = Path(stdin) if Path(stdin).is_absolute() else work / stdin
                run(args, work, folder / 'program.log', stdin, self.env, self.timeout)
                stats = parse_stats(stats_path, l2 is not None)
                save_json(done, {'elapsed_seconds': time.time() - start, 'stats': stats,
                                 'pintool_sha256': getattr(self, 'manifest', {}).get('pintool_sha256')})
            for k, v in stats.items():
                totals[k] = totals.get(k, 0) + v
        return totals

    def evaluate(self, l1, l2, stage):
        if not valid_pair(l1, l2):
            return None
        config_id = digest([l1, l2])
        if config_id in self.scores:
            for row in self.rows:
                if row['config_id'] == config_id and stage not in row['stages'].split(';'):
                    row['stages'] += ';' + stage
            self.scores[config_id]['stages'] = ';'.join(sorted(set(
                self.scores[config_id]['stages'].split(';') + [stage])))
            self.export_parts()
            return self.scores[config_id]
        h1 = self.hardware(l1)
        h2 = self.hardware(l2) if l2 else None
        rows = []
        for name in sorted(self.tools['benchmarks']):
            stats = self.collect(name, l1, l2)
            n = stats['accesses']
            row = {'config_id': config_id, 'stages': stage, 'benchmark': name,
                   'l1': label(l1), 'l2': label(l2) if l2 else 'none'}
            for prefix, c in (('l1', l1), ('l2', l2)):
                for field, value in zip(Cache._fields, c if c else ('',) * 4):
                    row[prefix + '_' + field] = value
            row.update(stats)
            row.update({'l1_miss_rate': stats['misses'] / n,
                        'l2_miss_rate': stats.get('l2_misses', 0) / stats['l2_accesses']
                        if stats.get('l2_accesses') else 0.0,
                        'amat_ns': amat(stats, h1, h2),
                        'area_mm2': h1['area_mm2'] + (h2['area_mm2'] if h2 else 0),
                        'leakage_mw': h1['leakage_mw'] + (h2['leakage_mw'] if h2 else 0),
                        'data_bytes': (l1.kb + (l2.kb if l2 else 0)) * 1024,
                        'metadata_bytes_estimate': overhead(l1) + (overhead(l2) if l2 else 0)})
            # Lookup, demand-write, and fill energy. Dirty eviction/coherence
            # traffic is not modeled; explicitly call this a demand-energy estimate.
            energy = 0.0
            for prefix, h in (('', h1), ('l2_', h2)):
                if h:
                    energy += (stats[prefix + 'read_hits'] * h['hit_nj']
                               + stats[prefix + 'write_hits'] * h['write_nj']
                               + stats[prefix + 'misses'] * (h['miss_nj'] + h['write_nj']))
            row['demand_energy_nj_per_access'] = energy / n
            # Fixed offered load, NOT host Pin wall time or measured processor power.
            rate = self.settings.get('accesses_per_second', 1e9)
            row['dynamic_power_estimate_mw'] = energy / n * rate * 1e-6
            row['total_power_estimate_mw'] = row['leakage_mw'] + row['dynamic_power_estimate_mw']
            rows.append(row)
        self.rows.extend(rows)
        score = {k: rows[0][k] for k in ('config_id', 'stages', 'l1', 'l2', 'area_mm2',
                                       'leakage_mw', 'data_bytes', 'metadata_bytes_estimate')}
        for k in ('amat_ns', 'demand_energy_nj_per_access', 'total_power_estimate_mw'):
            score[k] = sum(r[k] for r in rows) / len(rows)
        score['l1_config'], score['l2_config'] = list(l1), list(l2) if l2 else None
        self.scores[config_id] = score
        write_csv(self.session / 'measurements.csv', self.rows)
        self.export_parts()
        save_json(self.session / 'scores.json', list(self.scores.values()))
        return score

    def export_parts(self):
        """Publish per-part tables as runs finish, including reused configurations."""
        for part in ('part1', 'part2', 'part4'):
            folder = self.session / part
            folder.mkdir(parents=True, exist_ok=True)
            rows = [r for r in self.rows if
                    (r['l2_kb'] != '' if part == 'part4' else
                     'task' + part[-1] in r['stages'].split(';'))]
            write_csv(folder / 'measurements.csv', rows)
            geometries, runs = set(), []
            for row in rows:
                caches = []
                for level in ('l1', 'l2'):
                    cache = Cache(*(row[level + '_' + field] for field in Cache._fields)) if row[level + '_kb'] != '' else None
                    caches.append(cache)
                    if cache:
                        geometries.add((cache.kb, cache.block, cache.ways))
                for index, _ in enumerate(self.tools['benchmarks'][row['benchmark']]):
                    key = digest([row['benchmark'], index, caches[0], caches[1]])
                    shared = '../runs/{}/{}'.format(row['benchmark'], key)
                    runs.append({'benchmark': row['benchmark'], 'config_id': row['config_id'],
                                 'input': index + 1, 'stats_file': shared + '/cache.stats',
                                 'program_log': shared + '/program.log',
                                 'command_file': shared + '/command.json'})
            write_csv(folder / 'runs.csv', runs)
            hardware = [dict(self.hardware_cache[key], size_kb=key[0], block_bytes=key[1], ways=key[2])
                        for key in sorted(geometries)]
            write_csv(folder / 'hardware.csv', hardware)

    def search(self):
        log('Task 1: capacity, block-size, and associativity sweep.')
        for kb, block, ways in itertools.product((2, 4, 8), (32, 64), (1, 2, 4)):
            self.evaluate(Cache(kb, block, ways, 'lru'), None, 'task1')
        log('Task 2: replacement-policy comparison, including round-robin.')
        for kb, ways in ((2, 1), (4, 2), (8, 4)):
            for policy in POLICIES:
                self.evaluate(Cache(kb, 64, ways, policy), None, 'task2')
        log('Tasks 3/4: staged two-level design search.')
        l1s = [Cache(k, b, a, 'lru') for k, b, a in itertools.product(
            self.settings.get('l1_sizes_kb', [8, 32, 64]), (32, 64), (1, 4, 8))]
        l2s = [Cache(k, b, a, 'lru') for k, b, a in itertools.product(
            self.settings.get('l2_sizes_kb', [128, 256, 512, 1024, 4096]), (64, 128), (2, 4, 8))]
        baseline = Cache(512, 64, 8, 'lru')
        candidates = [self.evaluate(c, baseline, 'l1_search') for c in l1s]
        candidates = [c for c in candidates if c]
        best_l1 = Cache(*min(candidates, key=selection_key)['l1_config'])
        candidates += [self.evaluate(best_l1, c, 'l2_search') for c in l2s]
        candidates = [c for c in candidates if c]
        # Cross the best geometries with independently chosen per-level policies.
        seen = set()
        finalists = []
        for candidate in sorted(candidates, key=selection_key):
            pair = (tuple(candidate['l1_config']), tuple(candidate['l2_config']))
            if pair not in seen:
                seen.add(pair)
                finalists.append(pair)
            if len(finalists) == 4:
                break
        for first, second in finalists:
            for p1, p2 in itertools.product(POLICIES, repeat=2):
                self.evaluate(Cache(*first)._replace(policy=p1), Cache(*second)._replace(policy=p2), 'policy_search')
        best = min((s for s in self.scores.values() if s['l2_config']), key=selection_key)
        l1, l2 = Cache(*best['l1_config']), Cache(*best['l2_config'])
        # Controlled one-variable-at-a-time experiments around the selected design.
        for ways in (1, 2, 4, 8, 16):
            self.evaluate(l1, l2._replace(ways=ways), 'sensitivity_associativity')
        for kb in (128, 256, 512, 1024, 2048, 4096):
            self.evaluate(l1, l2._replace(kb=kb), 'sensitivity_size')
        save_json(self.session / 'part4/sensitivity_anchor.json', best)
        self.report()

    def report(self):
        scores = [s for s in self.scores.values() if s['l2_config']]
        frontier = pareto(scores, ('amat_ns', 'area_mm2', 'total_power_estimate_mw'))
        front_ids = {s['config_id'] for s in frontier}
        for s in scores:
            s['pareto_optimal'] = s['config_id'] in front_ids
        write_csv(self.session / 'measurements.csv', self.rows)
        self.export_parts()
        write_csv(self.session / 'part4/design_space.csv', scores)
        write_csv(self.session / 'part4/pareto.csv', frontier)
        best = min(scores, key=selection_key)
        save_json(self.session / 'part4/recommended.json', best)
        hardware_rows = []
        for (kb, block, ways), metrics in sorted(self.hardware_cache.items()):
            hardware_rows.append(dict(metrics, size_kb=kb, block_bytes=block, ways=ways,
                                      hit_cycles_at_2ghz=metrics['hit_ns'] * 2,
                                      tag_area_fraction=metrics['tag_area_mm2'] / metrics['area_mm2']))
        write_csv(self.session / 'hardware.csv', hardware_rows)
        plots = []
        def chart(filename, title, xlabel, ylabel, series, bars=False, lines=True):
            (self.session / filename).parent.mkdir(parents=True, exist_ok=True)
            svg_chart(self.session / filename, title, xlabel, ylabel, series, bars, lines)
            plots.append((title, filename))
        for name in sorted(self.tools['benchmarks']):
            rows = [r for r in self.rows if r['benchmark'] == name]
            series = {}
            for r in rows:
                if 'task1' in r['stages'].split(';'):
                    key = '{} KB, {} B'.format(r['l1_kb'], r['l1_block'])
                    series.setdefault(key, []).append((r['l1_ways'], r['amat_ns']))
            chart('part1/plots/' + name + '-task1.svg', name + ': single-level AMAT', 'Associativity', 'AMAT (ns)', series)
            series = {}
            for r in rows:
                if 'task2' in r['stages'].split(';'):
                    key = '{} KB, {} way'.format(r['l1_kb'], r['l1_ways'])
                    series.setdefault(key, []).append((POLICIES.index(r['l1_policy']), r['l1_miss_rate']))
            chart('part2/plots/' + name + '-task2.svg', name + ': replacement (0=random, 1=LRU, 2=bit-PLRU, 3=RR)',
                  'Policy', 'Miss rate', series, bars=True)
        for stage, field, axis in (('sensitivity_associativity', 'l2_ways', 'L2 ways'),
                                   ('sensitivity_size', 'l2_kb', 'L2 capacity (KB)')):
            series = {}
            for r in self.rows:
                if stage in r['stages'].split(';'):
                    series.setdefault(r['benchmark'], []).append((r[field], r['amat_ns']))
            chart('part4/plots/' + stage + '.svg', stage.replace('_', ' '), axis, 'AMAT (ns)', series)
        for field, axis in (('area_mm2', 'Area (mm^2)'), ('total_power_estimate_mw', 'Estimated power (mW)')):
            front2 = pareto(scores, ('amat_ns', field))
            chart('part4/plots/pareto-' + field + '.svg', 'Design space and 2D Pareto frontier', axis, 'Mean AMAT (ns)',
                  {'All evaluated': [(r[field], r['amat_ns']) for r in scores],
                   '2D frontier': [(r[field], r['amat_ns']) for r in front2]}, lines=False)
        chosen = sorted(frontier, key=selection_key)[:8]
        series = {}
        for name in sorted(self.tools['benchmarks']):
            series[name] = [(i + 1, next(r['amat_ns'] for r in self.rows
                                       if r['config_id'] == s['config_id'] and r['benchmark'] == name))
                            for i, s in enumerate(chosen)]
        chart('part4/plots/pareto-benchmarks.svg', 'Pareto configurations by benchmark', 'Design number (table below)',
              'AMAT (ns)', series, bars=True)
        report_html(self, best, chosen, frontier, plots)
        save_json(self.session / 'COMPLETE.json', {'configurations': len(self.scores),
                  'benchmark_measurements': len(self.rows), 'recommended': best['config_id'],
                  'finished_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())})
        log('COMPLETE: ' + str(self.session / 'report.html'))


def selection_key(row):
    # Exact performance ties break on area, then power. No hidden tolerance.
    return (row['amat_ns'], row['area_mm2'], row['total_power_estimate_mw'])


def pareto(rows, fields):
    return [r for r in rows if not any(
        all(o[k] <= r[k] for k in fields) and any(o[k] < r[k] for k in fields)
        for o in rows)]


def svg_chart(path, title, xlabel, ylabel, series, bars=False, lines=True):
    points = [p for data in series.values() for p in data]
    if not points:
        raise ValueError('Cannot plot empty data: ' + title)
    xmax, ymax = max(p[0] for p in points), max(p[1] for p in points)
    xmin = min(p[0] for p in points)
    span = max(xmax - xmin, 1)
    xmin -= span * .08
    xmax += span * .08
    ymax = ymax * 1.15 or 1
    x = lambda v: 90 + (v - xmin) / (xmax - xmin) * 760
    y = lambda v: 430 - v / ymax * 340
    esc = html.escape
    svg = ['<svg xmlns="http://www.w3.org/2000/svg" width="1100" height="510" viewBox="0 0 1100 510">',
           '<rect width="100%" height="100%" fill="white"/>',
           '<g font-family="sans-serif" font-size="12" fill="#253047">',
           '<text x="90" y="32" font-size="18">' + esc(title) + '</text>']
    for i in range(6):
        yy = 430 - i * 340 / 5
        xx = 90 + i * 760 / 5
        svg.append('<path d="M90 {0}H850" stroke="#e2e8f0"/><text x="12" y="{1}">{2:.4g}</text>'.format(yy, yy+4, ymax*i/5))
        svg.append('<text x="{}" y="453" text-anchor="middle">{:.4g}</text>'.format(xx, xmin+(xmax-xmin)*i/5))
    colors = ['#2563eb', '#e15759', '#059669', '#9333ea', '#d97706', '#0891b2']
    for i, (name, data) in enumerate(series.items()):
        data = sorted(set(data))
        color = colors[i % len(colors)]
        if (lines or name == '2D frontier') and not bars:
            svg.append('<polyline fill="none" stroke="{}" points="{}"/>'.format(
                color, ' '.join('{:.2f},{:.2f}'.format(x(a), y(b)) for a, b in data)))
        for a, b in data:
            if bars:
                width = min(18, 650 / max(1, len(data)) / (len(series) + 1))
                xx = x(a) + (i - (len(series) - 1)/2)*width
                svg.append('<rect x="{}" y="{}" width="{}" height="{}" fill="{}"/>'.format(
                    xx-width/2, y(b), width*.9, 430-y(b), color))
            else:
                svg.append('<circle cx="{}" cy="{}" r="3" fill="{}"/>'.format(x(a), y(b), color))
        svg.append('<rect x="870" y="{}" width="10" height="10" fill="{}"/><text x="887" y="{}">{}</text>'.format(
            70+i*23, color, 80+i*23, esc(name)))
    svg += ['<text x="460" y="492" text-anchor="middle">' + esc(xlabel) + '</text>',
            '<text x="18" y="70">' + esc(ylabel) + '</text>', '</g></svg>']
    Path(path).write_text('\n'.join(svg))


def report_html(exp, best, chosen, frontier, plots):
    esc = html.escape
    parts = ['<!doctype html><meta charset="utf-8"><title>Lab 2 results</title>',
             '<style>body{font:16px/1.6 system-ui;margin:40px auto;max-width:1150px;color:#172033}'
             'table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccd3df;padding:8px;text-align:left}'
             'img{width:100%}code{background:#eee} @media print{h2{break-after:avoid}img{break-inside:avoid}}</style>',
             '<h1>Lab 2: collected results and analysis</h1>',
             '<p>Input size: <b>{}</b>. {} evaluated configurations; {} benchmark summaries; '
             '{} points on the three-objective Pareto frontier. All inputs in each selected SPEC command file '
             'were run. These are architectural experiments, not official SPEC scores.</p>'.format(
                 esc(exp.tools['input_size']), len(exp.scores), len(exp.rows), len(frontier)),
             '<h2>Selected hierarchy</h2><p>L1: <b>{}</b>; L2: <b>{}</b>. '
             'Equal-weight mean gcc/leela AMAT: {:.5g} ns. Area: {:.5g} mm². '
             'Estimated total power: {:.5g} mW. The winner is the best measured design in the bounded '
             'staged search; this does not establish a global optimum.</p>'.format(
                 esc(best['l1']), esc(best['l2']), best['amat_ns'], best['area_mm2'], best['total_power_estimate_mw']),
             '<h2>Method and model assumptions</h2><ul>',
             '<li>18 single-level configurations; four replacement policies on three configurations. '
             '2 KB direct mapped, 4 KB 2-way, and 8 KB 4-way expose capacity/conflict pressure and '
             'increase replacement freedom. Direct mapping is a policy-independent control.</li>',
             '<li>Search L1 geometry with a fixed 512 KB L2; search L2 with the best L1; cross all '
             'four policies independently at both levels for the four best geometry pairs. '
             'Finally vary L2 size and associativity one at a time around a recorded anchor.</li>',
             '<li>Destiny models 2D SRAM at {} nm, 350 K, LOP, normal access, optimized for read latency. '
             'Every configuration and raw output is retained under destiny/. '
             'Read/write latency, hit/miss/write energy, area, and leakage are in hardware.csv.</li>'.format(
                 exp.settings.get('process_nm', 65)),
             '<li>AMAT uses the handout formula with separate hit/miss latencies and 9.5 ns DRAM latency. '
             'Times are in ns, never mixed with CPU cycles. Hardware CSV also shows L1 latency at an '
             'explicit illustrative 2 GHz CPU clock.</li>',
             '<li>Demand-only, cold-start data-cache model: both loads and stores allocate on a miss; '
             'L1 misses fetch through L2; no inclusion constraint, dirty eviction traffic, coherence, '
             'prefetching, instruction cache, or memory-level parallelism. Stores do not propagate to L2 '
             'on hits. AMAT follows the handout demand-access convention; it is not full processor runtime.</li>',
             '<li>Energy includes lookup and one fill write per miss; it excludes writebacks, DRAM '
             'energy, and replacement-controller energy. Dynamic power is an estimate at {:.4g} offered '
             'L1 accesses/s, not a measured machine power. Leakage is added separately. Compare energy '
             'per access as well as power; these assumptions limit physical-power conclusions.</li>'.format(
                 exp.settings.get('accesses_per_second', 1e9)),
             '<li>5 MiB budget applies to cache data capacity. Analytical metadata overhead assumes '
             '64-bit addresses and includes tags, valid bits, and replacement bits separately. '
             'Destiny includes its own tag-array model in area; controller overhead is not modeled.</li>',
             '<li>ASLR disabled: {}. Fixed PRNG seed and single OpenMP thread. '
             'When ASLR is unavailable, policy differences may include address-layout noise. '
             'Completion requires zero process exit status and consistent counters; SPEC output '
             'correctness comparisons are not performed by this runner.</li></ul>'.format(bool(exp.aslr)),
             '<h2>Implementability evidence</h2>']
    for level, config in (('L1', best['l1_config']), ('L2', best['l2_config'])):
        cache = Cache(*config)
        h = exp.hardware(cache)
        parts.append('<p>{}: read-hit latency {:.4g} ns ({:.4g} cycles at 2 GHz), write latency {:.4g} ns, '
                     'read-hit/write energy {:.4g}/{:.4g} nJ, leakage {:.4g} mW. '
                     'Destiny tag area is {:.2%} of cache area; estimated logical metadata/data ratio {:.2%}. '
                     '{}</p>'.format(level, h['hit_ns'], 2*h['hit_ns'], h['write_ns'], h['hit_nj'],
                         h['write_nj'], h['leakage_mw'], h['tag_area_mm2']/h['area_mm2'],
                         overhead(cache)/(cache.kb*1024),
                         'L1 exceeds a three-cycle illustrative target; discuss this tradeoff.'
                         if level == 'L1' and h['hit_ns']*2 > 3 else ''))
    parts.append('<h2>Replacement observations</h2>')
    for name in sorted(exp.tools['benchmarks']):
        for kb, ways in ((2, 1), (4, 2), (8, 4)):
            rows = [r for r in exp.rows if r['benchmark'] == name and 'task2' in r['stages'].split(';')
                    and r['l1_kb'] == kb and r['l1_ways'] == ways]
            winner = min(rows, key=lambda r: r['l1_miss_rate'])
            spread = max(r['l1_miss_rate'] for r in rows) - min(r['l1_miss_rate'] for r in rows)
            parts.append('<p>{}, {} KB / {} way: lowest observed miss rate {:.3%} ({}); '
                         'policy spread {:.3f} percentage points. {}</p>'.format(
                             name, kb, ways, winner['l1_miss_rate'], winner['l1_policy'], spread*100,
                             'Direct-mapped differences indicate run variation, not replacement benefit.' if ways == 1 else ''))
    parts.append('<h2>Pareto configurations shown in the bar chart</h2><table><tr><th>#</th><th>L1</th>'
                 '<th>L2</th><th>Mean AMAT (ns)</th></tr>')
    for i, s in enumerate(chosen, 1):
        parts.append('<tr><td>{}</td><td>{}</td><td>{}</td><td>{:.5g}</td></tr>'.format(
            i, esc(s['l1']), esc(s['l2']), s['amat_ns']))
    parts.append('</table>')
    for title, filename in plots:
        parts.append('<h2>{}</h2><img src="{}" alt="{}">'.format(esc(title), filename, esc(title)))
    parts.append('<h2>Files and final writeup</h2><p>measurements.csv contains per-benchmark counters; '
                 'part1/ and part2/ contain their own measurements, hardware tables, run indexes, and plots. '
                 'part4/ contains the two-level measurements, design_space.csv, pareto.csv, '
                 'recommended.json, and sensitivity/Pareto plots. All figures are in the respective '
                 'part\'s plots/ subfolder. Each part\'s runs.csv points to shared '
                 'raw runs using paths relative to that part folder. hardware.csv contains all '
                 'Destiny metrics; manifest.json records provenance. '
                 'Use these results in your final PDF and discuss the modeling limitations, power budget, '
                 'and latency target. This generated report is a reviewable analysis draft.</p>'
                 '<p>Tool references: <a href="https://github.com/sparsh0mittal/destiny_3d_cache">'
                 'Destiny author mirror</a>; <a href="https://www.spec.org/cpu2017/Docs/utility.html">'
                 'SPEC utilities</a>.</p>')
    (exp.session / 'report.html').write_text('\n'.join(parts), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Discover dependencies without running experiments')
    parser.add_argument('--diagnose', action='store_true', help='List SPEC paths and search issues; no builds, downloads, or benchmark runs')
    parser.add_argument('--config', type=Path, default=ROOT / 'lab2_config.json')
    args = parser.parse_args()
    settings = json.loads(args.config.read_text()) if args.config.exists() else {}
    for key in ('l1_sizes_kb', 'l2_sizes_kb'):
        if key in settings and (not settings[key] or any(
                not isinstance(v, int) or v <= 0 or v & (v-1) for v in settings[key])):
            raise ValueError(key + ' must be a nonempty list of positive powers of two')
    if not math.isfinite(float(settings.get('accesses_per_second', 1e9))) or settings.get('accesses_per_second', 1e9) <= 0:
        raise ValueError('accesses_per_second must be positive and finite')
    out = Path(settings.get('output_dir', str(ROOT / 'lab2-output'))).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    if sys.platform != 'linux':
        raise RuntimeError('Run this collector on the Linux ECE machine. Python unit tests run on any OS.')
    # flock is released even after a crash; prevent concurrent writers to the same output tree.
    import fcntl
    with (out / '.runner.lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Another collector is already using ' + str(out))
        if args.diagnose:
            log('Inspecting SPEC setup (no workloads will be run)...')
            _, _, diagnostics = discover_files(settings, out)
            print_discovery(diagnostics, out)
            return
        tools = discover(settings, out)
        save_json(out / 'discovered.json', tools)
        if args.check:
            log('Preflight passed. See ' + str(out / 'discovered.json'))
            return
        exp = Experiment(settings, tools, out)
        exp.prepare()
        exp.search()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        log('Interrupted. Re-run python3 script.py to resume completed configurations.')
        sys.exit(130)
    except (RuntimeError, ValueError, OSError, subprocess.TimeoutExpired) as error:
        print('\nERROR: {}\nCompleted runs are preserved; fix the issue and rerun python3 script.py.'.format(error),
              file=sys.stderr)
        sys.exit(1)
