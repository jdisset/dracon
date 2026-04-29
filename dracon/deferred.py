# Copyright (c) 2025 Jean Disset
# MIT License - see LICENSE file for details.

from typing import Optional, Any, List, Dict, TypeVar, Generic, Type, ForwardRef, Union
import dracon.utils as utils
from dracon.utils import ftrace, deepcopy, ser_debug, node_repr
from dracon.utils import ShallowDict
from dracon.composer import (
    CompositionResult,
    walk_node,
)
from ruamel.yaml.nodes import Node
from dracon.nodes import (
    DraconScalarNode,
    ContextNode,
    context_node_hash,
    make_source_context,
)
from dracon.diagnostics import SourceContext, DraconError

from dracon.keypath import KeyPath, ROOTPATH
from dracon.merge import add_to_context, merged, MergeKey, cached_merge_key, reset_context

from functools import partial
import logging
import re

from pydantic import GetCoreSchemaHandler, GetJsonSchemaHandler
from pydantic_core import core_schema
import typing

logger = logging.getLogger(__name__)

DraconLoader = ForwardRef('DraconLoader')


T = TypeVar('T')


## {{{                       --     DeferredNode     --
class DeferredNode(ContextNode, Generic[T]):
    """
    Allows to "pause" the composition of the contained node until construct is called
    All of dracons tree walking functions see this node as a leaf, i.e. it will not
    be traversed further.

    Implements the Symbol protocol: interface() / bind() / invoke() / materialize().
    """

    def __init__(
        self,
        value: Node | T,
        path=ROOTPATH,
        obj_type: Optional[Type[T]] = None,
        clear_ctx: Optional[List[str] | bool] = None,
        loader: Optional['DraconLoader'] = None,
        context=None,
        comp=None,
        creation_context: Optional[SourceContext] = None,
        **kwargs,
    ):
        from dracon.loader import DraconLoader as LoaderCls
        from dracon.loader import dump_to_node

        if loader is None:
            self._loader: Optional[LoaderCls] = LoaderCls()
        else:
            self._loader = loader

        # capture the source context from the value node if available
        if creation_context is None and isinstance(value, Node) and hasattr(value, 'source_context'):
            creation_context = value.source_context
        if creation_context is None and isinstance(value, Node) and hasattr(value, 'start_mark'):
            creation_context = make_source_context(value.start_mark)

        self._creation_context = creation_context

        if not isinstance(value, Node):
            try:
                yaml_string = self._loader.dump(value)
                comp_res = self._loader.compose_config_from_str(yaml_string)
                value = comp_res.root
            except Exception as e:
                logger.warning(f"Failed to dump value: {e}")
                value = dump_to_node(value)

        self._clear_ctx = []
        self._original_clear_ctx = clear_ctx

        if isinstance(clear_ctx, str):
            clear_ctx = [clear_ctx]

        if context is None or clear_ctx is True:
            context = ShallowDict()
        elif not isinstance(context, ShallowDict):
            context = ShallowDict(context)

        if isinstance(clear_ctx, list):
            self._clear_ctx = clear_ctx

        super().__init__(tag='', value=value, context=context, **kwargs)

        self.obj_type = obj_type

        for key in self._clear_ctx:
            if key in self.context:
                del self.context[key]

        self.path = path
        self._full_composition: Optional[CompositionResult] = comp
        self._cached_interface = None

    def __getstate__(self):
        state = DraconScalarNode.__getstate__(self)
        state['path'] = self.path
        state['context'] = self.context
        state['obj_type'] = self.obj_type
        state['_loader'] = self._loader
        state['_full_composition'] = self._full_composition
        state['_clear_ctx'] = self._clear_ctx
        state['_original_clear_ctx'] = self._original_clear_ctx
        state['_creation_context'] = self._creation_context
        return state

    def __setstate__(self, state):
        DraconScalarNode.__setstate__(self, state)
        self.path = state['path']
        self.context = state['context']
        self.obj_type = state['obj_type']
        self._loader = state['_loader']
        self._clear_ctx = state['_clear_ctx']
        self._full_composition = state['_full_composition']
        self._original_clear_ctx = state.get('_original_clear_ctx')
        self._creation_context = state.get('_creation_context')
        self._cached_interface = None

    # ── Symbol protocol ──────────────────────────────────────────────────

    def interface(self):
        if self._cached_interface is not None:
            return self._cached_interface
        from dracon.symbols import InterfaceSpec, SymbolKind, SymbolSourceInfo, MISSING, resolve_annotation
        params, contracts, ret_anno_name = _scan_deferred_interface(self.value, self._loader)
        source = None
        if self._creation_context:
            source = SymbolSourceInfo(
                file_path=getattr(self._creation_context, 'file_path', None),
                line=getattr(self._creation_context, 'line', None),
            )
        scope = getattr(self._loader, 'context', None) if self._loader else None
        ret_anno_obj = resolve_annotation(ret_anno_name, scope) if ret_anno_name else MISSING
        self._cached_interface = InterfaceSpec(
            kind=SymbolKind.DEFERRED, name=None, params=params,
            contracts=contracts, source=source,
            return_annotation=ret_anno_obj,
            return_annotation_name=ret_anno_name,
        )
        return self._cached_interface

    def bind(self, **kwargs):
        from dracon.symbols import BoundSymbol
        return BoundSymbol(self, **kwargs)

    def invoke(self, **kwargs):
        cp = self.copy()
        return cp.construct(context=kwargs)

    def materialize(self):
        return self

    def represented_type(self):
        return None  # deferred branches are node trees, not types

    @ftrace(watch=[])
    def update_context(self, context):
        add_to_context(context, self)

    @ftrace(watch=[])
    def compose(
        self,
        context: Optional[Dict[str, Any]] = None,
        deferred_paths: Optional[list[KeyPath | str]] = None,
        use_original_root: bool = False,
    ) -> 'CompositionResult':
        from dracon.loader import DraconLoader as LoaderCls

        if self._loader is None:
            self._loader = LoaderCls(context=self.context, deferred_paths=deferred_paths)

        assert self._loader is not None, "loader must be set before composing."
        assert self._full_composition is not None, "full composition must be set before composing."

        assert isinstance(self.path, KeyPath)
        assert isinstance(self.value, Node)

        deferred_paths = [KeyPath(p) if isinstance(p, str) else p for p in deferred_paths or []]

        logger.debug(f"composing deferred node at {self.path}. deferred_paths={deferred_paths}")
        if not use_original_root:
            deferred_paths = [self.path + p.rootless() for p in deferred_paths]

        self._loader.deferred_paths = deferred_paths

        composition = self._full_composition
        value = self.value

        ser_debug(context, operation='deepcopy')
        ser_debug(self.context, operation='deepcopy')

        logger.debug(f"composing deferred node at {self.path}. context={context}")
        merged_context = merged(self.context, context or {}, cached_merge_key("{<~}[<~]"))
        merged_context = ShallowDict(merged_context)

        composition.set_at(self.path, value)

        if self._clear_ctx:
            for key in self._clear_ctx:
                composition.defined_vars.pop(key, None)
                composition.default_vars.discard(key)

            def _clear_stale_context(node):
                ctx = getattr(node, 'context', None)
                if ctx is not None:
                    for key in self._clear_ctx:
                        ctx.pop(key, None)

            walk_node(self.path.get_obj(composition.root), _clear_stale_context)

        for key in self._clear_ctx:
            self._loader.context.pop(key, None)

        # update loader context with runtime values so !require checks see them
        if context:
            self._loader.update_context(context)

        composition.walk_no_path(
            callback=partial(
                add_to_context, self._loader.context, merge_key=cached_merge_key('{<~}[<~]')
            )
        )
        # overwrite this node's existing context with the new merged context
        walk_node(
            node=self.path.get_obj(composition.root),
            callback=partial(add_to_context, merged_context, merge_key=cached_merge_key('{<~}[<~]')),
        )

        compres = self._loader.post_process_composed(composition)

        # return a CompositionResult rooted at the deferred subtree
        subtree = self.path.get_obj(compres.root)
        result = CompositionResult(root=subtree)
        result._loader_instance = self._loader
        result._obj_type = self.obj_type
        return result

    @ftrace(watch=[])
    def construct(self, **kwargs) -> T:  # type: ignore
        from dracon.lazy import resolve_all_lazy
        from dracon.dracontainer import Dracontainer
        try:
            context = kwargs.get('context')
            comp_result = self.compose(**kwargs)
            result = self._loader.load_node(comp_result.root, target_type=self.obj_type)
            # resolve lazy values for non-Dracontainer types (like plain dict/list)
            # Dracontainer handles lazy resolution on access, but plain types don't
            if not isinstance(result, Dracontainer):
                result = resolve_all_lazy(result, context_override=context)
            return result
        except DraconError:
            raise
        except Exception as e:
            ctx_info = f" (defined at {self._creation_context})" if self._creation_context else ""
            raise DraconError(f"Deferred node construction failed{ctx_info}: {e}", context=self._creation_context, cause=e) from e

    @property
    def keypath_passthrough(self):
        return self.value

    def __hash__(self):
        return context_node_hash(self)

    def copy(self, clear_context=False, reroot=False, deepcopy_composition=True):
        value_copy = deepcopy(self.value)
        context = {} if clear_context else self.context.copy()

        new_obj = DeferredNode(
            value=value_copy,
            path=deepcopy(self.path),
            obj_type=self.obj_type,
            start_mark=self.start_mark,
            end_mark=self.end_mark,
            anchor=self.anchor,
            comment=self.comment,
            context=context,
            clear_ctx=self._original_clear_ctx,  # use original value for copy
            creation_context=self._creation_context,
        )
        new_obj._loader = self._loader.copy() if self._loader else None
        if not reroot:
            new_obj._full_composition = self._full_composition
            if deepcopy_composition and self._full_composition:
                new_obj._full_composition = deepcopy(self._full_composition)
        else:
            if self._full_composition:
                new_comp = self._full_composition.rerooted(self.path)
                new_obj._full_composition = new_comp
                new_obj.path = ROOTPATH
            else:
                new_obj._full_composition = None

        return new_obj

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: Any, handler: GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        instance_schema = core_schema.is_instance_schema(cls)

        # handle serialization correctly for both DeferredNode and default values
        def serialize_deferred(instance: Any) -> Any:
            if isinstance(instance, cls):
                # if it's already a deferrednode, return its inner value for serialization
                return instance.value
            # otherwise (e.g., a default string value), return the value itself
            return instance

        serialization_schema = core_schema.plain_serializer_function_ser_schema(
            serialize_deferred,
            info_arg=False,
            return_schema=core_schema.any_schema(),  # serialize contained value as anything
        )

        return core_schema.no_info_after_validator_function(
            function=lambda v: v,  # input is already validated/constructed by dracon
            schema=instance_schema,
            serialization=serialization_schema,
        )

    @classmethod
    def __get_pydantic_json_schema__(
        cls, core_schema_obj: core_schema.CoreSchema, handler: GetJsonSchemaHandler
    ) -> Dict[str, Any]:
        json_schema = handler(core_schema.any_schema())
        if "description" not in json_schema:
            json_schema["description"] = ""
        json_schema["description"] += " (note: this value is deferred and constructed later)"
        if "type" in json_schema:
            del json_schema["type"]

        return json_schema


def _scan_deferred_interface(node, loader=None):
    """Extract params, contracts, and return annotation from a deferred node's value tree.

    Routes param/return scanning through the same helper used for !fn templates
    so type annotations and docs stay consistent across both kinds. Also
    collects `!assert` contracts.

    Returns (tuple[ParamSpec, ...], tuple[ContractSpec, ...], return_annotation_name|None).
    """
    from dracon.symbols import ContractSpec
    from dracon.composer import DraconMappingNode
    from dracon.interpolation import InterpolableNode
    from dracon.callable import _scan_template_interface

    if not isinstance(node, DraconMappingNode):
        return (), (), None

    params, ret_anno_name = _scan_template_interface(node, loader)

    contracts: list = []
    for k_node, v_node in node.value:
        tag = getattr(k_node, 'tag', None)
        if not tag or not isinstance(tag, str) or tag != '!assert':
            continue
        name = getattr(k_node, 'value', None)
        hint = getattr(v_node, 'value', None) if hasattr(v_node, 'value') else str(v_node)
        expr = k_node.value if isinstance(k_node, InterpolableNode) else name
        contracts.append(ContractSpec(kind='assert', name=expr or '', message=hint))

    return params, tuple(contracts), ret_anno_name


def make_deferred(
    value: Any,
    loader=None,
    context=None,
    comp=None,
    path=ROOTPATH,
    clear_ctx=None,
    reroot=False,
    obj_type: Optional[Type] = None,
) -> DeferredNode:
    from dracon.utils import ShallowDict
    from dracon.composer import CompositionResult
    from dracon.loader import dump_to_node

    if context is None or clear_ctx is True:
        context = ShallowDict()
    elif not isinstance(context, ShallowDict):
        context = ShallowDict(context)

    n = DeferredNode(
        value=value,
        context=context,
        path=path,
        clear_ctx=clear_ctx,
        loader=loader,
        comp=None,
        obj_type=obj_type,
    )

    final_comp = comp
    if final_comp is None:
        final_comp = CompositionResult(root=n)

    n._full_composition = final_comp

    if reroot:
        original_path = n.path
        n.path = ROOTPATH
        if comp is not None:
            try:
                n._full_composition = final_comp.rerooted(original_path)
            except Exception as e:
                logger.warning(
                    f"could not reroot deferred node at {original_path}: {e}. keeping original composition."
                )
                n.path = original_path

    n._loader = loader

    return n


##────────────────────────────────────────────────────────────────────────────}}}

## {{{                     --     process deferred     --


def parse_query_params(query_string: str) -> Dict[str, Any]:
    from urllib.parse import parse_qsl

    params = {}
    if not query_string:
        return params

    for key, value in parse_qsl(query_string, keep_blank_values=True):
        if value.lower() == "true":
            value = True
        elif value.lower() == "false":
            value = False
        elif value.lower() == "null" or value.lower() == "none":
            value = None
        else:
            try:
                if value.isdigit() or (value.startswith('-') and value[1:].isdigit()):
                    value = int(value)
                else:
                    if ('.' in value or 'e' in value.lower()) and re.match(
                        r'^-?\d+(\.\d+)?([eE][-+]?\d+)?$', value
                    ):
                        value = float(value)
            except (ValueError, TypeError):
                pass

        if "." in key:
            parts = key.split(".")
            current = params
            for part in parts[:-1]:
                if part not in current:
                    current[part] = {}
                elif not isinstance(current[part], dict):
                    if isinstance(current[part], list):
                        current[part] = {}
                    else:
                        current[part] = {'_value': current[part]}

                if not isinstance(current.get(part), dict):
                    current[part] = {}

                current = current[part]

            last_part = parts[-1]
            if last_part in current:
                if isinstance(current[last_part], list):
                    current[last_part].append(value)
                else:
                    current[last_part] = [current[last_part], value]
            else:
                current[last_part] = value
        elif key in params:
            if isinstance(params[key], list):
                params[key].append(value)
            else:
                params[key] = [params[key], value]
        else:
            params[key] = value

    return params


PathOrStr = Union[KeyPath, str]


@ftrace(watch=[], inputs=True)
def process_deferred(
    comp: CompositionResult,
    force_deferred_at: Optional[List[Union[PathOrStr, tuple[PathOrStr, Type]]]] = None,
):
    from dracon.nodes import reset_tag
    # force deferred_at is a list where each elt can be a path, or a tuple of (path, target_type)

    force_deferred_at = force_deferred_at or []
    # early exit: no deferred paths requested, skip the expensive tree walk
    if not force_deferred_at:
        # still need to check for !deferred tags in the tree, but only walk if any exist
        has_deferred_tag = False
        if comp.node_map:
            for node in comp.node_map.values():
                tag = getattr(node, 'tag', None)
                if tag and isinstance(tag, str) and tag.startswith('!deferred'):
                    has_deferred_tag = True
                    break
        if not has_deferred_tag:
            return comp
    deferred_paths = {}
    for elt in force_deferred_at:
        _path = None
        _type = None
        if isinstance(elt, tuple):
            if len(elt) == 2:
                _path, _type = elt
            else:
                raise ValueError(
                    "force_deferred_at must be a list of paths or tuples of (path, type)"
                )
        elif isinstance(elt, str):
            _path = KeyPath(elt)
        elif isinstance(elt, KeyPath):
            _path = elt

        if not isinstance(_path, KeyPath):
            raise ValueError("force_deferred_at must be a list of paths or tuples of (path, type)")

        deferred_paths[_path] = _type

    deferred_nodes = []

    comp.make_map()

    def find_deferred_nodes(node, path: KeyPath):
        is_tag_deferred = (
            hasattr(node, 'tag') and isinstance(node.tag, str) and node.tag.startswith('!deferred')
        )
        is_path_deferred = False
        best_match = ROOTPATH
        _type = None
        for p, t in deferred_paths.items():
            if p.match(path):
                is_path_deferred = True
                # take most specific type
                if t is not None:
                    if _type is None or len(p) > len(best_match):
                        best_match = p
                        _type = t
                break

        if not isinstance(node, DeferredNode) and (is_tag_deferred or is_path_deferred):
            is_child_of_deferred = False
            current_parent_path = path.parent
            while current_parent_path != ROOTPATH and current_parent_path != path:
                if any(p == current_parent_path for _, p, _ in deferred_nodes):
                    is_child_of_deferred = True
                    break
                current_parent_path = current_parent_path.parent

            if not is_child_of_deferred:
                deferred_nodes.append((node, path, _type))

    comp.walk(find_deferred_nodes)
    deferred_nodes = sorted(deferred_nodes, key=lambda x: len(x[1]), reverse=True)

    nodes_processed_paths = set()

    for node, path, obj_type in deferred_nodes:
        if any(path.startswith(processed_path) for processed_path in nodes_processed_paths):
            continue

        current_node_at_path = path.get_obj(comp.root)
        if isinstance(current_node_at_path, DeferredNode):
            continue

        qparams = {}
        node_context = {}
        if hasattr(node, 'context'):
            node_context = node.context

        if hasattr(node, 'tag') and isinstance(node.tag, str) and node.tag.startswith('!deferred'):
            node.tag = node.tag[len('!deferred') :]
            if node.tag.startswith('::'):
                tag_parts = node.tag[2:].split(':', 1)
                query_string = tag_parts[0]
                qparams = parse_query_params(query_string)
                if len(tag_parts) > 1:
                    node.tag = '!' + tag_parts[1]
                else:
                    node.tag = ''
            elif node.tag.startswith(':'):
                node.tag = '!' + node.tag[1:]
            elif not node.tag:
                node.tag = ''
            else:
                if node.tag and not node.tag.startswith('!'):
                    node.tag = '!' + node.tag

        if not hasattr(node, 'tag') or not node.tag or node.tag == '!':
            reset_tag(node)

        loader_instance = getattr(comp, '_loader_instance', None)

        logger.debug(f"Creating deferred node at {path} with type {obj_type}")

        new_node = make_deferred(
            value=node,
            path=path,
            context=node_context,
            comp=comp,
            loader=loader_instance,
            obj_type=obj_type,
            **qparams,
        )
        comp.set_at(path, new_node)
        nodes_processed_paths.add(path)

    comp.make_map()
    return comp
