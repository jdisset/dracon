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
    fast_copy_node_tree,
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
from dracon.symbol_table import SymbolTable

from dracon.interpolation import InterpolableNode, preprocess_references
from dracon.merge import process_merges, add_to_context, merged, MergeKey, cached_merge_key
from dracon.instructions import process_instructions, process_assertions, check_pending_requirements
from dracon.deferred import DeferredNode, process_deferred
from dracon.representer import DraconRepresenter
from dracon.nodes import MergeNode, DraconMappingNode, DraconSequenceNode

from dracon.lazy import DraconError, resolve_all_lazy

from dracon import dracontainer
import logging

logger = logging.getLogger(__name__)
##────────────────────────────────────────────────────────────────────────────}}}

## {{{                       --     DraconLoader     --


def _now_func(fmt='%Y-%m-%d %H:%M:%S'):
    from datetime import datetime
    return datetime.now().strftime(fmt)


DEFAULT_CONTEXT = {
    # some relatively safe os functions (not all of them are safe)
    'getenv': os.getenv,
    'getcwd': os.getcwd,
    'listdir': os.listdir,
    'join': os.path.join,
    'basename': os.path.basename,
    'dirname': os.path.dirname,
    'expanduser': os.path.expanduser,
    'isfile': os.path.isfile,
    'isdir': os.path.isdir,
    # pathlib
    'Path': Path,
    # datetime
    'now': _now_func,
}


@ftrace(watch=[])
def compose(source, **kwargs) -> CompositionResult:
    """Compose a DeferredNode with runtime context.

    Returns a CompositionResult that can be passed to dracon.construct().
    Auto-copies the source DeferredNode to prevent mutation.
    """
    if isinstance(source, DeferredNode):
        return source.copy().compose(**kwargs)
    raise TypeError(f"compose() expects DeferredNode, got {type(source)}")


@ftrace(watch=[])
def construct(node_or_val, resolve=True, **kwargs):
    if isinstance(node_or_val, DeferredNode):
        n = node_or_val.construct(**kwargs)
    elif isinstance(node_or_val, CompositionResult):
        loader = getattr(node_or_val, '_loader_instance', None) or DraconLoader(**kwargs)
        target_type = getattr(node_or_val, '_obj_type', None)
        n = loader.load_node(node_or_val.root, target_type=target_type)
    elif isinstance(node_or_val, Node):
        loader = DraconLoader(**kwargs)
        compres = CompositionResult(root=node_or_val)
        n = loader.load_composition_result(compres, post_process=True)
    else:
        n = node_or_val

    if resolve:
        n = resolve_all_lazy(n)

    return n


## {{{              --     composition trace helpers     --

def _get_node_source(node) -> 'Optional[SourceContext]':
    """Get source context from a node, enriching with FILE_PATH from context if available."""
    from dracon.diagnostics import SourceContext
    src = getattr(node, 'source_context', None) or getattr(node, '_source_context', None)
    if src and src.file_path in ('<unicode string>', '<unknown>'):
        fp = getattr(node, 'context', {}).get('FILE_PATH') or getattr(node, 'context', {}).get('FILE')
        if fp:
            src = SourceContext(
                file_path=fp, line=src.line, column=src.column,
                keypath=src.keypath, include_trace=src.include_trace,
            )
    return src


def _record_leaves(trace, node_map, via, detail, layer=None):
    """Fast-path: record trace entries for all leaf nodes in a node_map."""
    from dracon.composition_trace import TraceEntry, MAPPING_KEY
    from dracon.keypath import KeyPathToken
    _container = (DraconMappingNode, DraconSequenceNode)
    _record = trace.record
    for path, node in node_map.items():
        if isinstance(node, _container):
            continue
        parts = path.parts
        if MAPPING_KEY in parts:
            continue
        # inline keypath_to_dotted
        segs = []
        for p in parts:
            if not isinstance(p, KeyPathToken):
                segs.append(str(p))
        if not segs:
            continue
        path_str = '.'.join(segs)
        src = getattr(node, 'source_context', None) or getattr(node, '_source_context', None)
        _record(path_str, TraceEntry(
            value=getattr(node, 'value', None), source=src, via=via, detail=detail,
            layer=layer,
        ))


def _record_initial_definitions(comp: CompositionResult):
    """Walk the tree and record a 'definition' entry for every leaf node."""
    if comp.trace is None or comp.node_map is None:
        return
    _record_leaves(comp.trace, comp.node_map, "definition", "local key")


def _record_file_layer_trace(comp: CompositionResult, layer_comp: CompositionResult, layer_idx: int, layer_path: str, metadata=None):
    """Record trace entries for nodes that came from a file layer merge."""
    if comp.trace is None or layer_comp.node_map is None:
        return
    from dracon.composition_trace import LayerTraceRecord
    layer_record = LayerTraceRecord(index=layer_idx, label=layer_path, metadata=dict(metadata or {}))
    _record_leaves(
        comp.trace, layer_comp.node_map,
        "file_layer", f"file layer {layer_idx} ({layer_path})",
        layer=layer_record,
    )


def _record_subtree_trace(comp: CompositionResult, subtree_root_path: 'KeyPath', via: str, detail: str):
    """Walk a subtree and record trace for all leaves."""
    from dracon.composition_trace import TraceEntry, keypath_to_dotted
    from dracon.composer import walk_node
    if comp.trace is None:
        return

    def _record(node, path):
        if isinstance(node, (DraconMappingNode, DraconSequenceNode)):
            return
        path_str = keypath_to_dotted(path)
        if path_str:
            comp.trace.record(path_str, TraceEntry(
                value=getattr(node, 'value', None),
                source=_get_node_source(node),
                via=via,
                detail=detail,
            ))

    try:
        subtree = subtree_root_path.get_obj(comp.root)
    except (KeyError, IndexError, TypeError):
        return
    walk_node(subtree, _record, start_path=subtree_root_path)

##────────────────────────────────────────────────────────────────────────────}}}


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
        trace: bool = True,
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

        from dracon.composition_trace import trace_enabled_from_env
        self._trace_enabled = trace or trace_enabled_from_env()

        if interpolation_engine not in ['asteval', 'eval', 'none']:
            raise ValueError(
                f"Invalid interpolation_engine: {interpolation_engine}. Choose 'asteval', 'eval', or 'none'."
            )
        self.interpolation_engine = interpolation_engine

        self._last_composition: Optional[CompositionResult] = None

        self._init_yaml()

        self.context = SymbolTable()
        if self._context_arg:
            self.context.update(self._context_arg)
        self.reset_context()

    @property
    def symbols(self) -> SymbolTable:
        """SSOT access to the symbol table (same object as self.context)."""
        return self.context

    def catalog(self) -> dict:
        """Catalog projection of the symbol table for tooling.

        Returns a dict of {name: {kind, params, ...}} for user-defined symbols,
        derived directly from the runtime model.
        """
        return self.context.to_json()

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
                ),
                '__scope__': self.context,
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
            trace=self._trace_enabled,
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

    def _trace_for_path(self, keypath: Optional[str]) -> Optional[list]:
        """Look up trace history for a dotted keypath from the last composition."""
        if not keypath or not self._last_composition or not self._last_composition.trace:
            return None
        return self._last_composition.trace.get(keypath) or None

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
        except DraconError as e:
            # enrich existing DraconError with trace if available
            if not e.trace_history and e.context:
                e.trace_history = self._trace_for_path(getattr(e.context, 'keypath', None))
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
            trace_history = self._trace_for_path(getattr(ctx, 'keypath', None) if ctx else None)
            raise DraconError(msg, context=ctx, cause=e, trace_history=trace_history) from e

    def load_composition_result(self, compres: CompositionResult, post_process=True):
        if post_process:
            compres = self.post_process_composed(compres)
        self._last_composition = compres
        return self.load_node(compres.root)

    def compose(
        self,
        config_paths: Union[str, Path, List[Union[str, Path]]],
        merge_key: str = "<<{<+}[<~]",
    ):
        self.reset_context()

        if not isinstance(config_paths, list):
            config_paths = [config_paths]
        if not config_paths:
            raise ValueError("No configuration paths provided.")

        from dracon.stack import CompositionStack, LayerSpec
        layers = [
            LayerSpec(
                source=(p.resolve().as_posix() if isinstance(p, Path) else str(p)),
                merge_key=merge_key,
            )
            for p in config_paths
        ]
        result = CompositionStack(self, layers).composed
        self._last_composition = result
        return result

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
            merge_key = cached_merge_key(merge_key)

        comp2 = comp_res_2 if isinstance(comp_res_2, CompositionResult) else CompositionResult(root=comp_res_2)
        cres = comp_res_1.merged(comp2, merge_key)
        # record merge trace for the new layer
        if cres.trace is not None:
            _record_file_layer_trace(cres, comp2, layer_idx=2, layer_path="merge")
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
        # init tracing for paths that skip compose() (e.g. loads())
        _needs_initial_trace = self._trace_enabled and comp.trace is None
        if _needs_initial_trace:
            from dracon.composition_trace import CompositionTrace
            comp.trace = CompositionTrace()

        ser_debug(self, operation='deepcopy')
        ser_debug(comp, operation='deepcopy')
        comp = preprocess_references(comp)
        comp = process_deferred(comp, force_deferred_at=self.deferred_paths)  # type: ignore
        comp.walk_no_path(
            callback=partial(add_to_context, self.context, merge_key=cached_merge_key('{>~}[>~]'), skip_clean=True)
        )

        # record initial definitions after context propagation (so FILE_PATH is available)
        if _needs_initial_trace:
            _record_initial_definitions(comp)
        comp = self.update_deferred_nodes(comp)
        # composition phase: while this block runs, LazyConstructable
        # resolution failures are translated to LazyResolutionPending so
        # instructions depending on not-yet-merged vocab can be deferred and
        # retried below. Save/restore the previous value so nested
        # post_process_composed calls (triggered by LazyConstructable.resolve
        # re-entering the loader) don't clobber the outer phase.
        prev_phase = getattr(self, '_composition_phase', False)
        self._composition_phase = True
        try:
            comp = process_instructions(comp, self)
            comp = self.process_includes(comp)
            # composition contracts: check pending !require, then run !assert
            check_pending_requirements(comp, self)
            comp = process_assertions(comp, self)
            comp.make_map()
            from dracon.instructions import deferred_instruction_value_paths
            comp, merge_changed = process_merges(
                comp, loader=self, skip_paths=deferred_instruction_value_paths(comp)
            )
            if merge_changed:
                comp.make_map()
        finally:
            self._composition_phase = prev_phase
        # retry pass runs with real-error semantics: any remaining
        # unresolved tags surface as genuine CompositionErrors now.
        from dracon.instructions import retry_deferred_instructions
        had_deferred = bool(getattr(comp, '_deferred_instructions', None))
        comp = retry_deferred_instructions(comp, self)
        if had_deferred:
            comp = process_instructions(comp, self)
            comp = self.process_includes(comp)
            check_pending_requirements(comp, self)
            comp = process_assertions(comp, self)
            comp.make_map()
            comp, retry_merge_changed = process_merges(comp, loader=self)
            merge_changed = merge_changed or retry_merge_changed
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
            merged(self.referenced_nodes, referenced_nodes, cached_merge_key('{<~}[<~]'))
        )
        return comp_res

    @ftrace(watch=[])
    def process_includes(self, comp_res: CompositionResult) -> CompositionResult:
        from dracon.diagnostics import SourceLocation
        from dracon.instructions import deferred_instruction_value_paths, path_is_under_any
        comp_res.find_special_nodes('include', lambda n: isinstance(n, IncludeNode))

        if not comp_res.special_nodes['include']:
            return comp_res

        skip_paths = deferred_instruction_value_paths(comp_res)
        include_paths = [
            path for path in comp_res.special_nodes['include']
            if not path_is_under_any(path, skip_paths)
        ]
        if not include_paths:
            return comp_res

        comp_res.special_nodes['include'] = include_paths
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
            try:
                include_composed = compose_from_include_str(
                    new_loader,
                    include_str=inode.value,
                    include_node_path=inode_path,
                    composition_result=comp_res,
                    custom_loaders=self.custom_loaders,
                    node=inode,
                )
            except FileNotFoundError:
                if not inode.optional:
                    raise
                if inode_path == ROOTPATH:
                    comp_res.root = DraconMappingNode.make_empty()
                else:
                    parent = inode_path.parent.get_obj(comp_res.root)
                    if isinstance(parent, DraconSequenceNode):
                        del parent[int(inode_path[-1])]
                    else:
                        del parent[inode_path[-1]]
                comp_res.make_map()
                continue

            # propagate include trace to all nodes from the included file
            if include_loc is not None:
                # get file path from the root node's context if available
                file_path = None
                if hasattr(include_composed.root, 'context'):
                    file_path = include_composed.root.context.get('FILE_PATH') or include_composed.root.context.get('FILE')
                self._propagate_include_trace(include_composed.root, include_loc, file_path=file_path)

            comp_res.set_composition_at(inode_path, include_composed)

            # record include trace
            if comp_res.trace is not None:
                _record_subtree_trace(
                    comp_res, inode_path,
                    via="include",
                    detail=f"!include {inode.value}",
                )

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

    def dump_to_node(self, data: Any) -> Node:
        """Quote data into a Node using this loader's bound vocabulary.

        Semantic boundary for the object -> node direction, peer of
        :meth:`construct`. The loader's :attr:`context` (a SymbolTable)
        drives vocabulary-aware tag emission; any value whose type is
        registered canonically gets its short tag, with qualname fallback
        otherwise.
        """
        if isinstance(data, Node):
            return data
        prev = self.yaml.representer._vocabulary
        self.yaml.representer._vocabulary = self.context
        try:
            return self.yaml.representer.represent_data(data)
        finally:
            self.yaml.representer._vocabulary = prev

    def dump(self, data, stream=None):
        """Quote and emit data as YAML text using this loader's vocabulary.

        Equivalent to ``emit(self.dump_to_node(data))``. When ``stream`` is
        None, returns the YAML string; otherwise writes to the stream and
        returns None (ruamel convention).
        """
        node = self.dump_to_node(data)
        if stream is None:
            from io import StringIO
            buf = StringIO()
            self.yaml.dump(node, buf)
            return buf.getvalue()
        return self.yaml.dump(node, stream)

    def stack(self, *sources, **ctx) -> 'CompositionStack':
        from dracon.stack import CompositionStack, LayerSpec
        layers = [
            LayerSpec(source=s, context=ctx if s is sources[0] else {})
            if isinstance(s, str) else s
            for s in sources
        ]
        return CompositionStack(self, layers)


##────────────────────────────────────────────────────────────────────────────}}}


@ftrace(watch=[])
def dump_to_node(
    data: Any,
    context: SymbolTable | dict[str, Any] | None = None,
) -> Node:
    """Quote a Python value into a Node against the given vocabulary.

    Semantic boundary for the object -> node direction, peer of
    :func:`construct`. Use this when you want a Node tree for further
    processing (e.g. inserting as a layer into a ``CompositionStack``)
    rather than YAML text.

    The vocabulary controls tag naming: any value whose type is registered
    in the SymbolTable gets its canonical short tag. Values without a
    vocabulary-local name fall back to qualname, governed by the
    representer's ``full_module_path``.
    """
    if isinstance(data, Node):
        return data
    loader = DraconLoader()
    if isinstance(context, SymbolTable):
        # preserve canonical entries that would be lost via dict-style .update
        loader.context = context
    elif context:
        loader.context.update(context)
    return loader.dump_to_node(data)


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
    """Quote and emit data as YAML text.

    Peer of :func:`dump_to_node` for the text boundary. Accepts a
    ``loader=`` kwarg to reuse an existing ``DraconLoader``; otherwise
    remaining kwargs (including ``context=``) build a fresh one.
    """
    loader = kwargs.pop('loader', None) or DraconLoader(**kwargs)
    return loader.dump(data, stream)


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
    cached = _cached_compose_config_from_str(yaml, content)
    # fast tree copy instead of generic deepcopy
    new_root = fast_copy_node_tree(cached.root)
    return CompositionResult(
        root=new_root,
        special_nodes={},
        anchor_paths=deepcopy(cached.anchor_paths) if cached.anchor_paths else None,
        defined_vars=deepcopy(cached.defined_vars) if cached.defined_vars else {},
        default_vars=set(cached.default_vars),
        pending_requirements=list(cached.pending_requirements),
        trace=None,
    )


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


def make_callable(
    path_or_node,
    context: Optional[Dict[str, Any]] = None,
    context_types: Optional[List[type]] = None,
    auto_context: bool = False,
    **loader_kwargs,
):
    """
    Turn a YAML config or DeferredNode into a callable function.

    Args:
        path_or_node: File path or existing DeferredNode
        context: Base context dict (types, functions, values)
        context_types: List of types to add as {name: type}
        auto_context: If True, capture types from caller's namespace
        **loader_kwargs: Passed to DraconLoader (deferred_paths, etc.)

    Returns:
        Callable that accepts **kwargs, injects them as context, and
        returns the constructed config.
    """
    from dracon.deferred import DeferredNode
    from dracon.utils import extract_types_from_caller

    full_context = {}

    if auto_context:
        full_context.update(extract_types_from_caller(depth=2))

    if context_types:
        for t in context_types:
            if hasattr(t, '__name__'):
                full_context[t.__name__] = t

    if context:
        full_context.update(context)

    if isinstance(path_or_node, DeferredNode):
        base_node = path_or_node
        if full_context:
            base_node.update_context(full_context)
    elif isinstance(path_or_node, (str, Path)):
        loader_kwargs.setdefault('deferred_paths', ['/'])
        loader = DraconLoader(context=full_context, **loader_kwargs)
        base_node = loader.load(str(path_or_node))
        if not isinstance(base_node, DeferredNode):
            raise ValueError(
                f"Expected loading with deferred_paths=['/'] to return DeferredNode, got {type(base_node)}"
            )
    else:
        raise TypeError(f"Expected path or DeferredNode, got {type(path_or_node)}")

    def call(**kwargs):
        node_copy = base_node.copy()
        return node_copy.construct(context=kwargs)

    call.__doc__ = f"Callable config from: {path_or_node}"
    return call
