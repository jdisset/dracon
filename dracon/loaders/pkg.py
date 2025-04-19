from .load_utils import with_possible_ext
import time
from importlib.resources import files, as_file
from typing import ForwardRef, Optional
from pathlib import Path
from cachetools import cached, LRUCache
from cachetools.keys import hashkey

DraconLoader = ForwardRef('DraconLoader')


@cached(LRUCache(maxsize=50))
def read_from_pkg_cached(*args, **kwargs):
    return read_from_pkg(*args, **kwargs)


def read_from_pkg(path: str):
    pkg = None

    if ':' in path:
        pkg, path = path.split(':', maxsplit=1)

    if not pkg:
        raise ValueError('No package specified in path')

    all_paths = with_possible_ext(path)

    for fpath in all_paths:
        try:
            with as_file(files(pkg) / fpath.as_posix()) as p:
                now = time.time()
                with open(p, 'r') as f:
                    pp = Path(p).resolve().absolute()
                    new_context = {
                        '$DIR': pp.parent.as_posix(),
                        '$FILE': pp.as_posix(),
                        '$FILE_PATH': pp.as_posix(),
                        '$FILE_STEM': pp.stem,
                        '$FILE_EXT': pp.suffix,
                        '$FILE_LOAD_TIME': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(now)),
                        '$FILE_LOAD_TIME_UNIX': int(now),
                        '$FILE_LOAD_TIME_UNIX_MS': int(now * 1000),
                        '$FILE_SIZE': pp.stat().st_size,
                        '$PACKAGE_NAME': pkg,
                    }

                    return f.read(), new_context
        except FileNotFoundError:
            pass

    # it failed
    tried_files = [str(files(pkg) / p.as_posix()) for p in all_paths]
    tried_str = '\n'.join(tried_files)
    resources = [resource.name for resource in files(pkg).iterdir() if not resource.is_file()]
    resources_str = '\n  - '.join(resources)
    raise FileNotFoundError(
        f'''File not found in package {pkg}: {path}. Tried: {tried_str}.
        Package root: {files(pkg)}
        Available subdirs:
        - {resources_str}'''
    )
