# Copyright (c) 2025 Jean Disset
# MIT License - see LICENSE file for details.

from ruamel.yaml.constructor import Constructor
import sys
import importlib
from ruamel.yaml.nodes import MappingNode, SequenceNode
from ruamel.yaml.constructor import ConstructorError
from dracon.merge import merged, MergeKey, cached_merge_key
from dracon.keypath import KeyPath, ROOTPATH
from pydantic import (
    TypeAdapter,
    PydanticSchemaGenerationError,
)
import typing
import inspect
from dracon.utils import ShallowDict, ftrace, deepcopy, DEFAULT_EVAL_ENGINE
from dracon import dracontainer
from dracon.interpolation import outermost_interpolation_exprs, InterpolableNode
from dracon.lazy import LazyInterpolable, resolve_all_lazy, is_lazy_compatible
from dracon.resolvable import Resolvable, get_inner_type
from dracon.deferred import DeferredNode, DraconLoader as DeferredDraconLoaderType  # For type hint
from dracon.nodes import reset_tag
from typing import (
    Optional,
    Hashable,
    Type,
    Any,
    ForwardRef,
    List,
    get_origin,
)
from functools import partial
from dracon.nodes import DraconScalarNode  # Added for type checking
from dracon.callable import DraconCallable
from dracon.pipe import DraconPipe
from dracon.partial import DraconPartial
import logging

logger = logging.getLogger("dracon")

# construction-time directive tags: skip the node (and its key-value pair) during construction.
# !noconstruct: strip raw template entries from constructed output
# !unset: mark a key for deletion (survives composition & merging, removed at construction)
_SKIP_TAGS = frozenset({'!noconstruct', '!unset'})
_SYMBOL_MISS = object()  # sentinel: tag is not a symbol invocation

## {{{                        --     type utils     --


_type_adapter_cache: dict[type, TypeAdapter] = {}


def _get_type_adapter(target_type) -> TypeAdapter:
    adapter = _type_adapter_cache.get(target_type)
    if adapter is None:
        adapter = TypeAdapter(target_type)
        _type_adapter_cache[target_type] = adapter
    return adapter


def pydantic_validate(target_type, value, localns=None, root_obj=None, current_path=None):
    if isinstance(target_type, str):  # if it's a string, we need to resolve it
        target_type = resolve_type(target_type, localns=localns)

    if not is_lazy_compatible(target_type) and target_type is not Any:
        resolve_all_lazy(value)
    try:
        return _get_type_adapter(target_type).validate_python(value)
    except PydanticSchemaGenerationError as e:
        instance = target_type(value)  # we try a simple construction
        return instance


def resolve_type(
    type_str: str,
    localns: Optional[dict] = None,
    available_module_names: Optional[List[str]] = None,
) -> Type:
    if not type_str.startswith('!'):
        return Any

    type_str = type_str[1:]

    if available_module_names is None:
        available_module_names = ["__main__"]
    localns = localns or {}

    if type_name := localns.get(type_str):
        return type_name

    module_name, type_name = type_str.rsplit(".", 1) if "." in type_str else ("", type_str)
    if module_name:
        available_module_names = [module_name] + available_module_names

    for module_name in available_module_names:
        try:
            module = sys.modules.get(module_name) or importlib.import_module(module_name)
            if hasattr(module, type_name):
                return getattr(module, type_name)
        except ImportError:
            continue

    if '.' in type_str:
        module_name, cname = type_str.rsplit('.', 1)
        try:
            module = importlib.import_module(module_name)
            localns[module_name] = module
            localns[type_str] = getattr(module, cname)
        except (ImportError, AttributeError):
            pass

    try:
        from typing import _eval_type

        return _eval_type(ForwardRef(type_str), globals(), localns)
    except NameError as e:
        # build a hint showing available type/callable names in scope
        available = sorted(
            k for k, v in (localns or {}).items()
            if isinstance(v, type) or callable(v)
        )[:10]
        hint = ""
        if available:
            hint = f" Available in scope: {', '.join(available)}"
        raise ValueError(f"failed to resolve type '{type_str}'.{hint} {e}") from None
    except Exception:
        return Resolvable if type_str.startswith('Resolvable[') else Any


def get_origin_type(t):
    orig = get_origin(t)
    if orig is None:
        return t
    return orig


_TYPE_BASES = (type, typing._GenericAlias, typing._SpecialForm, typing._SpecialGenericAlias)


def get_all_types(items):
    return {
        name: obj
        for name, obj in items.items()
        if isinstance(obj, _TYPE_BASES)
    }


# cache per module name — module dicts don't change during composition
_module_types_cache: dict[str, dict] = {}


def get_all_types_from_module(module):
    if isinstance(module, str):
        name = module
        if name in _module_types_cache:
            return _module_types_cache[name]
        try:
            module = importlib.import_module(name)
        except ImportError:
            print(f"WARNING: could not import module {name}")
            _module_types_cache[name] = {}
            return {}
    else:
        name = getattr(module, '__name__', None)
        if name and name in _module_types_cache:
            return _module_types_cache[name]
    result = get_all_types(module.__dict__)
    if name:
        _module_types_cache[name] = result
    return result


def get_globals_up_to_frame(frame_n):
    frames = inspect.stack()
    globalns = {}

    for frame_id in range(min(frame_n, len(frames) - 1), 0, -1):
        frame = frames[frame_id]
        globalns.update(frame.frame.f_globals)

    return globalns


def parse_resolvable_tag(tag):
    if tag.startswith('!'):
        tag = tag[1:]
    if tag.startswith('Resolvable['):
        inner = tag[11:-1]
        return inner
    return Any


_collect_cache: dict[tuple, dict] = {}


def collect_all_types(modules, capture_globals=True, globals_at_frame=15):
    if not capture_globals:
        cache_key = tuple(modules)
        if cache_key in _collect_cache:
            return dict(_collect_cache[cache_key])  # copy — caller mutates
        types = {}
        for module in modules:
            types.update(get_all_types_from_module(module))
        _collect_cache[cache_key] = types
        return dict(types)
    types = {}
    for module in modules:
        types.update(get_all_types_from_module(module))
    globalns = get_globals_up_to_frame(globals_at_frame)
    types.update(get_all_types(globalns))
    return types


DEFAULT_TYPES = {
    'Any': Any,
    'Resolvable': Resolvable,
    'DraconResolvable': Resolvable,
}

DEFAULT_MODULES_FOR_TYPES = [
    'pydantic',
    'typing',
    'dracon',
    'numpy',
]

##────────────────────────────────────────────────────────────────────────────}}}


class Draconstructor(Constructor):
    def __init__(
        self,
        preserve_quotes=None,
        loader=None,
        reference_nodes=None,
        interpolation_engine=DEFAULT_EVAL_ENGINE,
        resolve_interpolations=False,
        capture_globals=False,
        dracon_loader=None,
    ):
        Constructor.__init__(self, preserve_quotes=preserve_quotes, loader=loader)
        self.preserve_quotes = preserve_quotes
        self.yaml_base_dict_type = dracontainer.Mapping
        self.yaml_base_sequence_type = dracontainer.Sequence
        self.dracon_loader = dracon_loader

        self.localns = collect_all_types(
            DEFAULT_MODULES_FOR_TYPES,
            capture_globals=capture_globals,
        )
        self.localns.update(get_all_types_from_module('__main__'))

        self.referenced_nodes = reference_nodes or {}
        self._depth = 0
        self._root_node = None
        self._current_path = ROOTPATH
        self.resolve_interpolations = resolve_interpolations
        self.interpolation_engine = interpolation_engine

    def base_construct_object(self, node: Any, deep: bool = False) -> Any:
        """deep is True when creating an object/mapping recursively,
        in that case want the underlying elements available during construction
        """
        if node in self.constructed_objects:
            return self.constructed_objects[node]
        if deep:
            old_deep = self.deep_construct
            self.deep_construct = True
        if node in self.recursive_objects:
            return self.recursive_objects[node]
        self.recursive_objects[node] = None
        data = self.construct_non_recursive_object(node)

        self.constructed_objects[node] = data
        try:
            del self.recursive_objects[node]
        except KeyError as e:
            msg = f"failed to delete {node} from recursive objects: {e}"
            msg += f"\navailable = \n{self.recursive_objects}"
            logger.error(msg)

        if deep:
            self.deep_construct = old_deep
        return data

    def construct_object(self, node, deep=True, target_type=None):
        current_loader_context = self.dracon_loader.context if self.dracon_loader else {}

        self.localns.update(DEFAULT_TYPES)
        self.localns.update(get_all_types(current_loader_context))
        # surface type-valued !define aliases from node.context so resolve_type() can find them
        node_ctx = getattr(node, 'context', None)
        if node_ctx:
            self.localns.update(get_all_types(node_ctx))

        is_root = False
        if self._depth == 0:
            self._root_node = node
            is_root = True
            self._current_path = ROOTPATH
        self._depth += 1
        tag = node.tag

        # resolve interpolated tags on mapping/sequence nodes eagerly.
        # scalar nodes handle tag interpolation lazily via InterpolableNode,
        # so we skip them here to avoid double-resolving.
        if isinstance(node, (MappingNode, SequenceNode)):
            tag = self._resolve_interpolated_tag(node, current_loader_context)

        try:
            if str(tag) in _SKIP_TAGS:
                return None

            # !fn:path universal binding
            if tag and isinstance(tag, str) and tag.startswith('!fn:') and target_type is None:
                return self._construct_fn_target(tag[4:], node, current_loader_context)

            # symbol tag invocation: !name { kwargs } for callables, pipes, templates
            if tag and isinstance(tag, str) and tag.startswith('!') and target_type is None:
                result = self._try_symbol_invocation(tag[1:], node, current_loader_context)
                if result is not _SYMBOL_MISS:
                    return result

            if target_type is None:
                tag_type = resolve_type(tag, localns=self.localns)
            else:
                tag_type = target_type

            if (
                hasattr(tag_type, 'from_yaml')
                and callable(tag_type.from_yaml)
                and target_type is None
            ):
                obj = tag_type.from_yaml(self, node)
                self.constructed_objects[node] = obj
                obj = pydantic_validate(
                    tag_type, obj, self.localns, self._root_node, self._current_path
                )
            else:
                if issubclass(get_origin_type(tag_type), Resolvable):
                    return self.construct_resolvable(node, tag_type)

                if isinstance(node, DeferredNode):
                    return node

                if isinstance(node, InterpolableNode):
                    return self.construct_interpolable(node)

                if tag.startswith('!'):
                    reset_tag(node)
                obj = self.base_construct_object(node, deep=True)

                if (
                    isinstance(node, DraconScalarNode)
                    and isinstance(obj, str)
                    and not isinstance(node, (InterpolableNode, DeferredNode))
                ):
                    from dracon.interpolation_utils import unescape_dracon_specials

                    obj = unescape_dracon_specials(obj)
                node.tag = tag

                obj = pydantic_validate(
                    tag_type,
                    obj,
                    self.localns,
                    root_obj=self._root_node,
                    current_path=self._current_path,
                )

            if self.resolve_interpolations and is_root:
                resolve_all_lazy(obj)

            return obj

        finally:
            self._depth -= 1

    def _invoke_callable(self, callable_obj, kwargs, loader_context, node):
        """Invoke a callable via the Symbol protocol when available, else direct call."""
        try:
            if isinstance(callable_obj, DraconCallable):
                inv_ctx = dict(loader_context)
                node_ctx = getattr(node, 'context', None)
                if node_ctx:
                    inv_ctx.update(node_ctx)
                return callable_obj.invoke(kwargs, invocation_context=inv_ctx)
            # symbol protocol: bind + invoke
            if hasattr(callable_obj, 'invoke') and hasattr(callable_obj, 'bind'):
                return callable_obj.bind(**kwargs).invoke()
            return callable_obj(**kwargs)
        except TypeError as e:
            # enrich error with interface information
            from dracon.symbols import auto_symbol
            sym = auto_symbol(callable_obj)
            iface = sym.interface()
            expected = [
                f"{'*' if p.required else ''}{p.name}" for p in iface.params
            ]
            name = getattr(callable_obj, '__name__', None) or getattr(callable_obj, '_name', str(callable_obj))
            raise ConstructorError(
                None, None,
                f"calling {name}({', '.join(kwargs.keys())}): {e}\n"
                f"  expected interface: ({', '.join(expected)})",
                getattr(node, 'start_mark', None),
            ) from e

    def _resolve_any_target(self, name, loader_context, node):
        """Resolve a name to its value -- context/symbol table first, then import.

        Unlike the old _resolve_fn_target, accepts any symbol kind (types, pipes, etc).
        Returns the resolved value or raises ConstructorError.
        """
        # context/symbol table lookup
        val = loader_context.get(name)
        if val is not None:
            return val
        # node context fallback
        if hasattr(node, 'context'):
            val = (node.context or {}).get(name)
            if val is not None:
                return val
        # import fallback
        try:
            resolved = resolve_type(f'!{name}', localns=self.localns)
            if resolved is not Any:
                return resolved
        except (ValueError, ImportError):
            pass
        # not found -- build hint
        available = sorted(
            n for n in loader_context
            if (callable(loader_context.get(n)) or isinstance(loader_context.get(n), type))
            and not n.startswith('_')
        )[:10]
        hint = f"\n  available in scope: {', '.join(available)}" if available else ""
        raise ConstructorError(
            None, None,
            f"!fn:{name} -- cannot resolve '{name}' as context name or import path{hint}",
            node.start_mark,
        )

    def _construct_kwargs(self, node):
        """Extract kwargs dict from a mapping node, or empty dict."""
        if isinstance(node, MappingNode):
            reset_tag(node)
            kwargs = self.base_construct_object(node, deep=True)
            kwargs = resolve_all_lazy(kwargs)
            return dict(kwargs) if not isinstance(kwargs, dict) else kwargs
        return {}

    def _construct_fn_target(self, target_name, node, loader_context):
        """Handle !fn:target universal binding. Works on any symbol kind."""
        from dracon.symbols import SymbolKind, auto_symbol
        target = self._resolve_any_target(target_name, loader_context, node)
        kwargs = self._construct_kwargs(node)

        sym = auto_symbol(target, name=target_name)
        kind = sym.interface().kind
        if kind == SymbolKind.VALUE:
            raise ConstructorError(
                None, None,
                f"!fn:{target_name} resolved to non-callable {type(target).__name__}",
                node.start_mark,
            )
        # callables/types: DraconPartial for serialization compat
        if kind in (SymbolKind.CALLABLE, SymbolKind.TYPE):
            return DraconPartial(target_name, target, kwargs)
        # pipes, templates, deferred: bound symbol
        return sym.bind(**kwargs) if kwargs else target

    def _try_symbol_invocation(self, tag_name, node, loader_context):
        """Try to invoke a symbol from context via tag syntax.

        Returns _SYMBOL_MISS if tag_name is not a callable/pipe/template in context.
        """
        from dracon.symbols import SymbolKind, auto_symbol
        obj = loader_context.get(tag_name)
        if obj is None and hasattr(node, 'context'):
            obj = (node.context or {}).get(tag_name)
        if obj is None:
            return _SYMBOL_MISS

        sym = auto_symbol(obj, name=tag_name)
        kind = sym.interface().kind
        if kind not in (SymbolKind.CALLABLE, SymbolKind.TEMPLATE, SymbolKind.PIPE):
            return _SYMBOL_MISS

        if isinstance(node, MappingNode):
            return self._invoke_callable(obj, self._construct_kwargs(node), loader_context, node)
        if isinstance(node, DraconScalarNode):
            reset_tag(node)
            arg = self.base_construct_object(node, deep=True)
            if isinstance(arg, LazyInterpolable):
                arg = resolve_all_lazy(arg)
            if arg is None or arg == '':
                return self._invoke_callable(obj, {}, loader_context, node)
            return obj(arg)
        return self._invoke_callable(obj, {}, loader_context, node)

    def construct_resolvable(self, node, tag_type):
        newnode = deepcopy(node)
        inner_type = get_inner_type(tag_type)
        if inner_type is Any:
            inner_type = parse_resolvable_tag(newnode.tag)
        if inner_type is Any:
            reset_tag(newnode)
        else:
            # check if it's a string or a type:
            if isinstance(inner_type, str):
                newnode.tag = f"!{inner_type}"
            else:
                newnode.tag = f"!{inner_type.__name__}"
        res = Resolvable(node=newnode, ctor=self, inner_type=inner_type)
        return res

    def _resolve_interpolated_tag(self, node, loader_context) -> str:
        """Resolve interpolation expressions inside a YAML tag.

        Handles both $() and ${} syntax.  Returns the (possibly rewritten)
        tag string and mutates node.tag when resolution occurs.
        """
        tag = node.tag
        if not (tag and isinstance(tag, str) and tag.startswith('!')):
            return tag
        from dracon.interpolation_utils import transform_dollar_vars
        tag_scan = transform_dollar_vars(str(tag))
        if not outermost_interpolation_exprs(tag_scan):
            return tag
        from dracon.interpolation import evaluate_expression
        ctx = merged(
            loader_context,
            getattr(node, 'context', None) or {},
            cached_merge_key('{<+}'),
        )
        resolved = evaluate_expression(
            tag_scan[1:],  # strip leading '!'
            current_path=self._current_path,
            root_obj=self._root_node,
            engine=self.interpolation_engine,
            context=ctx,
        )
        tag = f"!{resolved}"
        node.tag = tag
        return tag

    def construct_interpolable(self, node):
        current_loader_context = self.dracon_loader.context if self.dracon_loader else {}
        node_value = node.value
        init_outermost_interpolations = node.init_outermost_interpolations
        validator = partial(pydantic_validate, node.tag, localns=self.localns)
        tag_iexpr = outermost_interpolation_exprs(node.tag)
        if tag_iexpr:  # tag is an interpolation itself
            # we can make a combo interpolation that evaluates
            # to a tuple of the resolved tag and value
            node_value = "${('" + str(node.tag) + "', " + str(node.value) + ")}"
            init_outermost_interpolations = outermost_interpolation_exprs(node_value)

            def validator_f(value, localns=self.localns):
                tag, value = value
                return pydantic_validate(tag, value, localns=localns)

            validator = partial(validator_f)

        context = ShallowDict(merged(current_loader_context, node.context, cached_merge_key('{<+}')))
        # inject __scope__: overlay node context onto the loader's SymbolTable
        from dracon.symbol_table import SymbolTable
        if isinstance(current_loader_context, SymbolTable):
            scope = current_loader_context
            node_ctx = node.context
            if node_ctx:
                scope = scope.copy()
                scope.update(node_ctx)
            context['__scope__'] = scope
        else:
            scope = SymbolTable()
            scope.update(context)
            context['__scope__'] = scope
        context['__DRACON_NODES'] = {
            i: Resolvable(node=n, ctor=self.copy()) for i, n in self.referenced_nodes.items()
        }
        logger.debug(f"context for {node}: {context}")

        lzy = LazyInterpolable(
            value=node_value,
            init_outermost_interpolations=init_outermost_interpolations,
            validator=validator,
            current_path=self._current_path,
            root_obj=self._root_node,
            engine=self.interpolation_engine,
            context=context,
            enable_shorthand_vars=self.dracon_loader.enable_shorthand_vars if self.dracon_loader else True,
            source_context=getattr(node, 'source_context', None),
        )

        return lzy

    def copy(self):
        ctor = Draconstructor(
            preserve_quotes=self.preserve_quotes,
            loader=self.loader,
            reference_nodes=self.referenced_nodes,
            interpolation_engine=self.interpolation_engine,
            dracon_loader=self.dracon_loader,
        )

        return ctor

    def __deepcopy__(self, memo):
        return self.copy()

    def construct_mapping(self, node: Any, deep: bool = False) -> Any:
        if not isinstance(node, MappingNode):
            raise ConstructorError(
                None,
                None,
                f"expected a mapping node, but found {node.id!s}",
                node.start_mark,
            )
        mapping = self.yaml_base_dict_type()
        for key_node, value_node in node.value:
            if str(key_node.tag) in _SKIP_TAGS or str(value_node.tag) in _SKIP_TAGS:
                continue
            key = self.construct_object(key_node, deep=True)
            if not isinstance(key, Hashable):
                if isinstance(key, list):
                    key = tuple(key)
            if not isinstance(key, Hashable):
                raise ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    "found unhashable key",
                    key_node.start_mark,
                )
            if self._depth == 1:  # This is the root mapping node
                if isinstance(key, str) and key.startswith('__dracon__'):
                    continue

            value = self.construct_object(value_node, deep=deep)
            mapping[key] = value

        return mapping

    def construct_sequence(self, node, deep=False):
        if not isinstance(node, SequenceNode):
            raise ConstructorError(
                None, None,
                f"expected a sequence node, but found {node.id!s}",
                node.start_mark,
            )
        return [
            self.construct_object(child, deep=deep)
            for child in node.value
            if str(getattr(child, 'tag', '')) not in _SKIP_TAGS
        ]
