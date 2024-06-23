#!/usr/bin/python3
from os import chdir
from pathlib import Path

import pymk
from pymk import PhonyTarget

chdir(Path(__file__).parent)

files = sorted([Path('mk.py'), *Path('src').glob('*.py'), *Path('tests').glob('*.py')])
pymk.set_variable(FILES=' '.join(str(f) for f in files))

# fmt: off
pymk.main([
    PhonyTarget('mypy',   help='Type checking',    cmd='python3 -m mypy $FILES'),
    PhonyTarget('lint',   help='Lint all files',   cmd='python3 -m ruff check $FILES'),
    PhonyTarget('fmt',    help='Format all files', cmd='python3 -m ruff format $FILES'),
    PhonyTarget('fmt-ok', help='Check formatting', cmd='python3 -m ruff format --check $FILES'),
    PhonyTarget('test',   help='Run all tests',    cmd='python3 -m pytest -v tests'),
])
