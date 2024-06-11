import io
import pytest
from typing import Generator
from pathlib import Path
from tempfile import TemporaryDirectory
from contextlib import redirect_stdout

import src as pymk
from src import Target, PhonyTarget


@pytest.fixture
def tmpdir() -> Generator[Path, None, None]:
    with TemporaryDirectory() as tmpdir_str:
        yield Path(tmpdir_str)


def run_pymk(targets: list[PhonyTarget]) -> tuple[int, str]:
    with io.StringIO() as buf, redirect_stdout(buf):
        status = pymk.run(0, targets)
        return status, buf.getvalue()


def test_trivial_command() -> None:
    status, output = run_pymk([PhonyTarget('x', cmd='echo hello world > /dev/null')])
    assert status == 0
    assert output.strip() == 'echo hello world > /dev/null'


def test_simple_dependencies(tmpdir: Path) -> None:
    a = Target(cmd='echo a > $OUTPUT', output=tmpdir / 'a.txt')
    b = Target(cmd='echo b > $OUTPUT', output=tmpdir / 'b.txt')
    c = Target(cmd='echo c > $OUTPUT', output=tmpdir / 'c.txt')
    abc = Target(cmd='cat $FILES > $OUTPUT', depends={'FILES': [a, b, c]}, output=tmpdir / 'abc.txt')
    status, output = run_pymk([PhonyTarget('x', depends=abc)])
    assert status == 0
    assert f'echo a > {tmpdir / "a.txt"}' in output
    assert f'echo b > {tmpdir / "b.txt"}' in output
    assert f'echo c > {tmpdir / "c.txt"}' in output
    assert f'cat {tmpdir / "a.txt"} {tmpdir / "b.txt"} {tmpdir / "c.txt"} > {tmpdir / "abc.txt"}' in output
    assert (tmpdir / 'abc.txt').read_text() == 'a\nb\nc\n'
