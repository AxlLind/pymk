import argparse
import subprocess
import re
from pathlib import Path
from typing import Sequence
from collections import defaultdict, deque

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
        raise Exception(f'Tried to replace unset variable "${var}"')

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
            raise Exception(f'Target "{target.name}" defined multiple times')
        TARGETS[target.name] = target

def build_execution_dag(targets: list[str]) -> tuple[list[Dependency], dict[str | Path, set[Dependency]]]:
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

def run_target(target: Dependency) -> None:
    match target:
        case Path():
            if not target.exists():
                raise Exception(f'File dependency "{target}" does not exist.')
        case Target():
            exitcode = execute_command(expand_cmd(target))
            if exitcode != 0:
                raise Exception(f'Target "{target.output}" failed. ({exitcode=})')
        case PhonyTarget():
            if not target.cmd:
                return
            exitcode = execute_command(expand_cmd(target))
            if exitcode != 0:
                raise Exception(f'Target "{target.name}" failed. ({exitcode=})')

def run() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('targets', nargs='+', choices=list(TARGETS.keys()))
    opts = parser.parse_args()

    leafs, exec_dag = build_execution_dag(opts.targets)
    print([str(l) for l in leafs])

    m: dict[TargetType, int] = {}
    queue = deque(leafs)
    while queue:
        t = queue.pop()
        run_target(t)
        for dependant in exec_dag.get(str(t), set()):
            assert not isinstance(dependant, Path)
            if dependant not in m:
                m[dependant] = sum(len(x) for x in dependant.depends.values())
            m[dependant] -= 1
            if not m[dependant]:
                queue.append(dependant)
