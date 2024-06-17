## {{{                          --     import     --
import hydra
from omegaconf import OmegaConf
from hydra import compose, initialize, initialize_config_dir
from hydra.core.plugins import Plugins
from hydra.core.config_search_path import ConfigSearchPath
from hydra.plugins.search_path_plugin import SearchPathPlugin
from hydra.core.global_hydra import GlobalHydra

from pathlib import Path
from typing import List, Optional, Dict
import re
import yaml
from pydantic import BaseModel

##────────────────────────────────────────────────────────────────────────────}}}

## {{{                          --     loaders     --
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


DEFAULT_ESCAPE_KEYS = ['<<']


def load_raw_conf(path: str, escape_keys=None) -> str:
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


class IncludeMatch(BaseModel):
    path: str
    start: int
    end: int
    name: Optional[str] = None
    subpath: Optional[str] = None

    def model_post_init(self, *args, **kwargs):
        super().model_post_init(*args, **kwargs)
        if '@' in self.path:
            assert self.path.count('@') == 1, 'Only one @ is allowed in include path'
            self.path, self.subpath = self.path.split('@', 1)


def collect_includes(content, include_markers=':/') -> List[IncludeMatch]:
    include_pattern = re.compile(r'(?<!["\'])\*([a-zA-Z0-9_@/:\-\.]+)')
    return [
        IncludeMatch(path=match.group(1), start=match.start() + 1, end=match.end())
        for match in include_pattern.finditer(content)
        if any([c in match.group(1) for c in include_markers])
    ]


def with_indent(content: str, indent: int) -> str:
    return '\n'.join([f'{" " * indent}{line}' for line in content.split('\n')])


def make_anchor_str(anchors: Dict[str, str]):
    def single(i, alias, raw):
        return f'{i}: &{alias}\n{with_indent(raw, 2)}'

    all_anchors = '\n'.join(
        [single(i, alias, raw) for i, (alias, raw) in enumerate(anchors.items())]
    )
    final = ''
    if all_anchors:
        final = f'__dracon__anchors:\n{with_indent(all_anchors, 2)}'
    return final

def load_conf(path: str) -> str:
    raw = load_raw_conf(path)
    include_matches = collect_includes(raw)
    offset = 0
    anchors = {}

    for include in include_matches:
        inner_raw = load_conf(include.path)
        if include.subpath:
            loaded = yaml.safe_load(inner_raw)
            inner_loaded = obj_resolver(loaded, include.subpath)
            inner_raw = yaml.dump(inner_loaded)

        alias = '__dracon__' + get_hash(inner_raw + include.path)
        anchors[alias] = inner_raw

        raw = raw[: include.start + offset] + alias + raw[include.end + offset :]
        offset += len(alias) - (include.end - include.start)

    final_raw = make_anchor_str(anchors) + f'\n{raw}'

    loaded = yaml.safe_load(final_raw)
    if '__dracon__anchors' in loaded:
        del loaded['__dracon__anchors']

    return yaml.dump(loaded)




##────────────────────────────────────────────────────────────────────────────}}}

class BiocompSearchPathPlugin(SearchPathPlugin):
    def manipulate_search_path(self, search_path: ConfigSearchPath) -> None:
        search_path.append(provider="biocomptools", path="pkg://biocomptools/configs")


Plugins.instance().register(BiocompSearchPathPlugin)


def reset_hydra(config_dir=None):
    GlobalHydra.instance().clear()
    if config_dir is not None:
        config_dir_path = Path(config_dir).expanduser().resolve().absolute()
        print(f'Initializing hydra with config dir {config_dir_path}')
        # make absolute:
        assert config_dir_path.exists()
        assert config_dir_path.is_dir()
        initialize_config_dir(config_dir=config_dir, version_base="1.3")
    else:
        initialize(version_base="1.3")


def load_config(cfgname: str, config_dir=None, without_parent_context=True, resolved=False):
    reset_hydra(config_dir=config_dir)
    cfg = compose(config_name=cfgname)

    if without_parent_context:
        # if we have a cfgname that's actually a path, the final config will be nested
        # in a parent context. This is not always what we want.
        ppath = cfgname.split('/')
        if len(ppath) > 1:
            for p in ppath[:-1]:
                cfg = cfg[p]
        cfg = OmegaConf.create(cfg)

    if resolved:
        cfg = OmegaConf.to_container(cfg, resolve=True)
        assert isinstance(cfg, dict)

    return cfg


def load_config_file(cfg_file: str | Path, config_dir=None, use_containing_dir=True):
    cfg_file_path = Path(cfg_file).expanduser().resolve().absolute()
    if not cfg_file_path.exists():
        raise ValueError(f'Config file {cfg_file_path} does not exist')
    file_dir = Path(cfg_file_path).parent.resolve().absolute().as_posix()

    cfgdir = file_dir if use_containing_dir else config_dir

    return load_config(cfgname=str(cfg_file_path.stem), config_dir=cfgdir)
