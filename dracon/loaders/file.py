from pathlib import Path
from typing import ForwardRef, TypeAlias
from .load_utils import with_possible_ext
from typing import Optional

from cachetools import cached, LRUCache
from cachetools.keys import hashkey
import time

DraconLoader = ForwardRef('DraconLoader')


@cached(LRUCache(maxsize=1e6))
def read_from_file(path: str, extra_paths=None):
    """
    Reads the content of a file, searching in the specified path and additional paths if provided.

    Args:
        path (str): The primary path to the file.
        extra_paths (list, optional): Additional paths to search for the file. Defaults to None.
        loader (Optional[DraconLoader], optional): An optional loader to update context. Defaults to None.

    Returns:
        str: The content of the file.

    Raises:
        FileNotFoundError: If the file is not found in any of the specified paths.
    """
    all_paths = with_possible_ext(path)
    if not extra_paths:
        extra_paths = []

    extra_path = [Path('./')] + [Path(p) for p in extra_paths]

    for ep in extra_path:
        for p in all_paths:
            p = (ep / p).expanduser().resolve()
            if Path(p).exists():
                path = p.as_posix()
                break

    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f'File not found: {path}')

    with open(p, 'r') as f:
        raw = f.read()

    now = time.time()

    new_context = {
        '$DIR': p.parent.as_posix(),
        '$FILE': p.as_posix(),
        '$FILE_PATH': p.as_posix(),
        '$FILE_STEM': p.stem,
        '$FILE_EXT': p.suffix,
        '$FILE_LOAD_TIME': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(now)),
        '$FILE_LOAD_TIME_UNIX': int(now),
        '$FILE_LOAD_TIME_UNIX_MS': int(now * 1000),
        '$FILE_SIZE': p.stat().st_size,
    }

    return raw, new_context
