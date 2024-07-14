from .load_utils import with_possible_ext
from importlib.resources import files, as_file
from typing import ForwardRef

DraconLoader = ForwardRef('DraconLoader')


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
                with open(p, 'r') as f:
                    return f.read()
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


def compose_from_pkg(path: str, loader: DraconLoader):
    return loader.compose_config_from_str(read_from_pkg(path))
