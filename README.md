# pymk - a make-inspired python library and build system
> What if your build system was just a Python script?

While `make` certainly is powerful, it's syntax and odd quirks makes it a pain to scale to larger projects and confusing for new developers.

`pymk` is just a Python library.

You write your entire build system as a Python script which defines your targets and dependencies, and `pymk` builds your targets efficiently. This means defining special logic, which eventually always happens as your project becomes more complicated, means just writing regular Python code. No bash, no unintuitive string handling in make, no new made-up programming language that sucks, and no godawful what-ever CMake tries to be. Just Python.

Like `make`, `pymk` only rebuilds what it has to and implements the same up-to-date check algorithm as `make`.

## Example
What would this look like for a simple C project?

```python
#!/usr/bin/python3
import pymk
from pymk import Target, PhonyTarget
from pathlib import Path
from os import chdir

BUILD_DIR = Path('out')
if build_dir := pymk.get_variable('BUILD_DIR'):
    BUILD_DIR = Path(build_dir).resolve()
BUILD_DIR.mkdir(exist_ok=True)
chdir(Path(__file__).parent)

pymk.set_variable(
    CC='clang',
    CFLAGS='-std=c11 -O3 -Wall -Wextra -Werror',
)

def obj_target(c_file: Path) -> Target:
    return Target(
        cmd='$CC $CFLAGS -c $SRC -o $OUTPUT',
        depends={'SRC': c_file},
        output=BUILD_DIR / c_file.name.replace('.c', '.o'),
    )

objs = [obj_target(c_file) for c_file in Path('src').glob('*.c')]
executable = Target(
    cmd='$CC $CFLAGS $OBJS -o $OUTPUT',
    depends={'OBJS': objs},
    output=BUILD_DIR / 'binary',
)

def lint_file(f: Path) -> PhonyTarget:
    return PhonyTarget(name=f'lint-{f}', cmd=f'clang-tidy {f} -- -std=c11')

lint_all = [lint_file(f) for f in Path('.').glob('**/*.[ch]')]

pymk.main([
    PhonyTarget('build', help='Build binary',      depends=executable),
    PhonyTarget('lint',  help='Lint source files', depends=lint_all),
])
```

You would build the project with simply:
```bash
./mk.py build                         # build everything
./mk.py lint                          # lint everything
./mk.py build -DBUILD_DIR=/tmp/build  # set a different build dir
```

`pymk` automatically generates the help message for you:

```
$ ./mk.py
usage: ./mk.py [-h] [-j [JOBS]] [-DVAR[=VALUE]] TARGET..

TARGET:
  build  Build binary
  lint   Lint source files

OPTIONS:
  -j, --jobs JOBS        number of parallel jobs (default 0=infinite)
  -D, --var VAR[=VALUE]  set a variable, example -DCC=gcc-11
  -h, --help             print this help message and exit
```

---

Need to select a different compiler based on the OS? Just write some damn Python code:

```python
if sys.platform == 'win32':
    CC = 'cl.exe'
    CFLAGS = '/std:c11 /O3 /W4'
else:
    CC = 'gcc'
    CFLAGS = '-std=c11 -O3 -Wall -Wextra -Werror'
pymk.set_variable(CC=CC, CFLAGS=CFLAGS)
```
