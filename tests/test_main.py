import io
from contextlib import contextmanager, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Generator

import pytest

import pymk
from pymk import PhonyTarget, Target


@pytest.fixture
def tmpdir() -> Generator[Path, None, None]:
    with TemporaryDirectory() as tmpdir_str:
        yield Path(tmpdir_str)


@contextmanager
def pymk_variables(variables: dict[str, str]) -> Generator[None, None, None]:
    pymk.set_variable(**variables)
    try:
        yield
    finally:
        pymk.internal.VARIABLES.clear()


def run_pymk(targets: list[PhonyTarget]) -> tuple[int, str]:
    with io.StringIO() as buf, redirect_stdout(buf):
        status = pymk.run(0, targets)
        return status, buf.getvalue()


def test_trivial_command() -> None:
    status, output = run_pymk([PhonyTarget('x', cmd='echo hello world > /dev/null')])
    assert status == 0
    assert output.strip() == 'echo hello world > /dev/null'


def test_var_expansion(tmpdir: Path) -> None:
    with pymk_variables({'A': 'a', 'B': 'b', 'C': 'c', 'DEV_NULL': '/dev/null', 'ECHO': 'echo'}):
        refers_to_output = Target(cmd='touch $OUTPUT', output=tmpdir / 'tmp.txt')
        status, output = run_pymk(
            [
                PhonyTarget('0', cmd='echo $dependency > /dev/null', depends={'dependency': refers_to_output}),
                PhonyTarget('1', cmd='echo $$VAR > /dev/null'),
                PhonyTarget('2', cmd='echo $A$B$C > /dev/null'),
                PhonyTarget('3', cmd='echo $(A)a${B} > /dev/null'),
                PhonyTarget('4', cmd='echo $A/next/to/path > /dev/null'),
                PhonyTarget('6', cmd='$ECHO expansions at edges > $DEV_NULL'),
            ]
        )
        assert status == 0
        assert f'touch {tmpdir / "tmp.txt"}' in output
        assert f'echo {tmpdir / "tmp.txt"} > /dev/null' in output
        assert 'echo $VAR > /dev/null' in output
        assert 'echo abc > /dev/null' in output
        assert 'echo aab > /dev/null' in output
        assert 'echo a/next/to/path > /dev/null' in output
        assert 'echo expansions at edges > /dev/null' in output

    status, output = run_pymk([PhonyTarget('a', cmd='echo $UNSET_VAR > /dev/null')])
    assert status != 0
    assert '$UNSET_VAR' in output

    status, output = run_pymk([PhonyTarget('a', cmd='echo $OUTPUT > /dev/null')])
    assert status != 0
    assert '$OUTPUT' in output


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


def test_exported_has_docstring() -> None:
    for x in dir(pymk):
        if x.startswith('__'):
            continue
        assert isinstance(getattr(pymk, x).__doc__, str)
