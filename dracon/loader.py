## {{{                          --     imports     --
from ruamel.yaml import YAML
from dracon.interpolation import resolve_interpolable_variables
from typing import Type, Callable
import os
import copy
import inspect
import re
from pathlib import Path
from typing import Optional, Dict, Any, Annotated, TypeVar
from pydantic import BaseModel, BeforeValidator, Field, PlainSerializer
from dracon.composer import IncludeNode, CompositionResult, DraconComposer, delete_unset_nodes
from dracon.draconstructor import Draconstructor
from dracon.keypath import KeyPath, ROOTPATH
from dracon.utils import (
    node_print,
    collect_all_types,
    DictLike,
    MetadataDictLike,
    ListLike,
    generate_unique_id,
)
from dracon.merge import process_merges
from dracon.loaders.file import read_from_file
from dracon.nodes import InterpolableNode, MappingNode, SequenceNode
from dracon.loaders.pkg import read_from_pkg
from dracon.loaders.env import read_from_env
from dracon.interpolation import find_field_references
from dracon.representer import DraconRepresenter
from dracon import dracontainer
from copy import deepcopy

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


DEFAULT_CONTEXT = {
    # some SAFE os functions (not all of them are safe)
    # need no side effects, and no access to the filesystem
    'getenv': os.getenv,
    'environ': os.environ,
    'getcwd': os.getcwd,
    'listdir': os.listdir,
}


class DraconLoader:
    def __init__(
        self,
        custom_loaders: Optional[Dict[str, Callable]] = None,
        custom_types: Optional[Dict[str, Type]] = None,
        capture_globals: bool = True,
        base_dict_type: Type[DictLike] = dracontainer.Mapping,
        base_list_type: Type[ListLike] = dracontainer.Sequence,
        enable_interpolation: bool = False,
        interpolate_all: bool = False,
        context: Optional[Dict[str, Any]] = None,
    ):
        self.custom_loaders = DEFAULT_LOADERS
        self.custom_loaders.update(custom_loaders or {})
        self.custom_types = custom_types or {}

        self.yaml = YAML()
        self.yaml.Composer = DraconComposer
        self.yaml.Constructor = Draconstructor
        self.yaml.Representer = DraconRepresenter

        self.reset_context()
        self.update_context(context or {})

        self.yaml.constructor.drloader = self
        self.yaml.constructor.context.update(self.context)
        self.yaml.constructor.interpolate_all = interpolate_all
        self.yaml.composer.interpolation_enabled = enable_interpolation

        localns = collect_all_types(
            DEFAULT_MODULES_FOR_TYPES,
            capture_globals=capture_globals,
        )
        localns.update(self.custom_types)
        self.yaml.constructor.localns = localns
        self.yaml.constructor.yaml_base_dict_type = base_dict_type

    def reset_context(self):
        self.context: Dict[str, Any] = {
            **DEFAULT_CONTEXT,
            'load': self.load,
        }

    def update_context(self, kwargs):
        # make sure it's created if it doesn't exist
        self.context.update(kwargs)

    def copy(self):
        new_loader = DraconLoader(
            custom_loaders=self.custom_loaders,
            custom_types=self.custom_types,
            capture_globals=False,
            base_dict_type=self.yaml.constructor.yaml_base_dict_type,
            base_list_type=self.yaml.constructor.yaml_base_list_type,
            enable_interpolation=self.yaml.composer.interpolation_enabled,
            context=deepcopy(self.context),
        )
        new_loader.yaml.constructor.yaml_constructors = copy.deepcopy(
            self.yaml.constructor.yaml_constructors
        )
        return new_loader

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

        res = custom_loaders[loader](path, loader=self)
        if not isinstance(res, CompositionResult):
            assert isinstance(res, str), f"Invalid loader result: {type(res)}"
            res = self.copy().compose_config_from_str(res)

        if keypath:
            res = res.rerooted(KeyPath(keypath))

        return res

    def compose_config_from_str(self, content: str) -> CompositionResult:
        self.yaml.compose(content)
        assert isinstance(self.yaml.composer, DraconComposer)
        res = self.yaml.composer.get_result()
        return self.post_process_composed(res)

    def load_from_composition_result(self, compres: CompositionResult):
        self.yaml.constructor.context.update(self.context)
        return self.yaml.constructor.construct_document(compres.root)

    def load(self, config_path: str | Path):
        self.reset_context()
        if isinstance(config_path, Path):
            config_path = config_path.resolve().as_posix()
        if ":" not in config_path:
            config_path = f"file:{config_path}"
        comp = self.compose_from_include_str(config_path)
        return self.load_from_composition_result(comp)

    def loads(self, content: str):
        self.reset_context()
        comp = self.compose_config_from_str(content)
        return self.load_from_composition_result(comp)

    def post_process_composed(self, comp: CompositionResult):
        comp = self.process_includes(comp)
        comp = process_merges(comp)
        comp = self.process_ampersand_references(comp)
        comp = delete_unset_nodes(comp)
        return comp

    def process_ampersand_references(self, comp_res: CompositionResult):
        """
        Find references in InterpolableNodes and replace them with copies of the target nodes.
        """

        def walk_node(node, current_path):
            if isinstance(node, InterpolableNode):
                node.preprosess_ampersand_references(comp_res, current_path)
            elif isinstance(node, MappingNode):
                for key_node, value_node in node.value:
                    walk_node(key_node, current_path)
                    walk_node(value_node, current_path + KeyPath(key_node.value))
            elif isinstance(node, SequenceNode):
                for idx, item_node in enumerate(node.value):
                    walk_node(item_node, current_path + KeyPath(str(idx)))

        walk_node(comp_res.root, ROOTPATH)
        return comp_res

    def process_includes(self, comp_res: CompositionResult):
        while comp_res.include_nodes:
            inode_path = comp_res.include_nodes.pop()
            inode = inode_path.get_obj(comp_res.root)
            assert isinstance(inode, IncludeNode), f"Invalid node type: {type(inode)}"
            include_str = inode.value
            include_str = resolve_interpolable_variables(include_str, self.context)
            new_loader = self.copy()
            include_composed = new_loader.compose_from_include_str(
                include_str, inode_path, comp_res
            )
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

    def dump_to_node(self, data):
        return self.yaml.representer.represent_data(data)


##────────────────────────────────────────────────────────────────────────────}}}


def load(config_path: str | Path, raw_dict=False, **kwargs):
    loader = DraconLoader(**kwargs)
    if raw_dict:
        loader.yaml.constructor.yaml_base_dict_type = dict
    return loader.load(config_path)


def load_file(config_path: str | Path, raw_dict=True, **kwargs):
    # just prepend 'file:' to the path
    return load(f'file:{config_path}', raw_dict, **kwargs)


def loads(config_str: str, raw_dict=False, **kwargs):
    loader = DraconLoader(**kwargs)
    if raw_dict:
        loader.yaml.constructor.yaml_base_dict_type = dict
    return loader.loads(config_str)


def dump(data, stream=None, **kwargs):
    loader = DraconLoader(**kwargs)
    return loader.dump(data, stream)


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
