import argparse
import collections
import concurrent.futures
import re
import subprocess
import sys
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor
from pathlib import Path
from typing import Sequence, TypeAlias

TargetType: TypeAlias = 'Target  | PhonyTarget'
Dependency: TypeAlias = 'Target  | PhonyTarget | Path'
DependencyInput: TypeAlias = Dependency | Sequence[Dependency] | dict[str, Dependency | Sequence[Dependency]]


class PymkException(Exception):
    pass


def simplify_dependency_input(depends: DependencyInput) -> dict[str, list[Dependency]]:
    if isinstance(depends, dict):
        return {k: list(v if isinstance(v, Sequence) else [v]) for k, v in depends.items()}
    return {'__pymk_default_key__': list(depends) if isinstance(depends, Sequence) else [depends]}


class Target:
    cmd: str
    output: Path
    depends: dict[str, list[Dependency]]

    def __init__(self, cmd: str, output: Path, depends: DependencyInput | None = None) -> None:
        if depends is None:
            depends = {}
        self.cmd = cmd
        self.output = output
        self.depends = simplify_dependency_input(depends)

    def __str__(self) -> str:
        return str(self.output)


class PhonyTarget:
    name: str
    cmd: str | None
    depends: dict[str, list[Dependency]]
    help: str | None

    def __init__(
        self,
        name: str,
        cmd: str | None = None,
        depends: DependencyInput | None = None,
        help: str | None = None,
    ) -> None:
        if depends is None:
            depends = {}
        self.name = name
        self.cmd = cmd
        self.depends = simplify_dependency_input(depends)
        self.help = help

    def __str__(self) -> str:
        return self.name


VARIABLES = dict[str, str]()
VAR_SUBST_REGEX = re.compile(r'\$(\$|[A-Za-z0-9_]+|\([A-Za-z0-9_]+\))')


def set_variable(**variables: str) -> None:
    VARIABLES.update(variables)


def expand_cmd(t: TargetType) -> str:
    def get_variable(m: re.Match[str]) -> str:
        var = m.group(1).replace('(', '').replace(')', '')
        if var == '$':
            return '$'
        if var == 'OUTPUT' and isinstance(t, Target):
            return str(t.output)
        if var in t.depends:
            return ' '.join(str(x) for x in t.depends[var])
        if var in VARIABLES:
            return VARIABLES[var]
        raise PymkException(f'Unset variable "${var}"')

    assert t.cmd
    return VAR_SUBST_REGEX.sub(get_variable, t.cmd)


def execute_target_command(t: TargetType) -> TargetType:
    cmd = expand_cmd(t)
    print(cmd)
    exitcode = subprocess.run('bash', input=cmd.encode('utf-8')).returncode
    if exitcode != 0:
        raise PymkException(f'Target "{t}" failed. ({exitcode=})')
    return t


def modified_time(t: Path | Target) -> int:
    f = t if isinstance(t, Path) else t.output
    return f.stat().st_mtime_ns


def up_to_date(t: Target, modified_times: dict[Path | Target, int]) -> bool:
    try:
        mtime = modified_time(t)
    except FileNotFoundError:
        return False
    modified_times[t] = mtime
    for dependencies in t.depends.values():
        for dep in dependencies:
            if isinstance(dep, PhonyTarget):
                return False
            time = modified_times[dep]
            if time > mtime:
                return False
    return True


def build_execution_dag(targets: list[PhonyTarget]) -> tuple[dict[Dependency, list[TargetType]], list[Dependency]]:
    dag = dict[Dependency, list[TargetType]]()
    leafs = list[Dependency]()

    seen = set[Dependency]()
    q = collections.deque[Dependency](targets)
    while q:
        t = q.pop()
        if isinstance(t, Path) or not t.depends:
            leafs.append(t)
            continue
        for dependencies in t.depends.values():
            for target in dependencies:
                if target not in dag:
                    dag[target] = []
                dag[target].append(t)
                if target not in seen:
                    seen.add(target)
                    q.append(target)
    return dag, leafs


class TargetExecutor:
    executor: ThreadPoolExecutor
    futures: set[Future[TargetType]]
    dependants: dict[Dependency, list[TargetType]]
    deps_left: dict[TargetType, int]
    modified_times: dict[Path | Target, int]

    def __init__(self, jobs: int) -> None:
        self.executor = ThreadPoolExecutor(max_workers=jobs if jobs > 0 else None)
        self.futures = set()
        self.dependants = {}
        self.deps_left = {}
        self.modified_times = {}

    def exec_command(self, t: TargetType) -> None:
        self.futures.add(self.executor.submit(execute_target_command, t))

    def on_finished(self, t: Dependency) -> None:
        if not isinstance(t, PhonyTarget):
            try:
                self.modified_times[t] = modified_time(t)
            except FileNotFoundError as e:
                raise PymkException(f'Expected {t} to exist') from e
        for dependant in self.dependants.get(t, []):
            if dependant not in self.deps_left:
                self.deps_left[dependant] = sum(len(x) for x in dependant.depends.values())
            self.deps_left[dependant] -= 1
            if not self.deps_left[dependant]:
                self.run_target(dependant)

    def run_target(self, t: Dependency) -> None:
        match t:
            case Path():
                if not t.exists():
                    raise PymkException(f'File dependency "{t}" does not exist.')
            case Target():
                if not up_to_date(t, self.modified_times):
                    return self.exec_command(t)
            case PhonyTarget():
                if t.cmd:
                    return self.exec_command(t)
        self.on_finished(t)

    def execute(self, targets: list[PhonyTarget]) -> None:
        self.dependants, leafs = build_execution_dag(targets)
        with self.executor:
            for leaf in leafs:
                self.run_target(leaf)
            while self.futures:
                done, self.futures = concurrent.futures.wait(self.futures, return_when=FIRST_COMPLETED)
                for f in done:
                    self.on_finished(f.result())


def exit_help(targets: Sequence[PhonyTarget], error: str | None = None) -> None:
    print(f'usage: {sys.argv[0]} [-h] [-j [JOBS]] [-DVAR[=VALUE]] TARGET..')
    if error:
        print('error:', error)
        sys.exit(2)
    print()
    print('TARGET:')
    maxlen = max(len(t.name) for t in targets)
    for t in targets:
        print(f'  {t.name.ljust(maxlen)}  {t.help if t.help else ""}')
    print()
    print('OPTIONS:')
    print('  -j, --jobs JOBS        number of parallel jobs (default 0=infinite)')
    print('  -D, --var VAR[=VALUE]  set a variable, example -DCC=gcc-11')
    print('  -h, --help             print this help message and exit')
    sys.exit(0)


def run(jobs: int, targets: list[PhonyTarget]) -> int:
    try:
        executor = TargetExecutor(jobs)
        executor.execute(targets)
    except PymkException as e:
        print('pymk:', e)
        return 1
    except KeyboardInterrupt:
        print('pymk: interrupt')
        return 130
    return 0


def main(targets: list[PhonyTarget]) -> None:
    known_targets = dict[str, PhonyTarget]()
    for target in targets:
        if str(target) in known_targets:
            raise PymkException(f'Target "{target}" defined multiple times')
        known_targets[str(target)] = target

    if any(h in sys.argv[1:] for h in ['-h', '--help']):
        exit_help(targets)

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('-j', '--jobs', type=int, default=0)
    parser.add_argument('-D', '--var', action='append', default=[])
    parser.add_argument('targets', nargs='*')
    opts = parser.parse_args()

    if not opts.targets:
        exit_help(targets)
    for t in opts.targets:
        if t not in known_targets:
            exit_help(targets, f'unknown target "{t}"')

    for s in opts.var:
        var, *rest = s.split('=', maxsplit=1)
        set_variable(**{var: rest[0] if rest else ''})
    sys.exit(run(opts.jobs, [known_targets[t] for t in opts.targets]))
