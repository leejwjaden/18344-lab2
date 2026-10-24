"""python3 -m unittest discover -s tests -v (no Pin/SPEC/Destiny needed)."""
import csv
import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import patch

import script


# Field names/units follow the authors' Destiny Result.cpp cache summary.
DESTINY = '''CACHE DESIGN -- SUMMARY
Area:
 - Total Area = 0.125mm^2
 |--- Data Array Area = 100um x 100um = 0.1mm^2
 |--- Tag Array Area  = 50um x 50um = 0.025mm^2
Timing:
 - Cache Hit Latency   = 1.5ns
 - Cache Miss Latency  = 0.25ns
 - Cache Write Latency = 1.2ns
Power:
 - Cache Hit Dynamic Energy   = 0.2nJ per access
 - Cache Miss Dynamic Energy  = 0.03nJ per access
 - Cache Write Dynamic Energy = 0.18nJ per access
 - Cache Total Leakage Power  = 2.5mW
CACHE DATA ARRAY DETAILS
 - Read Latency = 999ns
'''


def stats_text(two=True):
    text = ('accesses: 100\nhits: 75\nmisses: 25\nreads: 80\nwrites: 20\n'
            'read_hits: 60\nwrite_hits: 15\nmiss_rate: 0.25\n')
    if two:
        text += ('l2_accesses: 25\nl2_hits: 20\nl2_misses: 5\nl2_reads: 25\n'
                 'l2_writes: 0\nl2_read_hits: 20\nl2_write_hits: 0\n')
    return text + 'dram_accesses: {}\n'.format(5 if two else 25)


class RunnerTests(unittest.TestCase):
    def test_course_config_environment_and_output_root(self):
        with tempfile.TemporaryDirectory(dir=str(Path(__file__).resolve().parent)) as tmp:
            root = Path(tmp)
            config = root / 'personal.cfg'
            output = root / 'scratch'
            config.write_text('output_root = ' + output.as_posix() + ' # course scratch\n')
            with patch.dict(script.os.environ, {'ECE344_SPEC_CONFIG': str(config)}, clear=True):
                selected, _ = script.spec_configuration({})
                self.assertEqual(selected, str(config))
                self.assertEqual(script.config_output_roots(selected), [output.as_posix()])
                with patch.dict(script.os.environ, {'SPEC_CONFIG': 'explicit.cfg'}):
                    self.assertEqual(script.spec_configuration({})[0], 'explicit.cfg')

    def test_course_discovery_finds_config_output_and_ignores_fake_runcpu(self):
        with tempfile.TemporaryDirectory(dir=str(Path(__file__).resolve().parent)) as tmp:
            root = Path(tmp)
            install = root / 'course/opt/spec2017'
            (install / 'bin/harness').mkdir(parents=True)
            (install / 'bin/runcpu').write_text('fixture')
            (install / 'bin/harness/runcpu').write_text('fixture')
            (install / 'shrc').write_text('fixture')
            output = root / 'scratch'
            work = output / 'benchspec/CPU/602.gcc_s/run/run_base_test_example.0000'
            work.mkdir(parents=True)
            (work / 'cpugcc_s').write_text('fixture')
            (work / 'speccmds.cmd').write_text('./cpugcc_s input.c\n')
            config = root / 'course.cfg'
            config.write_text('output_root = ' + output.as_posix() + '\n')
            with patch.object(script, 'discovery_roots', return_value=[str(install)]), \
                    patch.dict(script.os.environ, {'ECE344_SPEC_CONFIG': str(config)}, clear=True):
                _, _, report = script.discover_files({}, root)
            self.assertEqual(report['tools']['runcpu'], [str(install / 'bin/runcpu')])
            self.assertEqual(len(report['workload_candidates']), 1)
            self.assertTrue(report['workload_candidates'][0]['requested_speed_and_size'])

    def test_runsetup_sources_spec_and_overrides_submit_and_output(self):
        with tempfile.TemporaryDirectory(dir=str(Path(__file__).resolve().parent)) as tmp:
            root = Path(tmp)
            install = root / 'SPEC with spaces'
            install.mkdir()
            (install / 'shrc').write_text('fixture')
            output = root / 'personal output'
            with patch.object(script, 'run') as run, patch.object(script, 'log'):
                result = script.setup_spec(install / 'bin/runcpu', 'personal.cfg', 'test',
                                           '602.gcc_s', {'spec_output_root': str(output)}, root)
            command = run.call_args[0][0]
            self.assertEqual(result, output.resolve())
            self.assertEqual(command[:2], ['bash', '-c'])
            self.assertIn('--no-use-submit-for-speed', command)
            self.assertIn('--output_root=' + str(output.resolve()), command)
            self.assertIn('--action=runsetup', command)
            self.assertIn('--noreportable', command)
            self.assertIn(str(install), command)

    def test_discovery_revisits_overlapping_roots_with_more_depth(self):
        with tempfile.TemporaryDirectory(dir=str(Path(__file__).resolve().parent)) as tmp:
            root = Path(tmp)
            run = root / 'installation/benchspec/CPU/602.gcc_s/run/run_base_test_example.0000'
            run.mkdir(parents=True)
            command = run / 'speccmds.cmd'
            command.write_text('fixture')
            found = script.walk_find([root, root / 'installation/benchspec/CPU'],
                                     ('speccmds.cmd',), max_depth=3)
            self.assertEqual(found, [command])

    def test_discovery_follows_installation_symlink_without_looping(self):
        with tempfile.TemporaryDirectory(dir=str(Path(__file__).resolve().parent)) as tmp:
            root = Path(tmp)
            install = root / 'actual'
            install.mkdir()
            (root / 'search').mkdir()
            (install / 'speccmds.cmd').write_text('fixture')
            try:
                (root / 'search/spec').symlink_to(install, target_is_directory=True)
                (install / 'loop').symlink_to(root / 'search', target_is_directory=True)
            except OSError:
                self.skipTest('Creating directory symlinks is unavailable on this host')
            found = script.walk_find([root / 'search'], ('speccmds.cmd',))
            self.assertEqual(len(found), 1)
            self.assertEqual(found[0].resolve(), install / 'speccmds.cmd')

    def test_destiny_cache_summary(self):
        h = script.parse_destiny(DESTINY)
        self.assertEqual(h['tag_area_mm2'], .025)
        self.assertEqual(h['hit_ns'], 1.5)
        self.assertEqual(h['leakage_mw'], 2.5)
        with self.assertRaises(ValueError):
            script.parse_destiny('No valid cache found')
        with self.assertRaises(ValueError):
            script.parse_destiny(DESTINY.replace('1.5ns', 'nan ns'))

    def test_amat_uses_distinct_miss_latency_and_dram(self):
        h = script.parse_destiny(DESTINY)
        stats = dict(accesses=100, misses=25, l2_accesses=25, l2_misses=5)
        self.assertAlmostEqual(script.amat(stats, h), .75*1.5+.25*(.25+9.5))
        self.assertAlmostEqual(script.amat(stats, h, h), .75*1.5+.25*(.25+.8*1.5+.2*(.25+9.5)))

    def test_counters_require_complete_consistent_run(self):
        with tempfile.TemporaryDirectory(dir=str(Path(__file__).resolve().parent)) as tmp:
            p = Path(tmp) / 'stats'
            p.write_text(stats_text())
            self.assertEqual(script.parse_stats(p, True)['dram_accesses'], 5)
            p.write_text(stats_text().replace('l2_accesses: 25', 'l2_accesses: 26'))
            with self.assertRaises(ValueError):
                script.parse_stats(p, True)
            p.write_text(stats_text(False))
            self.assertEqual(script.parse_stats(p, False)['dram_accesses'], 25)

    def test_spec_paths_quotes_and_multiple_inputs(self):
        with tempfile.TemporaryDirectory(prefix='spec space ', dir=str(Path(__file__).resolve().parent)) as tmp:
            root = Path(tmp)
            exe = root / 'cpugcc_s_base.test'
            exe.write_text('fixture')
            p = root / 'speccmds.cmd'
            p.write_text('-c "{}"\n-o out -e err ./cpugcc_s_base.test "input one.c" -O3\n'
                         '-i in -o out2 -e err2 ./cpugcc_s_base.test input2.c\n'.format(root))
            commands = script.parse_speccmds(p)
            self.assertEqual(len(commands), 2)
            self.assertEqual(commands[0]['argv'][1], 'input one.c')
            self.assertEqual(commands[1]['stdin'], 'in')
            self.assertEqual(commands[1]['cwd'], str(root.resolve()))

    def test_spec_environment_headers_are_metadata_not_commands(self):
        with tempfile.TemporaryDirectory(dir=str(Path(__file__).resolve().parent)) as tmp:
            root = Path(tmp)
            (root / 'cpugcc_s_base.mytest-m64').write_text('fixture')
            p = root / 'speccmds.cmd'
            p.write_text(
                '-E OMP_NUM_THREADS 8\n'
                '-E EMPTY_VALUE\n'
                '  -E MESSAGE literal # hash and an unmatched quote: \'\n'
                '-E SHELL_TEXT $(touch should-never-execute)\n'
                '-C 1\n'
                '-c "{}"\n'
                '-o gcc.out -e gcc.err ./cpugcc_s_base.mytest-m64 input.c -O3\n'.format(root))
            with patch.dict(script.os.environ, {'OMP_NUM_THREADS': '1'}):
                commands = script.parse_speccmds(p)
                self.assertEqual(script.os.environ['OMP_NUM_THREADS'], '1')
            self.assertEqual(len(commands), 1)
            self.assertEqual(commands[0]['argv'][1:], ['input.c', '-O3'])
            self.assertEqual(commands[0]['cwd'], str(root.resolve()))
            self.assertFalse((root / 'should-never-execute').exists())
            p.write_text('-E\n')
            with self.assertRaisesRegex(RuntimeError, 'Malformed SPEC environment record'):
                script.parse_speccmds(p)

    def test_direct_commands_bypass_spec_parser_and_setup(self):
        with tempfile.TemporaryDirectory(dir=str(Path(__file__).resolve().parent)) as tmp:
            root = Path(tmp)
            sdk = root / 'source/tools/Config'
            sdk.mkdir(parents=True)
            (sdk / 'makefile.config').write_text('fixture')
            for name in ('pin', 'destiny', 'sample_SRAM.cell', 'gcc', 'input one.c'):
                (root / name).write_text('fixture')
            entries = [{'cwd': str(root), 'argv': ['./gcc', 'input one.c', '-O3'],
                        'stdin': 'input one.c'}]
            settings = {'pin': str(root / 'pin'), 'pin_root': str(root),
                        'destiny': str(root / 'destiny'), 'destiny_cell': str(root / 'sample_SRAM.cell'),
                        'benchmark_commands': {'gcc': entries, 'leela': entries}}
            with patch.object(script, 'discover_files', return_value=([], [], {})), \
                    patch.object(script, 'parse_speccmds', side_effect=AssertionError('must bypass parser')), \
                    patch.object(script, 'setup_spec', side_effect=AssertionError('must bypass setup')):
                tools = script.discover(settings, root)
            self.assertEqual(tools['benchmarks']['gcc'][0]['argv'],
                             [str((root / 'gcc').resolve()), 'input one.c', '-O3'])
            self.assertEqual(tools['benchmarks']['leela'][0]['stdin'], 'input one.c')
            with self.assertRaisesRegex(ValueError, 'executable does not exist'):
                script.direct_commands([{'cwd': str(root), 'argv': ['./missing']}])
            with self.assertRaisesRegex(ValueError, 'nonempty JSON array'):
                script.direct_commands([{'cwd': str(root), 'argv': './gcc input.c'}])

    def test_budget_and_block_sizes(self):
        c = script.Cache
        self.assertTrue(script.valid_pair(c(64, 64, 4, 'lru'), c(4096, 128, 8, 'plru')))
        self.assertFalse(script.valid_pair(c(2048, 64, 4, 'lru'), c(4096, 128, 8, 'plru')))
        self.assertFalse(script.valid_pair(c(64, 128, 4, 'lru'), c(512, 64, 8, 'plru')))
        self.assertGreater(script.overhead(c(64, 64, 4, 'plru')), 0)

    def test_pareto_ties_and_tradeoffs(self):
        rows = [dict(x=1, y=2), dict(x=2, y=1), dict(x=2, y=3), dict(x=1, y=2)]
        self.assertEqual(script.pareto(rows, ('x', 'y')), [rows[0], rows[1], rows[3]])

    def test_end_to_end_with_fake_external_tools_and_resume(self):
        # Exercises real file handling, analysis, SVG/HTML generation, and resume;
        # the external simulator output is deliberately a fixture, never lab data.
        with tempfile.TemporaryDirectory(dir=str(Path(__file__).resolve().parent)) as tmp:
            root = Path(tmp)
            source = root / 'inputs'
            source.mkdir()
            (source / 'input.txt').write_text('data')
            command = {'cwd': str(source), 'argv': ['/fixture/gcc'], 'stdin': None}
            exp = object.__new__(script.Experiment)
            exp.settings = {}
            exp.tools = {'benchmarks': {'gcc': [command], 'leela': [command]},
                         'pin': '/fixture/pin', 'input_size': 'test'}
            exp.session = root / 'session'
            exp.session.mkdir()
            exp.hardware_cache, exp.rows, exp.scores = {}, [], {}
            exp.pintool = '/fixture/tool'
            exp.aslr, exp.env, exp.timeout = [], {}, None
            calls = []
            h = script.parse_destiny(DESTINY)
            def hardware(cache):
                exp.hardware_cache[(cache.kb, cache.block, cache.ways)] = h
                return h
            def fake_run(argv, cwd, logfile, *args):
                calls.append(argv)
                Path(argv[argv.index('-o') + 1]).write_text(stats_text('-l2c' in argv))
            exp.hardware = hardware
            with patch.object(script, 'run', side_effect=fake_run), patch.object(script, 'log'):
                exp.search()
                count = len(calls)
                self.assertGreater(count, 100)
                self.assertTrue((exp.session / 'COMPLETE.json').exists())
                self.assertTrue((exp.session / 'part4/plots/pareto-benchmarks.svg').exists())
                self.assertTrue((exp.session / 'part1/plots/gcc-task1.svg').exists())
                self.assertTrue((exp.session / 'part2/plots/leela-task2.svg').exists())
                for part, expected in (('part1', 36), ('part2', 24), ('part4', None)):
                    folder = exp.session / part
                    with (folder / 'measurements.csv').open(newline='') as f:
                        rows = list(csv.DictReader(f))
                    if expected:
                        self.assertEqual(len(rows), expected)
                        self.assertTrue(all('task' + part[-1] in r['stages'].split(';') for r in rows))
                    else:
                        self.assertTrue(rows)
                        self.assertTrue(all(r['l2_kb'] for r in rows))
                    self.assertTrue((folder / 'hardware.csv').exists())
                    with (folder / 'runs.csv').open(newline='') as f:
                        for row in csv.DictReader(f):
                            self.assertTrue((folder / row['stats_file']).is_file())
                for svg in exp.session.rglob('*.svg'):
                    self.assertEqual(ET.parse(str(svg)).getroot().tag, '{http://www.w3.org/2000/svg}svg')
                self.assertIn('9.5 ns', (exp.session / 'report.html').read_text(encoding='utf-8'))
                report = (exp.session / 'report.html').read_text(encoding='utf-8')
                self.assertIn('src="part1/plots/gcc-task1.svg"', report)
                self.assertIn('src="part4/plots/pareto-benchmarks.svg"', report)
                original_scores = json.loads((exp.session / 'part4/recommended.json').read_text())
                exp.rows, exp.scores = [], {}
                exp.search()
                self.assertEqual(len(calls), count, 'Completed jobs should not rerun')
                self.assertEqual(json.loads((exp.session / 'part4/recommended.json').read_text()), original_scores)
                # The direct-command entry point must also finish without Task 1/2 rows.
                exp.settings = {'task4_only': True}
                exp.rows, exp.scores = [], {}
                exp.session = root / 'task4-only'
                exp.session.mkdir()
                calls.clear()
                exp.search()
                self.assertTrue(calls)
                self.assertTrue(all('-l2c' in argv for argv in calls))
                self.assertFalse((exp.session / 'part1').exists())
                self.assertFalse((exp.session / 'part2').exists())
                self.assertTrue((exp.session / 'part4/plots/pareto-benchmarks.svg').exists())
                self.assertTrue((exp.session / 'COMPLETE.json').exists())
                self.assertIn('Task 4 only', (exp.session / 'report.html').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
