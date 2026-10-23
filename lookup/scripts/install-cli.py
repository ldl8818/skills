#!/usr/bin/env python3
"""Install one user-local command link. Existing unrelated commands are protected."""
from pathlib import Path


def install(home=None):
    source = Path(__file__).resolve().with_name('lookup')
    target = (Path(home) if home is not None else Path.home()) / '.local/bin/lookup'
    if target.is_symlink() or target.exists():
        if target.is_symlink() and target.resolve() == source:
            return target
        raise RuntimeError('LOOKUP_COMMAND_EXISTS: inspect its owner before replacing it')
    target.parent.mkdir(parents=True, exist_ok=True)
    target.symlink_to(source)
    return target


if __name__ == '__main__':
    print(install())
