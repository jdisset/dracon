# Copyright (c) 2025 Jean Disset
# MIT License - see LICENSE file for details.

## {{{                          --     imports     --
from ruamel.yaml import Node
import os
from typing import Any, Callable, Dict, Optional, Type, Annotated, TypeVar, Literal, List, Union
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
    DEFAULT_EVAL_ENGINE,
)

from dracon.interpolation import InterpolableNode, preprocess_references
from dracon.merge import process_merges, add_to_context, merged, MergeKey
from dracon.instructions import process_instructions
from dracon.deferred import DeferredNode, process_deferred
from dracon.representer import DraconRepresenter
from dracon.nodes import MergeNode, DraconMappingNode  # Added MergeNode, DraconMappingNode

from dracon.lazy import DraconError, resolve_all_lazy

from dracon import dracontainer
import logging

logger = logging.getLogger(__name__)
##────────────────────────────────────────────────────────────────────────────}}}

## {{{                       --     DraconLoader     --


DEFAULT_CONTEXT = {
    # some relatively safe os functions (not all of them are safe)
    'getenv': os.getenv,
    'getcwd': os.getcwd,
    'listdir': os.listdir,
    'join': os.path.join,
    'basename': os.path.basename,
    'dirname': os.path.dirname,
    'expanduser': os.path.expanduser,
    # datetime
    'now': lambda fmt='%Y-%m-%d %H:%M:%S': __import__('datetime').datetime.now().strftime(fmt),
}


@ftrace(watch=[])
def construct(node_or_val, resolve=True, **kwargs):
    if isinstance(node_or_val, DeferredNode):
        n = node_or_val.construct(**kwargs)
    elif isinstance(node_or_val, Node):
        loader = DraconLoader(**kwargs)
        compres = CompositionResult(root=node_or_val)
        n = loader.load_composition_result(compres, post_process=True)
    else:
        n = node_or_val

    if resolve:
        n = resolve_all_lazy(n)

    return n


class DraconLoader:
    def __init__(
        self,
        custom_loaders: Optional[Dict[str, Callable]] = None,
        capture_globals: bool = True,
        base_dict_type: Type[DictLike] = dracontainer.Mapping,
        base_list_type: Type[ListLike] = dracontainer.Sequence,
        enable_interpolation: bool = True,
        interpolation_engine: Literal['asteval', 'eval'] = DEFAULT_EVAL_ENGINE,
        context: Optional[Dict[str, Any]] = None,
        deferred_paths: Optional[list[KeyPath | str]] = None,
        enable_shorthand_vars: bool = True,
        use_cache: bool = True,
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
        self.use_cache = use_cache
        self.enable_shorthand_vars = enable_shorthand_vars

        if interpolation_engine not in ['asteval', 'eval', 'none']:
            raise ValueError(
                f"Invalid interpolation_engine: {interpolation_engine}. Choose 'asteval', 'eval', or 'none'."
            )
        self.interpolation_engine = interpolation_engine

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
        self.yaml.composer.enable_shorthand_vars = self.enable_shorthand_vars
        self.yaml.constructor.dracon_loader = self
        self.yaml.constructor.yaml_base_dict_type = self.base_dict_type
        self.yaml.constructor.interpolation_engine = self.interpolation_engine

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
                self.enable_shorthand_vars,
            )
        )

    def update_context(self, kwargs):
        add_to_context(kwargs, self)

    def copy(self):
        new_loader = DraconLoader(
            custom_loaders=self.custom_loaders.copy(),
            capture_globals=self._capture_globals,
            base_dict_type=self.base_dict_type,
            base_list_type=self.base_list_type,
            enable_interpolation=self._enable_interpolation,
            enable_shorthand_vars=self.enable_shorthand_vars,
            context=None,  # set context separately to preserve type
        )
        # preserve context type (e.g. TrackedContext) instead of wrapping in ShallowDict
        if self.context is not None:
            new_loader.context = self.context.copy()
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

    def compose_config_from_str(self, content: str) -> CompositionResult:
        if self.use_cache:
            composed_content = cached_compose_config_from_str(self.yaml, content)
        else:
            composed_content = compose_config_from_str(self.yaml, content)
        return self.post_process_composed(composed_content)

    def load_node(self, node, target_type: Optional[Type] = None):
        from pydantic import ValidationError
        from dracon.diagnostics import SourceContext
        from dracon.utils import node_repr

        try:
            self.yaml.constructor.referenced_nodes = self.referenced_nodes
            self.yaml.constructor.dracon_loader = self
            return self.yaml.constructor.construct_object(node, target_type=target_type)
        except ValidationError:
            raise
        except DraconError:
            raise
        except Exception as e:
            ctx = getattr(node, 'source_context', None) or getattr(node, '_source_context', None)
            if ctx is None and hasattr(node, 'start_mark'):
                ctx = SourceContext.from_mark(node.start_mark)

            tag_info = getattr(node, 'tag', '')
            if tag_info and tag_info.startswith('!'):
                tag_info = f" (tag: {tag_info})"
            else:
                tag_info = ""

            node_str = node_repr(node, max_depth=3)
            msg = f"Error loading config node{tag_info}: {type(e).__name__}: {e}\n{node_str}"
            raise DraconError(msg, context=ctx, cause=e) from e

    def load_composition_result(self, compres: CompositionResult, post_process=True):
        if post_process:
            compres = self.post_process_composed(compres)
        return self.load_node(compres.root)

    def compose(
        self,
        config_paths: Union[str, Path, List[Union[str, Path]]],
        merge_key: str = "<<{<+}[<~]",
    ):
        """
        Compose configuration from one or more paths.

        If multiple paths are provided, they are merged sequentially
        using the specified merge_key strategy.

        Args:
            config_paths: A single path (str or Path) or a list of paths.
            merge_key: The Dracon merge key string to use when merging multiple files.
                       Defaults to "<<{<+}[<~]" (recursive append dicts, new wins; replace list, new wins).

        Returns:
            The loaded and potentially merged configuration object.
        """

        self.reset_context()

        if not isinstance(config_paths, list):
            paths = [config_paths]
        else:
            paths = list(config_paths)  # ensure it's a mutable list

        if not paths:
            raise ValueError("No configuration paths provided.")

        processed_paths = []
        for p in paths:
            if isinstance(p, Path):
                p_str = p.resolve().as_posix()
            else:
                p_str = str(p)

            if ":" not in p_str:
                processed_paths.append(f"file:{p_str}")
            else:
                processed_paths.append(p_str)

        # load the first configuration as the base
        base_comp_res = compose_from_include_str(
            self, processed_paths[0], custom_loaders=self.custom_loaders
        )

        mkey = MergeKey(raw=merge_key)

        for next_path in processed_paths[1:]:
            next_comp_res = compose_from_include_str(
                self, next_path, custom_loaders=self.custom_loaders
            )
            base_comp_res = base_comp_res.merged(next_comp_res, mkey)

        final_comp_res = self.post_process_composed(base_comp_res)
        return final_comp_res

    def merge(
        self,
        comp_res_1: CompositionResult,
        comp_res_2: CompositionResult | Node,
        merge_key: MergeKey | str,
    ):
        """
        Merges two CompositionResults using the specified merge_key strategy.

        Args:
            comp_res_1: The first CompositionResult.
            comp_res_2: The second CompositionResult.
            merge_key: The Dracon merge key string to use when merging.

        Returns:
            A new CompositionResult that is the result of merging the two inputs.
        """
        if isinstance(merge_key, str):
            merge_key = MergeKey(raw=merge_key)

        cres = comp_res_1.merged(comp_res_2, merge_key)
        final_comp_res = self.post_process_composed(cres)
        return final_comp_res

    def load(
        self,
        config_paths: Union[str, Path, List[Union[str, Path]]],
        merge_key: str = "<<{<+}[<~]",
    ):
        """
        Loads configuration from one or more paths.

        If multiple paths are provided, they are merged sequentially
        using the specified merge_key strategy.

        Args:
            config_paths: A single path (str or Path) or a list of paths.
            merge_key: The Dracon merge key string to use when merging multiple files.
                       Defaults to "<<{<+}[<~]" (recursive append dicts, new wins; replace list, new wins).

        Returns:
            The loaded and potentially merged configuration object.
        """
        final_comp_res = self.compose(config_paths, merge_key=merge_key)

        return self.load_node(final_comp_res.root)

    @ftrace(watch=[])
    def loads(self, content: str):
        """Loads configuration from a YAML string."""
        comp = self.compose_config_from_str(content)
        return self.load_composition_result(comp)

    @ftrace(watch=[])
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

    @ftrace(watch=[], output=False)
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

    @ftrace(watch=[], output=False)
    def save_references(self, comp_res: CompositionResult):
        # the preprocessed refernces are stored as paths that point to refered nodes
        # however, after all the merging and including is done, we need to save
        # the nodes themselves so that they can't be affected by further changes (e.g. construction)

        # TODO: should belong to CompositionResult, not the loader

        comp_res.find_special_nodes('interpolable', lambda n: isinstance(n, InterpolableNode))

        referenced_nodes = {}

        for path in comp_res.pop_all_special('interpolable'):
            node = path.get_obj(comp_res.root)
            assert isinstance(node, InterpolableNode), f"Invalid node type: {type(node)}  => {node}"
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
        from dracon.diagnostics import SourceLocation
        comp_res.find_special_nodes('include', lambda n: isinstance(n, IncludeNode))

        if not comp_res.special_nodes['include']:
            return comp_res

        comp_res.sort_special_nodes('include')
        for inode_path in comp_res.pop_all_special('include'):
            inode = inode_path.get_obj(comp_res.root)
            assert isinstance(inode, IncludeNode), f"Invalid node type: {type(inode)}"

            # capture include location for trace - use file path from context if available
            include_loc = None
            if inode.start_mark:
                include_file = None
                if hasattr(inode, 'context'):
                    include_file = inode.context.get('FILE_PATH') or inode.context.get('FILE')
                loc = SourceLocation.from_mark(inode.start_mark, keypath=str(inode_path))
                if include_file and loc.file_path in ('<unicode string>', '<unknown>'):
                    include_loc = SourceLocation(file_path=include_file, line=loc.line, column=loc.column, keypath=loc.keypath)
                else:
                    include_loc = loc

            new_loader = self.copy()
            include_composed = compose_from_include_str(
                new_loader,
                include_str=inode.value,
                include_node_path=inode_path,
                composition_result=comp_res,
                custom_loaders=self.custom_loaders,
                node=inode,
            )

            # propagate include trace to all nodes from the included file
            if include_loc is not None:
                # get file path from the root node's context if available
                file_path = None
                if hasattr(include_composed.root, 'context'):
                    file_path = include_composed.root.context.get('FILE_PATH') or include_composed.root.context.get('FILE')
                self._propagate_include_trace(include_composed.root, include_loc, file_path=file_path)

            comp_res.set_composition_at(inode_path, include_composed)

        return self.process_includes(comp_res)

    def _propagate_include_trace(self, node, include_loc, file_path=None):
        from dracon.composer import CompositionResult
        from dracon.diagnostics import SourceContext
        comp = CompositionResult(root=node)

        def add_trace(n, path):
            # determine file path - use provided or from node's context
            fp = file_path
            if not fp and hasattr(n, 'context'):
                fp = n.context.get('FILE_PATH') or n.context.get('FILE')

            if hasattr(n, '_source_context') and n._source_context is not None:
                ctx = n._source_context
                new_trace = (include_loc,) + ctx.include_trace
                new_fp = fp if fp and ctx.file_path in ('<unicode string>', '<unknown>') else ctx.file_path
                n._source_context = SourceContext(
                    file_path=new_fp, line=ctx.line, column=ctx.column,
                    keypath=str(path) if path else ctx.keypath,
                    include_trace=new_trace, operation_context=ctx.operation_context,
                )
            elif hasattr(n, 'start_mark') and n.start_mark is not None:
                from dracon.nodes import make_source_context
                ctx = make_source_context(n.start_mark, include_trace=(include_loc,), keypath=str(path))
                if ctx and fp and ctx.file_path in ('<unicode string>', '<unknown>'):
                    ctx = SourceContext(file_path=fp, line=ctx.line, column=ctx.column,
                                        keypath=ctx.keypath, include_trace=ctx.include_trace)
                if hasattr(n, '_source_context'):
                    n._source_context = ctx

        comp.walk(add_trace)

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


@ftrace(watch=[])
def dump_to_node(data):
    if isinstance(data, Node):
        return data
    representer = DraconRepresenter()
    return representer.represent_data(data)


def load(
    config_paths: Union[str, Path, List[Union[str, Path]]],
    raw_dict=False,
    merge_key: str = "<<{<+}[<~]",
    **kwargs,
):
    """
    Loads configuration from one or more paths using a DraconLoader instance.

    If multiple paths are provided, they are merged sequentially
    using the specified merge_key strategy.

    Args:
        config_paths: A single path (str or Path) or a list of paths.
        raw_dict: If True, use standard Python dict/list instead of Dracon containers.
        merge_key: The Dracon merge key string to use when merging multiple files.
                   Defaults to "<<{<+}[<~]".
        **kwargs: Additional arguments passed to the DraconLoader constructor.

    Returns:
        The loaded and potentially merged configuration object.
    """
    loader = DraconLoader(**kwargs)
    if raw_dict:
        loader.yaml.constructor.yaml_base_dict_type = dict
        loader.yaml.constructor.yaml_base_list_type = list
    return loader.load(config_paths, merge_key=merge_key)


def load_node(node: Node, **kwargs):
    loader = DraconLoader(**kwargs)
    return loader.load_node(node)


def load_file(config_path: str | Path, raw_dict=True, **kwargs):
    """Convenience function to load a single file path."""
    if isinstance(config_path, Path):
        path_str = config_path.resolve().as_posix()
    else:
        path_str = str(config_path)

    if ":" not in path_str:
        path_str = f"file:{path_str}"

    return load(path_str, raw_dict=raw_dict, **kwargs)


def loads(config_str: str, raw_dict=False, **kwargs):
    """Loads configuration from a YAML string."""
    loader_instance = kwargs.pop('loader', None)
    if loader_instance:
        loader = loader_instance
    else:
        loader = DraconLoader(**kwargs)
    if raw_dict:
        loader.yaml.constructor.yaml_base_dict_type = dict
        loader.yaml.constructor.yaml_base_list_type = list

    return loader.loads(config_str)


def dump(data, stream=None, **kwargs):
    loader_instance = kwargs.pop('loader', None)
    if loader_instance:
        loader = loader_instance
    else:
        loader = DraconLoader(**kwargs)

    if stream is None:
        from io import StringIO

        string_stream = StringIO()
        loader.yaml.dump(data, string_stream)
        return string_stream.getvalue()
    else:
        return loader.yaml.dump(data, stream)


def load_config_to_dict(maybe_config: str | DictLike) -> DictLike:
    if isinstance(maybe_config, str):
        loader = DraconLoader()
        conf = loader.load(maybe_config)
        conf.set_metadata({'dracon_origin': maybe_config})
        return conf
    return maybe_config


def compose_config_from_str(yaml, content):
    from ruamel.yaml import YAMLError
    try:
        yaml.compose(content)
    except YAMLError as e:
        err_str = str(e)
        # detect flow syntax with interpolation pattern
        if "flow" in err_str.lower() and "${" in content:
            hint = '\n\nHint: Dracon\'s ${...} interpolation conflicts with YAML flow syntax ({key: value}).\nQuote the interpolation: {key: "${variable}"} or use block style:\n  key: ${variable}'
            raise type(e)(str(e) + hint) from e
        raise
    assert isinstance(yaml.composer, DraconComposer)
    return yaml.composer.get_result()


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
