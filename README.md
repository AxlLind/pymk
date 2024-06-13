# pymk - a make-inspired python library and build system
> What if "make" was just a Python library and your build system was just a Python file?

While `make` certainly is powerful, it's syntax and odd quirks makes it a pain to scale to larger projects and confusing for new developers.

`pymk` is just a Python library.

You write your entire build system as a Python script which defines your targets and dependencies, and `pymk` builds your targets efficiently. This means defining special logic, which eventually always happens as your project becomes more complicated, means just writing regular Python code. No bash, no unintuitive string handling in make, no new made-up programming language that sucks, and no godawful what-ever CMake tries to be. Just Python.

## Example
What would this look like for a simple C project?

```python
#!/usr/bin/python3
import pymk
from pymk import Target, PhonyTarget
from pathlib import Path

BUILD_DIR = Path('out')
BUILD_DIR.mkdir(exist_ok=True)

pymk.set_variable(
    CC='clang',
    CFLAGS='-O3 -Wall -Wextra -Werror',
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
    depends={'OBJS': [objs]},
    output=BUILD_DIR / 'binary',
)

pymk.run([PhonyTarget('build', help='Build binary', depends=executable)])
```

You would build the project simply: `./build.py build`

Like `make`, `pymk` only rebuilds what it has to and implements the same up-to-date check algorithm as `make`.
