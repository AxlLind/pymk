import re
import sys
import argparse
import subprocess
import concurrent.futures
import collections
from pathlib import Path
from typing import Sequence, TypeAlias
from concurrent.futures import ThreadPoolExecutor, Future, FIRST_COMPLETED

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

    def __init__(self, cmd: str, output: Path, depends: DependencyInput) -> None:
        self.cmd = cmd
        self.output = output
        self.depends = simplify_dependency_input(depends)

    def __str__(self) -> str:
        return str(self.output)


class PhonyTarget:
    name: str
    cmd: str | None
    depends: dict[str, list[Dependency]]

    def __init__(self, name: str, cmd: str | None = None, depends: DependencyInput = {}) -> None:
        self.name = name
        self.cmd = cmd
        self.depends = simplify_dependency_input(depends)

    def __str__(self) -> str:
        return self.name


VARIABLES = dict[str, str]()
VAR_SUBST_REGEX = re.compile(r'\$(\$|[A-Za-z0-9]+)')


def set_variable(**variables: str) -> None:
    VARIABLES.update(variables)


def expand_cmd(t: TargetType) -> str:
    def get_variable(m: re.Match[str]) -> str:
        var = m.group(1)
        if var == '$':
            return '$'
        if dep := t.depends.get(var):
            return ' '.join(str(x) for x in dep)
        if val := VARIABLES.get(var):
            return val
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


def up_to_date(t: Target) -> bool:
    if not t.output.exists() or not t.depends:
        return False
    mtime = modified_time(t)
    for dependencies in t.depends.values():
        for dep in dependencies:
            if isinstance(dep, PhonyTarget):
                return False
            time = modified_time(dep)
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

    def __init__(self, jobs: int) -> None:
        self.executor = ThreadPoolExecutor(max_workers=jobs if jobs > 0 else None)
        self.futures = set()
        self.dependants = {}
        self.deps_left = {}

    def exec_command(self, t: TargetType) -> None:
        self.futures.add(self.executor.submit(execute_target_command, t))

    def on_finished(self, t: Dependency) -> None:
        if isinstance(t, Target) and not t.output.exists():
            raise PymkException(f'Target {t} did not create expected output file')
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
                if not up_to_date(t):
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


def run(*targets: PhonyTarget) -> None:
    known_targets = dict[str, PhonyTarget]()
    for t in targets:
        if str(t) in known_targets:
            raise PymkException(f'Target "{t}" defined multiple times')
        known_targets[str(t)] = t

    parser = argparse.ArgumentParser()
    parser.add_argument('-j', '--jobs', type=int, default=0, help='number of parallel jobs (default 0=infinite)')
    parser.add_argument('targets', nargs='+', choices=known_targets.keys())
    opts = parser.parse_args()

    try:
        executor = TargetExecutor(opts.jobs)
        executor.execute([known_targets[t] for t in opts.targets])
    except PymkException as e:
        print('pymk:', e)
        sys.exit(1)
    except KeyboardInterrupt:
        print('pymk: interrupt')
        sys.exit(130)
