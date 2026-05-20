# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Jean Disset
from pathlib import Path
from .load_utils import with_possible_ext, make_file_context


def read_from_file(path: str, extra_paths=None, **_) -> tuple[str, dict]:
    all_paths = with_possible_ext(path)
    search_roots = [Path('./')] + [Path(p) for p in (extra_paths or [])]

    found = None
    for ep in search_roots:
        for cand in all_paths:
            resolved = (ep / cand).expanduser().resolve()
            if resolved.exists():
                found = resolved
                break
        if found:
            break

    if found is None:
        raise FileNotFoundError(f'File not found: {path}')

    with open(found, 'r') as f:
        raw = f.read()

    return raw, make_file_context(found)
