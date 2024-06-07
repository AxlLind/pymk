import re
import sys
import argparse
import subprocess
import concurrent.futures
from pathlib import Path
from typing import Sequence, TypeAlias
from collections import defaultdict

TargetType:      TypeAlias = 'Target  | PhonyTarget'
Dependency:      TypeAlias = 'Target  | PhonyTarget | Path'
DependencyInput: TypeAlias = Dependency | Sequence[Dependency] | dict[str, Dependency | Sequence[Dependency]]

class PymkException(Exception):
    pass

def simplify_dependency_input(depends: DependencyInput) -> dict[str, list[Dependency]]:
    if isinstance(depends, dict):
        return {k:list(v if isinstance(v,Sequence) else [v]) for k, v in depends.items()}
    return {'__pymk_default_key__': list(depends) if isinstance(depends,Sequence) else [depends]}

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

VARIABLES: dict[str, str] = {}
TARGETS: dict[str, PhonyTarget] = {}

VAR_SUBST_REGEX = re.compile(r'\$(\$|[A-Za-z0-9]+)')

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

def execute_target_command(t: TargetType) -> None:
    cmd = expand_cmd(t)
    print(cmd)
    exitcode = subprocess.run('bash', input=cmd.encode('utf-8')).returncode
    if exitcode != 0:
        raise PymkException(f'Target "{t}" failed. ({exitcode=})')

def set_variable(**variables: str) -> None:
    VARIABLES.update(variables)

def register_targets(*targets: PhonyTarget) -> None:
    for target in targets:
        if target.name in TARGETS:
            raise PymkException(f'Target "{target.name}" defined multiple times')
        TARGETS[target.name] = target

def build_execution_dag(targets: list[str]) -> tuple[list[Dependency], dict[str | Path, set[TargetType]]]:
    leafs: list[Dependency] = []
    dag: defaultdict[str | Path, set[TargetType]] = defaultdict(set)
    seen: set[TargetType] = set()

    def add_dependencies(target: TargetType) -> None:
        if target in seen:
            return
        seen.add(target)
        if not target.depends:
            leafs.append(target)
            return
        for dependencies in target.depends.values():
            for t in dependencies:
                dag[str(t)].add(target)
                if isinstance(t, Path):
                    leafs.append(t)
                else:
                    add_dependencies(t)

    for t in targets:
        add_dependencies(TARGETS[t])
    return leafs, dict(dag)

def run_target(target: Dependency) -> Dependency:
    match target:
        case Path():
            if not target.exists():
                raise PymkException(f'File dependency "{target}" does not exist.')
        case Target():
            execute_target_command(target)
        case PhonyTarget():
            if target.cmd:
                execute_target_command(target)
    return target

def execute_targets(jobs: int, targets: list[str]) -> None:
    leafs, exec_dag = build_execution_dag(targets)

    deps_left: dict[TargetType, int] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs if jobs > 0 else None) as executor:
        left = set(executor.submit(run_target, leaf) for leaf in leafs)
        while left:
            done, left = concurrent.futures.wait(left, return_when=concurrent.futures.FIRST_COMPLETED)
            for f in done:
                t = f.result()
                for dependant in exec_dag.get(str(t), set()):
                    if dependant not in deps_left:
                        deps_left[dependant] = sum(len(x) for x in dependant.depends.values())
                    deps_left[dependant] -= 1
                    if not deps_left[dependant]:
                        left.add(executor.submit(run_target, dependant))

def run() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('-j', '--jobs', type=int, default=0, help='number of parallel jobs (0=infinite)')
    parser.add_argument('targets', nargs='+', choices=list(TARGETS.keys()))
    opts = parser.parse_args()
    try:
        execute_targets(opts.jobs, opts.targets)
    except PymkException as e:
        print(f'pymk failure: {e}')
        sys.exit(1)
