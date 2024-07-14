from pathlib import Path
from typing import ForwardRef, TypeAlias
from .load_utils import with_possible_ext

DraconLoader = ForwardRef('DraconLoader')

def read_from_file(path: str, extra_paths=None):
    all_paths = with_possible_ext(path)
    if not extra_paths:
        extra_paths = []

    extra_path = [Path('./')] + [Path(p) for p in extra_paths]

    for ep in extra_path:
        for p in all_paths:
            p = ep / p
            if Path(p).exists():
                path = p.as_posix()
                break

    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f'File not found: {path}')

    with open(p, 'r') as f:
        raw = f.read()
    return raw


def compose_from_file(path: str, loader: DraconLoader, extra_paths=None):
    return loader.compose_config_from_str(read_from_file(path, extra_paths))

