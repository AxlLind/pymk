import re
import sys
import argparse
import subprocess
import concurrent.futures
from pathlib import Path
from typing import Sequence
from collections import defaultdict

class PymkException(Exception):
    pass

class Target:
    cmd: str
    output: Path
    depends: dict[str, list['Dependency']]

    def __init__(self, cmd: str, output: Path, depends: dict[str, 'Dependency' | Sequence['Dependency']]) -> None:
        self.cmd = cmd
        self.output = output
        self.depends = {k:list(v if isinstance(v,Sequence) else [v]) for k, v in depends.items()}

    def __str__(self) -> str:
        return str(self.output)

class PhonyTarget:
    name: str
    cmd: str | None
    depends: dict[str, list['Dependency']]

    def __init__(self, name: str, cmd: str | None = None, depends: dict[str, 'Dependency' | Sequence['Dependency']] = {}) -> None:
        self.name = name
        self.cmd = cmd
        self.depends = {k:list(v if isinstance(v,Sequence) else [v]) for k, v in depends.items()}

    def __str__(self) -> str:
        return self.name

TargetType = Target | PhonyTarget
Dependency = TargetType | Path

VARIABLES: dict[str, str] = {}
TARGETS: dict[str, PhonyTarget] = {}

VAR_SUBST_REGEX = re.compile(r'\$(\$|[A-Za-z0-9]+)')

def substitute_vars(var_maps: list[dict[str, str]], s: str) -> str:
    def get_variable(m: re.Match[str]) -> str:
        var = m.group(1)
        if var == '$':
            return '$'
        for var_map in var_maps:
            if val := var_map.get(var):
                return val
        raise PymkException(f'Unset variable "${var}"')

    return VAR_SUBST_REGEX.sub(get_variable, s)

def expand_cmd(t: TargetType) -> str:
    assert t.cmd
    var_maps = [{k:' '.join(str(x) for x in v) for k,v in t.depends.items()}, VARIABLES]
    return substitute_vars(var_maps, t.cmd)

def execute_command(cmd: str) -> int:
    print(cmd)
    return subprocess.run('bash', input=cmd.encode('utf-8')).returncode

def set_variable(**variables: str) -> None:
    VARIABLES.update(variables)

def register_targets(*targets: PhonyTarget) -> None:
    for target in targets:
        if target.name in TARGETS:
            raise PymkException(f'Target "{target.name}" defined multiple times')
        TARGETS[target.name] = target

def build_execution_dag(targets: list[str]) -> tuple[list[Dependency], dict[str | Path, set[TargetType]]]:
    leafs: list[Dependency] = []
    dag: defaultdict[str | Path, set[Dependency]] = defaultdict(set)
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
            exitcode = execute_command(expand_cmd(target))
            if exitcode != 0:
                raise PymkException(f'Target "{target.output}" failed. ({exitcode=})')
        case PhonyTarget():
            if target.cmd:
                exitcode = execute_command(expand_cmd(target))
                if exitcode != 0:
                    raise PymkException(f'Target "{target.name}" failed. ({exitcode=})')
    return target

def execute_targets(jobs: int, targets: list[str]) -> None:
    leafs, exec_dag = build_execution_dag(targets)

    deps_left: dict[TargetType, int] = {}
    with concurrent.futures.ProcessPoolExecutor(max_workers=jobs if jobs > 0 else None) as executor:
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
