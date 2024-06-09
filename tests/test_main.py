import sys
import io
from contextlib import redirect_stdout
from pathlib import Path

sys.path.append(Path(__file__).parent.parent)

import src as pymk
from src import Target, PhonyTarget

def run_pymk(targets: list[PhonyTarget]) -> tuple[int, str]:
    with io.StringIO() as buf, redirect_stdout(buf):
        status = pymk.run(0, targets)
        return status, buf.getvalue()

def test_thing() -> None:
    status, output = run_pymk([PhonyTarget('x', cmd='echo hello world >/dev/null')])
    assert status == 0
    assert output.strip() == 'echo hello world >/dev/null'
