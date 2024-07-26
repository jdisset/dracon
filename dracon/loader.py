## {{{                          --     imports     --
from ruamel.yaml import YAML
from typing import Type, Callable
import inspect
import re
from pathlib import Path
from typing import Optional, Dict, Any, Annotated, TypeVar
from pydantic import BaseModel, BeforeValidator, Field, PlainSerializer
from dracon.composer import IncludeNode, CompositionResult, DraconComposer
from dracon.draconstructor import Draconstructor
from dracon.keypath import KeyPath, ROOTPATH
from dracon.utils import node_print, collect_all_types, DictLike, MetadataDictLike, ListLike
from dracon.merge import process_merges
from dracon.loaders.file import read_from_file
from dracon.loaders.pkg import read_from_pkg
from dracon.loaders.env import read_from_env
from dracon.representer import DraconRepresenter
from dracon import dracontainer

##────────────────────────────────────────────────────────────────────────────}}}

## {{{                       --     doc     --
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

## {{{                       --     DraconLoader     --


DEFAULT_LOADERS: Dict[str, Callable] = {
    'file': read_from_file,
    'pkg': read_from_pkg,
    'env': read_from_env,
}

DEFAULT_MODULES_FOR_TYPES = [
    'pydantic',
    'typing',
    'dracon',
    'numpy',
]


class DraconLoader:
    def __init__(
        self,
        custom_loaders: Optional[Dict[str, Callable]] = None,
        custom_types: Optional[Dict[str, Type]] = None,
        capture_globals: bool = True,
        base_dict_type: Type[DictLike] = dracontainer.Mapping,
        base_list_type: Type[ListLike] = dracontainer.Sequence,
        enable_interpolation: bool = False,
    ):
        self.custom_loaders = DEFAULT_LOADERS
        self.custom_loaders.update(custom_loaders or {})
        self.custom_types = custom_types or {}

        self.yaml = YAML()
        self.yaml.Composer = DraconComposer
        self.yaml.Constructor = Draconstructor
        self.yaml.Representer = DraconRepresenter
        self.yaml.composer.interpolation_enabled = enable_interpolation

        localns = collect_all_types(DEFAULT_MODULES_FOR_TYPES, capture_globals=capture_globals)
        self.yaml.constructor.localns = localns
        self.yaml.constructor.yaml_base_dict_type = base_dict_type

    def copy(self):
        return DraconLoader(self.custom_loaders)

    def compose_from_include_str(
        self,
        include_str: str,
        include_node_path: KeyPath = ROOTPATH,
        composition_result: Optional[CompositionResult] = None,
        custom_loaders: dict = DEFAULT_LOADERS,
    ) -> Any:
        if '@' in include_str:
            # split at the first unescaped @
            mainpath, keypath = re.split(r'(?<!\\)@', include_str, maxsplit=1)
        else:
            mainpath, keypath = include_str, ''

        if composition_result is not None:
            # it's a path starting with the root of the document
            if include_str.startswith('/'):
                return composition_result.rerooted(KeyPath(mainpath))

            # it's a path relative to the current node
            if include_str.startswith('@') or include_str.startswith(
                '.'
            ):  # means relative to parent
                comb_path = include_node_path.parent.down(KeyPath(mainpath))
                return composition_result.rerooted(comb_path)

            anchors = composition_result.anchor_paths
            if mainpath in anchors:
                return composition_result.rerooted(anchors[mainpath] + keypath)

            assert ':' in mainpath, f'Invalid include path: anchor {mainpath} not found in document'

        assert ':' in mainpath, f'Invalid include path: {mainpath}. No loader specified.'

        loader, path = mainpath.split(':', 1)
        if loader not in custom_loaders:
            raise ValueError(f'Unknown loader: {loader}')

        res = custom_loaders[loader](path)
        if not isinstance(res, CompositionResult):
            assert isinstance(res, str), f"Invalid loader result: {type(res)}"
            res = self.copy().compose_config_from_str(res)

        if keypath:
            res = res.rerooted(KeyPath(keypath))

        return res

    def compose_config_from_str(self, content: str) -> CompositionResult:
        self.yaml.compose(content)
        res = self.yaml.composer.get_result()
        return self.post_process_composed(res)

    def load_from_composition_result(self, compres: CompositionResult):
        return self.yaml.constructor.construct_document(compres.root)

    def load(self, config_path: str | Path):
        if isinstance(config_path, Path):
            config_path = config_path.resolve().as_posix()
        if ":" not in config_path:
            config_path = f"file:{config_path}"
        comp = self.compose_from_include_str(config_path)
        return self.load_from_composition_result(comp)

    def loads(self, content: str):
        comp = self.compose_config_from_str(content)
        return self.load_from_composition_result(comp)

    def post_process_composed(self, comp: CompositionResult):
        comp = self.process_includes(comp)
        comp = process_merges(comp)
        return comp

    def process_includes(self, comp_res: CompositionResult):
        while comp_res.include_nodes:
            inode_path = comp_res.include_nodes.pop()
            inode = inode_path.get_obj(comp_res.root)
            assert isinstance(inode, IncludeNode), f"Invalid node type: {type(inode)}"
            include_str = inode.value
            include_composed = self.compose_from_include_str(include_str, inode_path, comp_res)
            comp_res = comp_res.replaced_at(inode_path, include_composed)
        return comp_res


    def dump(self, data, stream=None):
        if stream is None:
            from io import StringIO

            string_stream = StringIO()
            self.yaml.dump(data, string_stream)
            return string_stream.getvalue()
        else:
            return self.yaml.dump(data, stream)


##────────────────────────────────────────────────────────────────────────────}}}


def load_config_to_dict(maybe_config: str | DictLike) -> DictLike:
    if isinstance(maybe_config, str):
        loader = DraconLoader()
        conf = loader.load(maybe_config)
        conf.set_metadata({'dracon_origin': maybe_config})
        return conf
    return maybe_config

T = TypeVar('T')

LoadedConfig = Annotated[
    T | str,
    BeforeValidator(load_config_to_dict),
    PlainSerializer(lambda x: serialize_loaded_config(x)),
    Field(validate_default=True),
]


def serialize_loaded_config(c: DictLike) -> str | DictLike:
    if isinstance(c, MetadataDictLike):
        origin = c.get_metadata().get('dracon_origin')
        if origin is not None:
            return origin
    return c


