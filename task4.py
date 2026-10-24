#!/usr/bin/env python3
"""Collect Task 4 using explicit benchmark commands from task4_config.json."""
import subprocess
import sys

import script


if __name__ == '__main__':
    try:
        script.main(task4_only=True)
    except KeyboardInterrupt:
        print('\nInterrupted. Run python3 task4.py again to resume.', file=sys.stderr)
        sys.exit(130)
    except (RuntimeError, ValueError, KeyError, OSError, subprocess.TimeoutExpired) as error:
        print('\nERROR: {}\nCompleted runs are preserved; fix the issue and rerun python3 task4.py.'.format(error),
              file=sys.stderr)
        sys.exit(1)
