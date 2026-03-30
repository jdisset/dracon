from pathlib import Path
from typing import Optional

from dracon.loaders.load_utils import with_possible_ext

DEFAULT_CASCADE_MERGE_KEY = "<<{<+}[<~]"


def find_cascade_files(
    relative_path: str, start_dir: Optional[Path] = None
) -> list[Path]:
    """Walk up from start_dir toward root, collecting all files matching relative_path.

    Returns files in root-first order (furthest ancestor first, closest last)
    so that sequential merging gives closest = highest priority.
    """
    p = Path(relative_path).expanduser()
    if p.is_absolute():
        raise ValueError(
            f"cascade requires a relative path, got absolute: {relative_path}"
        )

    start = (start_dir or Path.cwd()).resolve()
    candidates_by_ext = with_possible_ext(str(p))
    found = []
    current = start

    while True:
        for candidate in candidates_by_ext:
            full = current / candidate
            if full.is_file():
                found.append(full.resolve())
                break  # one match per directory level
        parent = current.parent
        if parent == current:
            break
        current = parent

    found.reverse()
    return found


def _parse_cascade_path(path_str: str) -> tuple[str, str]:
    """Parse optional merge key prefix from a cascade path string.

    If path_str starts with { or [, extract the merge key spec up to the
    last closing bracket, expect ':' separator, then the file path.
    Returns (merge_key_raw, file_path).
    """
    if not path_str or path_str[0] not in ('{', '['):
        return DEFAULT_CASCADE_MERGE_KEY, path_str

    bracket_depth = 0
    end_idx = 0
    for i, ch in enumerate(path_str):
        if ch in ('{', '['):
            bracket_depth += 1
        elif ch in ('}', ']'):
            bracket_depth -= 1
            if bracket_depth == 0:
                end_idx = i + 1
        elif ch == ':' and bracket_depth == 0:
            break

    merge_spec = path_str[:end_idx]
    rest = path_str[end_idx:]
    if rest.startswith(':'):
        rest = rest[1:]

    return f"<<{merge_spec}", rest


def read_cascade(path_str: str, node=None, draconloader=None, **_):
    """Cascade loader: find all matching files walking up the directory tree,
    compose each, merge them root-first (closest = highest priority).
    """
    from dracon.include import compose_from_include_str
    from dracon.merge import cached_merge_key

    merge_key_raw, actual_path = _parse_cascade_path(path_str)
    files = find_cascade_files(actual_path)

    if not files:
        raise FileNotFoundError(
            f"cascade: no files matching '{actual_path}' found walking up from {Path.cwd()}"
        )

    if draconloader is not None:
        loader = draconloader.copy()
    else:
        from dracon.loader import DraconLoader
        loader = DraconLoader()

    mkey = cached_merge_key(merge_key_raw)

    base = compose_from_include_str(loader, f"file:{files[0]}", custom_loaders=loader.custom_loaders)
    for f in files[1:]:
        next_comp = compose_from_include_str(loader, f"file:{f}", custom_loaders=loader.custom_loaders)
        base = base.merged(next_comp, mkey)

    return base, dict(loader.context)
