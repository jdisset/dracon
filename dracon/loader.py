import re
from pathlib import Path
from typing import Optional, Dict, Any
from pydantic import BaseModel
from dracon.utils import dict_like

"""
    Dracon allows for including external configuration files in the YAML configuration files. The include paths can be specified in the following formats:
    pkg:pkg_name:config_path[@keypath]
    file:config_path[@keypath]

    @keypath is optional and is used to specify a subpath within the included dictionary.
    a path can be specified with or without the .yaml extension.

"""

class ConfPathLoader(BaseModel):

    def load_raw(self, path: str):
        raise NotImplementedError

    def with_yaml_ext(self, path: str) -> str:
        if not path.endswith('.yaml'):
            return path + '.yaml'
        return path


class FileConfPathLoader(ConfPathLoader):
    def load_raw(self, path: str):
        p = Path(self.with_yaml_ext(path)).expanduser().resolve()
        if not p.exists():
            raise FileNotFoundError(f'File not found: {p}')
        with open(p, 'r') as f:
            return f.read()


class PkgConfPathLoader(ConfPathLoader):
    def load_raw(self, path: str):
        import importlib.resources
        from importlib.resources import files, as_file

        pkg = __name__
        if ':' in path:
            pkg, path = path.split(':', 1)

        fpath = self.with_yaml_ext(path)
        try:
            with as_file(files(pkg) / fpath) as p:
                with open(p, 'r') as f:
                    return f.read()
        except FileNotFoundError:
            raise FileNotFoundError(f'File not found in package {pkg}: {fpath}')


def load_raw_conf_str(path: str, escape_keys=None) -> str:
    ctype = 'file'
    cpath = path
    raw_yaml = None
    if ':' in path:
        ctype, cpath = path.split(':', 1)
    if ctype == 'file':
        raw_yaml = FileConfPathLoader().load_raw(cpath)
    elif ctype == 'pkg':
        raw_yaml = PkgConfPathLoader().load_raw(cpath)
    else:
        raise ValueError(f'Unknown include type: {ctype}')
    if escape_keys:

        def replace_merge(match):
            return match.group(0).replace(match.group(1), '"' + match.group(1) + '"')

        for key in escape_keys:
            pattern = re.compile(r'^\s*(' + key + r')\s*:\s*$', re.MULTILINE)
            raw_yaml = pattern.sub(replace_merge, raw_yaml)
    return raw_yaml


class IncludePath(BaseModel):
    path: str
    subpath: Optional[str] = None

    def model_post_init(self, *args, **kwargs):
        super().model_post_init(*args, **kwargs)
        if '@' in self.path:
            assert self.path.count('@') == 1, 'Only one @ is allowed in include path'
            self.path, self.subpath = self.path.split('@', 1)


