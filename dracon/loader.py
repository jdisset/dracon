## {{{                       --     imports & doc     --
from ruamel.yaml import YAML
import os
from typing import Type
import importlib.resources
from importlib.resources import files, as_file
from pathlib import Path
from typing import Optional, Dict, Any
from pydantic import BaseModel
from dracon.utils import dict_like, get_obj_at_keypath
from dracon.merge import perform_merges
from dracon.composer import IncludeNode, DraconComposer
import importlib.resources
from importlib.resources import files, as_file

"""
    Dracon allows for including external configuration files in the YAML configuration files.
    Dracon provides 3 default loaders:

    pkg: for including files from a python package
    file: for including files from the filesystem
    env: for including environment variables

    special loaders (no need for ':'):
    / root of the current document
    @ current scope
    ..(n) parent scope (n times)

    syntax:
    loader:[path:][@key.path]

    a path can be specified with or without the .yaml extension.

    @key.path is optional and is used to specify a subpath within the included dictionary.
    in a keypath, dot notation is used to specify the path to the key within the dictionary.

    When an include references another included item, we build a tree of dependencies and resolve them in topological order (bottom-up).

    In theory, even though it's most likely a bad idea, nothing prevents you from defining anchors that have ambiguous names (names that look like loader paths, that start with '/', '.' or '@' or contain ':' ).
    Existing regular anchors will take precedence over the special loader paths.

    ## examples:

    ```
    default_settings:
        setting1: default_value1
        dict2: &alias
            subkey1: value1
        from_pkg: &pkgalias
            <<: *pkg:dracon:tests/configs/params # using the merge syntax (would be the same to directly include as value)
        from_file: *file:./configs/params.yaml@subkey1 # include the value of subkey1 from the file (uses a relative path to the current file)
        from_file: *file:use_executable_path:./configs/params.yaml@subkey1 # include the value of subkey1 from the file (uses a relative path to the executing script)

    settings:

        # @ and leading . mean local parent scope. Both can be omitted (but be careful with name collisions if you have aliases that use these characters)
        # / means root of the current document
        # extra dots mean going up in the hierarchy

        - */default_settings.setting1 # will include default_value1
        - */.@.@.default_settings.setting1 # same
        - *..default_settings.setting1 # same


        - *@0 # will repeat the first item of this list (scope of @ is the current obj) (first dot is implicit)
        - *.0 # same

        - *.1 # will repeat the second item of this list after it is resolved, i.e it'll be default_value1

        - *env:HOME # include the value of the HOME environment variable

        - *alias # dumps the entire dict2 (the "vanilla" alias behavior)
        - *alias@ # same
        - *alias@subkey1 # dumps value1
        - *alias@.subkey1 # same
        # !!!! - *alias.subkey1 WON'T WORK as you expect. It'll just be interpreted as an anchor name. You need to use @ to specify a subpath.

        - *alias@/default_settings.setting1 # dumps default_value1. Syntaxically valid but not very useful
        - *alias@..setting1 # same but using relative path to &alias

        - *pkgalias # dumps the entire dict from the package

    ```

"""


##────────────────────────────────────────────────────────────────────────────}}}


class IncludeAlias(BaseModel):
    mainpath: str
    keypath: Optional[str] = None

    def model_post_init(self, *args, **kwargs):
        super().model_post_init(*args, **kwargs)
        if '@' in self.mainpath:
            assert self.mainpath.count('@') == 1, 'Only one @ is allowed in include path'
            self.mainpath, self.keypath = self.mainpath.split('@', 1)


def with_possible_ext(path: str):
    # return: the original, with .yaml, with .yml, without extension. in that order
    p = Path(path)
    return [p, p.with_suffix('.yaml'), p.with_suffix('.yml'), p.with_suffix('')]


def load_from_file(path: str, extra_paths=None):
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
    return load_config_from_str(raw)


def load_from_pkg(path: str):
    pkg = __name__

    if ':' in path:
        pkg, path = path.split(':', 1)

    all_paths = with_possible_ext(path)

    for fpath in all_paths:
        try:
            with as_file(files(pkg) / fpath.as_posix()) as p:
                with open(p, 'r') as f:
                    return load_config_from_str(f.read())
        except FileNotFoundError:
            pass

    raise FileNotFoundError(f'File not found in package {pkg}: {path}')


def load_from_env(path: str):
    return os.getenv(path)


DEFAULT_LOADERS = {
    'file': load_from_file,
    'pkg': load_from_pkg,
    'env': load_from_env,
}


def load_from_include_str(
    include_str: str,
    path_to_node: str,
    conf_obj: Any,
    anchors=None,
    custom_loaders: dict = DEFAULT_LOADERS,
) -> Any:

    if anchors is None:
        anchors = {}


    # Handle special cases for relative paths
    if include_str.startswith('/'):
        return get_obj_at_keypath(conf_obj, include_str)

    if include_str.startswith('@') or include_str.startswith('.'):
        print('path_to_node:', path_to_node)
        current_obj = get_obj_at_keypath(conf_obj, path_to_node)
        return get_obj_at_keypath(current_obj, include_str[1:])

    if '@' in include_str:
        mainpath, keypath = include_str.split('@', 1)
    else:
        mainpath, keypath = include_str, ''

    if mainpath in anchors:
        refpath = anchors[mainpath]
        obj = get_obj_at_keypath(conf_obj, refpath)
        return get_obj_at_keypath(obj, keypath)

    assert ':' in mainpath, f'Invalid include path: anchor {mainpath} not found'

    loader, path = mainpath.split(':', 1)
    if loader not in custom_loaders:
        raise ValueError(f'Unknown loader: {loader}')

    obj = custom_loaders[loader](path)
    return get_obj_at_keypath(obj, keypath)



def resolve_includes(conf_node, full_conf, anchor_paths=None):

    if dict_like(conf_node):
        return {k: resolve_includes(v, full_conf, anchor_paths) for k, v in conf_node.items()}

    if isinstance(conf_node, list):
        return [resolve_includes(v, full_conf, anchor_paths) for v in conf_node]

    if hasattr(conf_node, 'tag') and conf_node.tag == 'dracon_include':
        include_str = conf_node.anchor.value
        keypath = conf_node.value
        print('include_str:', include_str)
        return load_from_include_str(include_str, keypath, full_conf, anchor_paths)

    return conf_node


def dracon_post_process(loaded, anchor_paths=None):
    loaded = resolve_includes(loaded, loaded, anchor_paths)
    loaded = perform_merges(loaded)
    return loaded


def load_config_from_str(content: str):
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.Composer = DraconComposer
    loaded_raw = yaml.load(content)
    anchor_paths = yaml.composer.anchor_paths
    return dracon_post_process(loaded_raw, anchor_paths)
