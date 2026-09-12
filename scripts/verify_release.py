#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT
VENV_PYTHON = WORKSPACE / '.venv' / 'bin' / 'python'
PYTHON = str(VENV_PYTHON if VENV_PYTHON.exists() else Path(sys.executable))


def run(cmd, cwd):
    print('+', ' '.join(map(str, cmd)))
    subprocess.run(cmd, cwd=cwd, check=True)


def main():
    run([PYTHON, str(ROOT / 'scripts' / 'verify_repo_hygiene.py')], ROOT)
    run([PYTHON, '-m', 'compileall', '-q', 'app'], ROOT / 'backend')
    run([PYTHON, '-m', 'unittest', 'discover', '-s', 'tests', '-v'], ROOT)
    run([PYTHON, str(ROOT / 'scripts' / 'verify_runtime_acceptance.py')], ROOT)
    run(['npm', 'run', 'build'], ROOT / 'frontend')
    print('VERIFY_RELEASE_OK')


if __name__ == '__main__':
    main()
