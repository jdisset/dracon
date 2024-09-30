## {{{                          --     imports     --
from ruamel.yaml import YAML, Node
from typing import Type, Callable
import os
import copy
import re
from pathlib import Path
from typing import Optional, Dict, Any, Annotated, TypeVar
from pydantic import BeforeValidator, Field, PlainSerializer
from dracon.composer import (
    IncludeNode,
    CompositionResult,
    DraconComposer,
    delete_unset_nodes,
    walk_node,
)
from dracon.draconstructor import Draconstructor
from dracon.keypath import KeyPath, ROOTPATH
from dracon.utils import (
    collect_all_types,
    DictLike,
    MetadataDictLike,
    ListLike,
    ShallowDict,
    ftrace,
)
from dracon.interpolation_utils import resolve_interpolable_variables
from dracon.interpolation import InterpolableNode
from dracon.merge import process_merges, add_to_context
from dracon.instructions import process_instructions
from dracon.loaders.file import read_from_file
from dracon.loaders.pkg import read_from_pkg
from dracon.loaders.env import read_from_env
from dracon.representer import DraconRepresenter
from dracon import dracontainer
from copy import deepcopy
from functools import partial


##────────────────────────────────────────────────────────────────────────────}}}

## {{{                       --     DraconLoader     --

DEFAULT_LOADERS: Dict[str, Callable] = {
    'file': read_from_file,
    'pkg': read_from_pkg,
    'env': read_from_env,
}

DEFAULT_MODULES_FOR_TYPES = [
    # 'pydantic',
    # 'typing',
    # 'dracon',
    # 'numpy',
]


DEFAULT_CONTEXT = {
    # some SAFE os functions (not all of them are safe)
    # need no side effects, and no access to the filesystem
    'getenv': os.getenv,
    'getcwd': os.getcwd,
}


@ftrace()
def construct(node_or_val, **kwargs):
    if isinstance(node_or_val, Node):
        loader = DraconLoader(**kwargs)
        compres = CompositionResult(root=deepcopy(node_or_val))
        return loader.load_from_composition_result(compres, post_process=True)

    return node_or_val


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
        self._context = context
        self._interpolate_all = interpolate_all
        self._enable_interpolation = enable_interpolation

        self.yaml = YAML()
        self.yaml.Composer = DraconComposer
        self.yaml.Constructor = Draconstructor
        self.yaml.Representer = DraconRepresenter

        self.yaml.constructor.resolve_interpolations = interpolate_all
        self.yaml.composer.interpolation_enabled = enable_interpolation

        localns = collect_all_types(
            DEFAULT_MODULES_FOR_TYPES,
            capture_globals=capture_globals,
        )
        localns.update(self.custom_types)
        self.yaml.constructor.localns = localns
        self.yaml.constructor.yaml_base_dict_type = base_dict_type
        self.reset_context()
        self.update_context(context or {})
        self.referenced_nodes = {}

    def reset_context(self):
        self.context: Dict[str, Any] = {
            **DEFAULT_CONTEXT,
            'load': load,  # from string or path to obj
            'construct': partial(  # from node to obj
                construct,
                custom_types=self.yaml.constructor.localns,
                context=self._context,
                interpolate_all=self._interpolate_all,
                enable_interpolation=self._enable_interpolation,
            ),
        }

    def update_context(self, kwargs):
        # make sure it's created if it doesn't exist
        self.context.update(kwargs)
        self.yaml.constructor.context.update(self.context)

    def copy(self):
        new_loader = DraconLoader(
            custom_loaders=self.custom_loaders,
            custom_types=self.custom_types,
            capture_globals=False,
            base_dict_type=self.yaml.constructor.yaml_base_dict_type,
            base_list_type=self.yaml.constructor.yaml_base_list_type,
            enable_interpolation=self.yaml.composer.interpolation_enabled,
            context=self.context.copy(),
        )
        new_loader.yaml.constructor.yaml_constructors = self.yaml.constructor.yaml_constructors

        return new_loader

    @ftrace(inputs=False, watch=[])
    def compose_from_include_str(
        self,
        include_str: str,
        include_node_path: KeyPath = ROOTPATH,
        composition_result: Optional[CompositionResult] = None,
        custom_loaders: dict = DEFAULT_LOADERS,
        node: Optional[IncludeNode] = None,
    ) -> Any:
        # TODO [medium priority]:
        # this resolve_interpolable_variables business is hacky and ugly.
        # It's just a find + replace of $VAR with the value of VAR
        # from the loader context (i.e. "./$FILE_STEM.png").
        # It's weirdly independent from the rest of the interpolation system,
        # and not even using the node.extra_symbols.
        # It's conflicting with the node include syntax (!include $var)
        # which does use the node.extra_symbols...
        # Need to clean this up, merge both (probably use comptime interpolation)
        # and make it consistent.

        include_str = resolve_interpolable_variables(include_str, self.context)

        res = None

        try:
            if '@' in include_str:
                # split at the first unescaped @
                mainpath, keypath = re.split(r'(?<!\\)@', include_str, maxsplit=1)
            else:
                mainpath, keypath = include_str, ''

            if composition_result is not None:
                if mainpath.startswith('$'):  # it's an in-memory node
                    if not node:
                        raise ValueError('Node not provided for in-memory include')
                    name = mainpath[1:]
                    if name in node.extra_symbols:
                        incl_node = node.extra_symbols[name]
                        incl_node = self.dump_to_node(incl_node)
                        if keypath:
                            incl_node = KeyPath(keypath).get_obj(incl_node)
                        res = CompositionResult(root=incl_node)
                        res.root = deepcopy(res.root)
                        return res

                    raise ValueError(f'Invalid in-memory include: {name} not found')

                # it's a path starting with the root of the document
                if include_str.startswith('/'):
                    res = composition_result.rerooted(KeyPath(mainpath))
                    res.root = deepcopy(res.root)
                    return res

                # it's a path relative to the current node
                if include_str.startswith('@') or include_str.startswith(
                    '.'
                ):  # means relative to parent
                    comb_path = include_node_path.parent.down(KeyPath(mainpath))
                    res = composition_result.rerooted(comb_path)
                    res.root = deepcopy(res.root)
                    return res

                anchors = composition_result.anchor_paths
                if mainpath in anchors:
                    res = composition_result.rerooted(anchors[mainpath] + keypath)
                    res.root = deepcopy(res.root)
                    return res

                assert (
                    ':' in mainpath
                ), f'Invalid include path: anchor {mainpath} not found in document'

            assert ':' in mainpath, f'Invalid include path: {mainpath}. No loader specified.'

            loader, path = mainpath.split(':', 1)
            if loader not in custom_loaders:
                raise ValueError(f'Unknown loader: {loader}')

            res = custom_loaders[loader](path, loader=self)
            if not isinstance(res, CompositionResult):
                if not isinstance(res, str):
                    raise ValueError(f"Invalid result type from loader '{loader}': {type(res)}")
                res = self.copy().compose_config_from_str(res)
            if keypath:
                res = res.rerooted(KeyPath(keypath))
            return res
        finally:
            if isinstance(res, CompositionResult) and node is not None:
                # we need to update the context of the composed documdeepcopy(res)
                # with the context of the loader that composed it
                walk_node(
                    node=res.root,
                    callback=partial(add_to_context, node.extra_symbols),
                )

    def compose_config_from_str(self, content: str) -> CompositionResult:
        self.yaml.compose(content)
        assert isinstance(self.yaml.composer, DraconComposer)
        res = self.yaml.composer.get_result()
        return self.post_process_composed(res)

    def load_from_node(self, node):
        self.yaml.constructor.context.update(self.context)
        return self.yaml.constructor.construct_document(node)

    def load_from_composition_result(self, compres: CompositionResult, post_process=True):
        if post_process:
            compres = self.post_process_composed(compres)
        return self.load_from_node(compres.root)

    def load(self, config_path: str | Path):
        self.reset_context()
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
        walk_node(
            node=comp.root,
            callback=partial(add_to_context, self.context),
        )
        comp = self.preprocess_references(comp)
        comp = process_instructions(comp)
        comp = self.process_includes(comp)
        comp = process_merges(comp)
        comp = delete_unset_nodes(comp)
        comp = self.save_references(comp)

        return comp

    @ftrace(inputs=False, watch=[])
    def preprocess_references(self, comp_res: CompositionResult):
        comp_res.find_special_nodes('interpolable', lambda n: isinstance(n, InterpolableNode))
        comp_res.sort_special_nodes('interpolable')

        for path in comp_res.pop_all_special('interpolable'):
            node = path.get_obj(comp_res.root)
            assert isinstance(node, InterpolableNode), f"Invalid node type: {type(node)}"
            node.preprocess_references(comp_res, path)

        return comp_res

    def save_references(self, comp_res: CompositionResult):
        # the preprocessed refernces are stored as paths that point to refered nodes
        # however, after all the merging and including is done, we need to save
        # the nodes themselves so that they can't be affected by further changes (e.g. construction)
        comp_res.find_special_nodes('interpolable', lambda n: isinstance(n, InterpolableNode))

        referenced_nodes = {}

        for path in comp_res.pop_all_special('interpolable'):
            node = path.get_obj(comp_res.root)
            assert isinstance(node, InterpolableNode), f"Invalid node type: {type(node)}"
            node.flush_references()
            for i, n in node.referenced_nodes.items():
                if i not in referenced_nodes:
                    referenced_nodes[i] = deepcopy(n)

        self.referenced_nodes = ShallowDict(referenced_nodes)
        # set the referenced nodes of the constructor:
        self.yaml.constructor.referenced_nodes = self.referenced_nodes

        return comp_res

    def process_includes(self, comp_res: CompositionResult):
        while True:  # we need to loop until there are no more includes (since some includes may bring other ones )
            comp_res.find_special_nodes('include', lambda n: isinstance(n, IncludeNode))
            if not comp_res.special_nodes['include']:
                break

            comp_res.sort_special_nodes('include')
            for inode_path in comp_res.pop_all_special('include'):
                inode = inode_path.get_obj(comp_res.root)
                assert isinstance(inode, IncludeNode), f"Invalid node type: {type(inode)}"
                new_loader = self.copy()
                include_composed = new_loader.compose_from_include_str(
                    inode.value, inode_path, comp_res, node=inode
                )
                comp_res.replace_node_at(inode_path, include_composed.root)

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
        if isinstance(data, Node):
            return data
        return self.yaml.representer.represent_data(data)


##────────────────────────────────────────────────────────────────────────────}}}


def load(config_path: str | Path, raw_dict=False, **kwargs):
    loader = DraconLoader(**kwargs)
    if raw_dict:
        loader.yaml.constructor.yaml_base_dict_type = dict
    return loader.load(config_path)


def load_node(node: Node, **kwargs):
    loader = DraconLoader(**kwargs)
    return loader.load_from_node(node)


def load_file(config_path: str | Path, raw_dict=True, **kwargs):
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
