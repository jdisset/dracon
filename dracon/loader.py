## {{{                          --     imports     --
from ruamel.yaml import Node
import os
from typing import Any, Callable, Dict, Optional, Type, Annotated, TypeVar
from functools import partial

from cachetools import cached, LRUCache
from cachetools.keys import hashkey
from pathlib import Path
from pydantic import BeforeValidator, Field, PlainSerializer

from dracon.include import DEFAULT_LOADERS, compose_from_include_str

from dracon.composer import (
    IncludeNode,
    CompositionResult,
    DraconComposer,
    delete_unset_nodes,
)

from dracon.draconstructor import Draconstructor
from dracon.keypath import KeyPath, ROOTPATH
from dracon.yaml import PicklableYAML

from dracon.utils import (
    DictLike,
    MetadataDictLike,
    ListLike,
    ShallowDict,
    ftrace,
    deepcopy,
    make_hashable,
    ser_debug,
    node_repr,
)

from dracon.interpolation import InterpolableNode, preprocess_references
from dracon.merge import process_merges, add_to_context, merged, MergeKey
from dracon.instructions import process_instructions
from dracon.deferred import DeferredNode, process_deferred
from dracon.representer import DraconRepresenter

from dracon.lazy import DraconError

from dracon import dracontainer


##────────────────────────────────────────────────────────────────────────────}}}

## {{{                       --     DraconLoader     --


DEFAULT_CONTEXT = {
    # some SAFE os functions (not all of them are safe)
    # need no side effects, and no access to the filesystem
    'getenv': os.getenv,
    'getcwd': os.getcwd,
}


def dillcopy(obj):
    import dill

    return dill.loads(dill.dumps(obj))


@ftrace()
def construct(node_or_val, **kwargs):
    if isinstance(node_or_val, Node):
        loader = DraconLoader(**kwargs)
        compres = CompositionResult(root=node_or_val)
        return loader.load_composition_result(compres, post_process=True)

    return node_or_val


class DraconLoader:
    def __init__(
        self,
        custom_loaders: Optional[Dict[str, Callable]] = None,
        capture_globals: bool = True,
        base_dict_type: Type[DictLike] = dracontainer.Mapping,
        base_list_type: Type[ListLike] = dracontainer.Sequence,
        enable_interpolation: bool = False,
        context: Optional[Dict[str, Any]] = None,
        deferred_paths: Optional[list[KeyPath | str]] = None,
    ):
        self.custom_loaders = DEFAULT_LOADERS.copy()
        self.custom_loaders.update(custom_loaders or {})
        self._capture_globals = capture_globals
        self._context_arg = context
        self._enable_interpolation = enable_interpolation
        self.referenced_nodes = {}
        self.deferred_paths = [KeyPath(p) for p in (deferred_paths or [])]
        self.base_dict_type = base_dict_type
        self.base_list_type = base_list_type

        self._init_yaml()

        self.context = (
            ShallowDict[str, Any](self._context_arg)
            if self._context_arg
            else ShallowDict[str, Any]()
        )
        self.yaml.constructor.context = self.context.copy()
        self.reset_context()

    def _init_yaml(self):
        self.yaml = PicklableYAML()
        self.yaml.Composer = DraconComposer
        self.yaml.Constructor = Draconstructor
        self.yaml.Representer = DraconRepresenter

        self.yaml.composer.interpolation_enabled = self._enable_interpolation
        self.yaml.constructor.yaml_base_dict_type = self.base_dict_type

    def reset_context(self):
        self.update_context(DEFAULT_CONTEXT)
        self.update_context(
            {
                'construct': partial(
                    construct,
                    custom_loaders=self.custom_loaders,
                    capture_globals=self._capture_globals,
                    enable_interpolation=self._enable_interpolation,
                    context=self.context,
                )
            }
        )

    def __hash__(self):
        return hash(
            (
                make_hashable(self.context),
                tuple(self.deferred_paths),
                self._enable_interpolation,
            )
        )

    @ftrace()
    def update_context(self, kwargs):
        add_to_context(kwargs, self)

    def copy(self):
        new_loader = DraconLoader(
            custom_loaders=self.custom_loaders.copy(),
            capture_globals=self._capture_globals,
            base_dict_type=self.base_dict_type,
            base_list_type=self.base_list_type,
            enable_interpolation=self._enable_interpolation,
            context=self.context.copy() if self.context else None,
        )
        new_loader.referenced_nodes = self.referenced_nodes.copy()
        new_loader.yaml.constructor.yaml_constructors = (
            self.yaml.constructor.yaml_constructors.copy()
        )
        return new_loader

    def __deepcopy__(self, memo):
        return self.copy()

    def __getstate__(self):
        state = self.__dict__.copy()
        return state

    def __setstate__(self, state):
        self.__dict__.update(state)

    @ftrace()
    def compose_config_from_str(self, content: str) -> CompositionResult:
        composed_content = cached_compose_config_from_str(self.yaml, content)
        return self.post_process_composed(composed_content)

    @ftrace()
    def load_node(self, node):
        try:
            self.yaml.constructor.referenced_nodes = self.referenced_nodes
            if self.yaml.constructor.context is None:
                self.yaml.constructor.context = self.context.copy() or {}
            return self.yaml.constructor.construct_document(node)
        except Exception as e:
            raise DraconError(f"Error loading node {node}") from e

    @ftrace()
    def load_composition_result(self, compres: CompositionResult, post_process=True):
        if post_process:
            compres = self.post_process_composed(compres)
        return self.load_node(compres.root)

    @ftrace()
    def load(self, config_path: str | Path):
        self.reset_context()
        if isinstance(config_path, Path):
            config_path = config_path.resolve().as_posix()
        if ":" not in config_path:
            config_path = f"file:{config_path}"
        comp = compose_from_include_str(self, config_path, custom_loaders=self.custom_loaders)
        return self.load_composition_result(comp)

    @ftrace()
    def loads(self, content: str):
        comp = self.compose_config_from_str(content)
        return self.load_composition_result(comp)

    @ftrace()
    def post_process_composed(self, comp: CompositionResult):
        ser_debug(self, operation='deepcopy')
        ser_debug(comp, operation='deepcopy')
        comp = preprocess_references(comp)
        comp = process_deferred(comp, force_deferred_at=self.deferred_paths)  # type: ignore
        comp.walk_no_path(
            callback=partial(add_to_context, self.context, merge_key=MergeKey(raw='{>~}[>~]'))
        )
        comp = self.update_deferred_nodes(comp)
        comp = process_instructions(comp, self)
        comp = self.process_includes(comp)
        comp, merge_changed = process_merges(comp)
        comp, delete_changed = delete_unset_nodes(comp)
        if merge_changed or delete_changed:
            comp.make_map()
        comp = self.save_references(comp)
        comp.update_paths()

        # one more round of processing deferred nodes to catch them at new paths
        comp = process_deferred(comp, force_deferred_at=self.deferred_paths)  # type: ignore
        comp = self.update_deferred_nodes(comp)
        comp.update_paths()

        return comp

    @ftrace()
    def update_deferred_nodes(self, comp_res: CompositionResult):
        # copies the loader into deferred nodes so they can resume their composition by themselves

        deferred_nodes = []

        def find_deferred_nodes(node: Node, path: KeyPath):
            if isinstance(node, DeferredNode):
                deferred_nodes.append((node, path))

        comp_res.walk(find_deferred_nodes)
        deferred_nodes = sorted(deferred_nodes, key=lambda x: len(x[1]), reverse=True)

        for node, _ in deferred_nodes:
            if node._loader is None:
                node._loader = self.copy()
            node._full_composition = comp_res
            if node._clear_ctx:
                for k in node._clear_ctx:
                    node.context.pop(k, None)
                    node._loader.context.pop(k, None)

        return comp_res

    @ftrace(watch=[])
    def save_references(self, comp_res: CompositionResult):
        # the preprocessed refernces are stored as paths that point to refered nodes
        # however, after all the merging and including is done, we need to save
        # the nodes themselves so that they can't be affected by further changes (e.g. construction)

        # TODO: should belong to CompositionResult, not the loader

        comp_res.find_special_nodes('interpolable', lambda n: isinstance(n, InterpolableNode))

        referenced_nodes = {}

        for path in comp_res.pop_all_special('interpolable'):
            node = path.get_obj(comp_res.root)
            assert isinstance(node, InterpolableNode), f"Invalid node type: {type(node)}"
            node.flush_references()
            for i, n in node.referenced_nodes.items():
                if i not in referenced_nodes:
                    referenced_nodes[i] = deepcopy(n)

        self.referenced_nodes = ShallowDict(
            merged(self.referenced_nodes, referenced_nodes, MergeKey(raw='{<~}[<~]'))
        )
        return comp_res

    @ftrace(watch=[])
    def process_includes(self, comp_res: CompositionResult) -> CompositionResult:
        comp_res.find_special_nodes('include', lambda n: isinstance(n, IncludeNode))

        if not comp_res.special_nodes['include']:
            return comp_res

        # Process the current batch of includes
        comp_res.sort_special_nodes('include')
        for inode_path in comp_res.pop_all_special('include'):
            inode = inode_path.get_obj(comp_res.root)
            assert isinstance(inode, IncludeNode), f"Invalid node type: {type(inode)}"

            new_loader = self.copy()
            include_composed = compose_from_include_str(
                new_loader,
                include_str=inode.value,
                include_node_path=inode_path,
                composition_result=comp_res,
                custom_loaders=self.custom_loaders,
                node=inode,
            )
            comp_res.merge_composition_at(inode_path, include_composed)

        # Recursive call to process any new includes that were brought in
        return self.process_includes(comp_res)

    def dump(self, data, stream=None):
        if stream is None:
            from io import StringIO

            string_stream = StringIO()
            self.yaml.dump(data, string_stream)
            return string_stream.getvalue()
        else:
            return self.yaml.dump(data, stream)

    def dump_to_node(self, data):
        return dump_to_node(data)


##────────────────────────────────────────────────────────────────────────────}}}


def dump_to_node(data):
    if isinstance(data, Node):
        return data
    representer = DraconRepresenter()
    return representer.represent_data(data)


def load(config_path: str | Path, raw_dict=False, **kwargs):
    loader = DraconLoader(**kwargs)
    if raw_dict:
        loader.yaml.constructor.yaml_base_dict_type = dict
        loader.yaml.constructor.yaml_base_list_type = list
    return loader.load(config_path)


def load_node(node: Node, **kwargs):
    loader = DraconLoader(**kwargs)
    return loader.load_node(node)


def load_file(config_path: str | Path, raw_dict=True, **kwargs):
    return load(f'file:{config_path}', raw_dict, **kwargs)


@ftrace()
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


def compose_config_from_str(yaml, content):
    yaml.compose(content)
    assert isinstance(yaml.composer, DraconComposer)
    res = yaml.composer.get_result()
    return res


def cached_compose_config_from_str(yaml, content):
    cop = deepcopy(_cached_compose_config_from_str(yaml, content))
    return cop


@cached(LRUCache(maxsize=128), key=lambda yaml, content: hashkey(content))
def _cached_compose_config_from_str(yaml, content):
    return compose_config_from_str(yaml, content)


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
