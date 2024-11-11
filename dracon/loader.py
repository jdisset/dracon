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
    full_flatten,
    ftrace,
    deepcopy,
    make_hashable,
)

from dracon.interpolation import InterpolableNode, preprocess_references
from dracon.merge import process_merges, add_to_context, merged, MergeKey
from dracon.instructions import process_instructions
from dracon.deferred import DeferredNode, process_deferred
from dracon.generator import process_generators
from dracon.representer import DraconRepresenter


from dracon import dracontainer

import logging
log = logging.getLogger(__name__)


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
    try:
        if isinstance(node_or_val, Node):
            loader = DraconLoader(**kwargs)
            compres = CompositionResult(root=node_or_val)
            return loader.load_composition_result(compres, post_process=True)
    except Exception as e:
        # give much more context to the error, since this usually happens inside an asteval eval
        import traceback

        msg = f'Error while constructing node: {e}\n{traceback.format_exc()}'
        raise ValueError(msg)

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
                    capture_globals=True,
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

    def update_context(self, kwargs):
        add_to_context(kwargs, self)

    def copy(self):
        new_loader = DraconLoader(
            custom_loaders=self.custom_loaders.copy(),
            capture_globals=False,
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

    def compose_config_from_str(self, content: str) -> list[CompositionResult]:
        composed_content = cached_compose_config_from_str(self.yaml, content)
        assert isinstance(composed_content, CompositionResult), f"Invalid type: {type(composed_content)}"
        return self.post_process_composed(composed_content)

    def load_node(self, node):
        self.yaml.constructor.referenced_nodes = self.referenced_nodes
        self.yaml.constructor.context = self.context.copy() or {}
        return self.yaml.constructor.construct_document(node)

    def load_composition_result(self, compres: CompositionResult, post_process=True) -> list[Any]:
        """Post-process and construct a CompositionResult"""
        if post_process:
            all_comp = self.post_process_composed(compres)

        return full_flatten([self.load_node(c.root) for c in all_comp])

    def load(self, config_path: str | Path, all=False) -> Any | list[Any]:
        self.reset_context()
        if isinstance(config_path, Path):
            config_path = config_path.resolve().as_posix()
        if ":" not in config_path:
            config_path = f"file:{config_path}"
        comps = compose_from_include_str(self, config_path, custom_loaders=self.custom_loaders)
        loaded = full_flatten([self.load_composition_result(comp) for comp in comps])

        if len(loaded) > 1 and not all:
            log.warning('Configuration yielded multiple results. Call load(..., all=True) to get them.')
        return loaded if all else loaded[0]



    def loads(self, content: str, all=False):
        comps = self.compose_config_from_str(content)
        loaded = full_flatten([self.load_composition_result(comp) for comp in comps])

        if len(loaded) > 1 and not all:
            log.warning('Configuration yielded multiple results. Call loads(..., all=True) to get them.')
        return loaded if all else loaded[0]


    def post_process_composed(self, comp: CompositionResult) -> list[CompositionResult]:
        assert isinstance(comp, CompositionResult), f"Invalid type in postprocess: {type(comp)}"

        comp.walk_no_path(callback=partial(add_to_context, self.context))

        comp = preprocess_references(comp)
        comp = process_deferred(comp, force_deferred_at=self.deferred_paths)  # type: ignore

        comps = full_flatten(process_instructions(comp, self)) #  instructions can fork the composition
        # from now on we deal with a list of compositions
        print(f'After instructions: {type(comps)=}')
        for comp in comps:
            assert isinstance(comp, CompositionResult), f"Invalid type in post_process_composed after instructions: {type(comp)}"

        comps = full_flatten([self.process_includes(comp) for comp in comps])

        processed_comps = []
        for comp in comps:
            comp, merge_changed = process_merges(comp)
            comp, delete_changed = delete_unset_nodes(comp)

            # recompute the map if any merge or delete happened
            if merge_changed or delete_changed:
                comp.make_map()

            comp = self.save_references(comp)
            comp = self.update_deferred_nodes(comp)
            comp.update_paths()
            processed_comps.append(comp)

        return processed_comps

    # def post_process_composed(self, comp: CompositionResult) -> list[CompositionResult]:
    #
    #     assert isinstance(comp, CompositionResult), f"Invalid type in postprocess: {type(comp)}"
    #
    #     comp.walk_no_path(callback=partial(add_to_context, self.context))
    #
    #     comp = preprocess_references(comp)
    #     comp = process_deferred(comp, force_deferred_at=self.deferred_paths)  # type: ignore
    #
    #     comps = full_flatten(process_instructions(comp, self)) #  instructions can fork the composition
    #     # from now on we deal with a list of compositions
    #     print(f'After instructions: {type(comps)=}')
    #     for comp in comps:
    #         assert isinstance(comp, CompositionResult), f"Invalid type in post_process_composed after instructions: {type(comp)}"
    #
    #     comps = full_flatten([self.process_includes(comp) for comp in comps])
    #
    #     comps, merge_changed = zip(*[process_merges(comp) for comp in comps])
    #     comps, delete_changed = zip(*[delete_unset_nodes(comp) for comp in comps])
    #
    #     # recompute the map if any merge or delete happened
    #     for merge, delete in zip(merge_changed, delete_changed):
    #         if merge or delete:
    #             comp.make_map()
    #
    #     comps = [self.save_references(comp) for comp in comps]
    #     comps = [self.update_deferred_nodes(comp) for comp in comps]
    #     for comp in comps:
    #         comp.update_paths()
    #
    #     return comps

    def update_deferred_nodes(self, comp_res: CompositionResult):
        # copies the loader into deferred nodes so they can resume their composition by themselves

        deferred_nodes = []

        def find_deferred_nodes(node: Node, path: KeyPath):
            if isinstance(node, DeferredNode):
                deferred_nodes.append((node, path))

        comp_res.walk(find_deferred_nodes)
        deferred_nodes = sorted(deferred_nodes, key=lambda x: len(x[1]), reverse=True)

        for node, _ in deferred_nodes:
            node._loader = self
            node._full_composition = comp_res
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
            merged(self.referenced_nodes, referenced_nodes, MergeKey(raw='{<+}'))
        )
        return comp_res


    def process_includes(self, comp_res: CompositionResult) -> list[CompositionResult]:
        assert isinstance(comp_res, CompositionResult), f"Invalid type: {type(comp_res)}"
        comp_res.find_special_nodes('include', lambda n: isinstance(n, IncludeNode))
        
        if not comp_res.special_nodes['include']:
            return [comp_res]
        
        comp_res.sort_special_nodes('include')
        current_variants = [comp_res] 
        
        for inode_path in comp_res.pop_all_special('include'):
            new_variants = [] 
            
            for variant in current_variants:
                inode = inode_path.get_obj(variant.root)
                assert isinstance(inode, IncludeNode), f"Invalid node type: {type(inode)}"
                
                new_loader = self.copy()
                include_composed = compose_from_include_str(
                    new_loader,
                    include_str=inode.value,
                    include_node_path=inode_path,
                    composition_result=variant,
                    custom_loaders=self.custom_loaders,
                    node=inode,
                )
                
                # new variant for each included composition
                duplicates = variant.make_duplicates(len(include_composed))
                for dup, incl in zip(duplicates, include_composed):
                    dup.merge_composition_at(inode_path, incl)
                    new_variants.append(dup)
            
            current_variants = new_variants
        
        # process each variant recursively to handle nested includes
        all_processed_variants = []
        for variant in current_variants:
            processed_variants = self.process_includes(variant)
            all_processed_variants.extend(processed_variants)
        
        return all_processed_variants


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
    return loader.load(config_path)


def load_node(node: Node, **kwargs):
    loader = DraconLoader(**kwargs)
    return loader.load_node(node)


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
