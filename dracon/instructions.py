# Copyright (c) 2025 Jean Disset
# MIT License - see LICENSE file for details.

## {{{                          --     imports     --
from dataclasses import dataclass
from typing import Any, Optional
import re
from dracon.utils import ftrace, deepcopy
from dracon.composer import (
    CompositionResult,
    walk_node,
    DraconMappingNode,
    DraconSequenceNode,
)
from dracon.utils import ShallowDict
from ruamel.yaml.nodes import Node
from dracon.keypath import KeyPath, KeyPathToken, MAPPING_KEY
from dracon.nodes import node_source
from dracon.merge import merged, cached_merge_key, add_to_context
from dracon.interpolation import evaluate_expression, InterpolableNode, LazyConstructable
from dracon.deferred import DeferredNode
from functools import partial
from dracon.nodes import DraconScalarNode
from dracon.cli_declaration import (
    CliDirective,
    parse_directive_body,
    _SET_DEFAULT_KEYS,
)

##────────────────────────────────────────────────────────────────────────────}}}

## {{{                      --     instruct utils     --


def evaluate_nested_mapping_keys(node, engine, context):
    if isinstance(node, DraconMappingNode):
        new_items = []
        for k_node, v_node in node.value:
            # Evaluate the key if it's an InterpolableNode
            if isinstance(k_node, InterpolableNode):
                scalar_key = DraconScalarNode(
                    tag=k_node.tag,
                    value=k_node.evaluate(engine=engine, context=context),
                )
                new_items.append((scalar_key, v_node))
            else:
                new_items.append((k_node, v_node))
            evaluate_nested_mapping_keys(v_node, engine, context)
        node.value = new_items
    elif isinstance(node, DraconSequenceNode):
        for item in node.value:
            evaluate_nested_mapping_keys(item, engine, context)


def _is_cli_metadata_body(value_node) -> bool:
    """True iff `value_node` is a mapping body that should be parsed as
    CLI metadata (per the !require / !set_default extended grammar).

    Trigger: any string key in the (extended) allowed set. `default` is
    recognised on `!require` too so an ill-formed body surfaces a clear
    "require + default" error rather than falling through to legacy
    dict-default semantics.
    """
    if not isinstance(value_node, DraconMappingNode):
        return False
    for k_node, _ in value_node.value:
        kv = getattr(k_node, "value", None)
        if isinstance(kv, str) and kv in _SET_DEFAULT_KEYS:
            return True
    return False


def unpack_mapping_key(
    comp_res: CompositionResult, path: KeyPath, tag_name: str
) -> tuple:
    """Extract key_node, value_node, parent_node from a mapping-key instruction path.

    Validates that path is a mapping key and parent is a DraconMappingNode.
    Used by instruction handlers that operate on `!tag key: value` patterns.
    """
    from dracon.diagnostics import CompositionError
    if not path.is_mapping_key():
        raise CompositionError(f"!{tag_name} must be a mapping key, got {path}")
    key_node = path.get_obj(comp_res.root)
    value_node = path.removed_mapping_key().get_obj(comp_res.root)
    parent_node = path.parent.get_obj(comp_res.root)
    if not isinstance(parent_node, DraconMappingNode):
        ctx = node_source(key_node)
        raise CompositionError(
            f"!{tag_name} parent must be a mapping, got {type(parent_node).__name__}",
            context=ctx,
        )
    return key_node, value_node, parent_node


class Instruction:
    deferred: bool = False  # if True, processed in the assertion pass instead

    @staticmethod
    def match(value: Optional[str]) -> Optional['Instruction']:
        raise NotImplementedError

    def process(self, comp_res: CompositionResult, path: KeyPath, loader) -> CompositionResult:
        raise NotImplementedError


@dataclass
class DeferredInstruction:
    inst: Instruction
    path: KeyPath
    node: Node


def _path_has_prefix(path: KeyPath, prefix: KeyPath) -> bool:
    path_parts = tuple(path.simplified().parts)
    prefix_parts = tuple(prefix.simplified().parts)
    return len(path_parts) >= len(prefix_parts) and path_parts[:len(prefix_parts)] == prefix_parts


def path_is_under_any(path: KeyPath, prefixes: tuple[KeyPath, ...]) -> bool:
    return any(_path_has_prefix(path, prefix) for prefix in prefixes)


def _current_deferred_instruction_path(
    comp_res: CompositionResult, deferred: DeferredInstruction
) -> KeyPath | None:
    assert comp_res.node_map is not None
    for path, node in comp_res.node_map.items():
        if node is deferred.node:
            return path
    try:
        if deferred.path.get_obj(comp_res.root) is deferred.node:
            return deferred.path
    except Exception:
        return None
    return None


def deferred_instruction_value_paths(comp_res: CompositionResult) -> tuple[KeyPath, ...]:
    """Return value subtrees owned by deferred parent instructions."""
    pending = getattr(comp_res, '_deferred_instructions', None) or []
    if not pending:
        return ()
    comp_res.make_map()
    paths = []
    for deferred in pending:
        path = _current_deferred_instruction_path(comp_res, deferred)
        if path is not None:
            paths.append(path.removed_mapping_key())
    return tuple(paths)




@ftrace()
def process_instructions(comp_res: CompositionResult, loader) -> CompositionResult:
    """Process composition-time instructions (!define, !each, !if, !require).

    Instructions whose evaluation depends on symbols still arriving via
    includes/merges (e.g. `!each(x) ${D}` where D is a LazyConstructable on
    a merge-included vocab tag) raise LazyResolutionPending from deep inside
    .resolve(). The handler catches that, stashes the instruction in
    `comp_res._deferred_instructions`, and reports NO_CHANGE so the rewriter
    moves on. retry_deferred_instructions runs them after merges populate
    the vocab.
    """
    from dracon.interpolation import LazyResolutionPending
    from dracon.rewriter import (
        NodeRewriter,
        RewriteHandler,
        RewriteResult,
        MutationKind,
    )

    deferred: list = []

    def discover(node, path):
        tag = getattr(node, 'tag', None)
        if not tag:
            return False
        inst = match_instruct(tag)
        return inst is not None and not getattr(inst, 'deferred', False)

    def skip_under(comp):
        return deferred_instruction_value_paths(comp)

    def apply(comp, path, node):
        # rediscover the instruction kind from the node's current tag
        inst = match_instruct(node.tag)
        if inst is None:
            return RewriteResult.NO_CHANGE
        try:
            inst.process(comp, path, loader)
            return RewriteResult.MUTATED
        except LazyResolutionPending:
            # vocab not yet populated by includes/merges; retry later
            deferred.append(DeferredInstruction(inst, path, node))
            comp._deferred_instructions = deferred  # type: ignore[attr-defined]
            return RewriteResult.NO_CHANGE

    handler = RewriteHandler(
        name='process_instructions',
        discover=discover,
        apply=apply,
        trace_label='instruction',
        mutation_kind=MutationKind.REPLACE,
        restart_other_passes=True,
        skip_under=skip_under,
    )
    # shortest_first matches the previous len-ascending sort: outer
    # instructions resolve before nested ones in the same scope, which
    # matters for !define propagation.
    NodeRewriter(comp_res, handler, order='shortest_first').run()
    comp_res._deferred_instructions = deferred  # type: ignore[attr-defined]
    return comp_res


@ftrace()
def retry_deferred_instructions(
    comp_res: CompositionResult, loader
) -> CompositionResult:
    """Re-run instructions deferred by process_instructions.

    Caller must have set loader._composition_phase = False so LazyConstructable
    failures propagate as real errors on this pass instead of deferring again.
    """
    pending = getattr(comp_res, '_deferred_instructions', None) or []
    if not pending:
        return comp_res
    comp_res._deferred_instructions = []  # type: ignore[attr-defined]
    comp_res.make_map()
    for deferred in pending:
        path = _current_deferred_instruction_path(comp_res, deferred)
        if path is None:
            continue
        comp_res = deferred.inst.process(comp_res, path.copy(), loader)
        comp_res.make_map()
    return comp_res


@ftrace()
def process_assertions(comp_res: CompositionResult, loader) -> CompositionResult:
    """Process all !assert instructions after other instructions have resolved."""
    assert_nodes = []

    def find_assert_nodes(node: Node, path: KeyPath):
        if path_is_under_any(path, skip_paths):
            return
        tag = getattr(node, 'tag', None)
        if tag:
            inst = match_instruct(tag)
            if inst is not None and getattr(inst, 'deferred', False):
                assert_nodes.append((inst, path))

    comp_res.make_map()
    skip_paths = deferred_instruction_value_paths(comp_res)
    comp_res.walk(find_assert_nodes)
    assert_nodes = sorted(assert_nodes, key=lambda x: len(x[1]))

    for inst, path in assert_nodes:
        comp_res = inst.process(comp_res, path.copy(), loader)

    return comp_res


def check_pending_requirements(comp_res: CompositionResult, loader) -> None:
    """Raise CompositionError for any unsatisfied !require vars.

    Honors ``loader._skip_require_check`` so the CLI discovery pre-pass can
    walk the instruction tree without aborting on names that argv will
    supply later.
    """
    if getattr(loader, '_skip_require_check', False):
        return
    from dracon.diagnostics import CompositionError
    unsatisfied = [
        (var, hint, ctx)
        for var, hint, ctx in comp_res.pending_requirements
        if var not in loader.context and var not in comp_res.defined_vars
    ]
    if unsatisfied:
        lines = []
        for var, hint, ctx in unsatisfied:
            loc = f"  required by: {ctx}" if ctx else ""
            lines.append(f"required variable '{var}' not provided\n  hint: {hint}\n{loc}")
        raise CompositionError("\n".join(lines))


##────────────────────────────────────────────────────────────────────────────}}}

## {{{                           --     fn     --


def _has_fn_return_key(node):
    """Check if a mapping node has a !fn-tagged key (return marker)."""
    if not isinstance(node, DraconMappingNode):
        return False
    return any(getattr(k, 'tag', None) == '!fn' for k, v in node.value)


_FN_RETURN_KEY = '__fn_return__'


def _rewrite_fn_return_key(template_node):
    """Find !fn-tagged key in mapping, rewrite to sentinel. Returns True if found."""
    from dracon.diagnostics import CompositionError
    found = False
    for k_node, v_node in template_node.value:
        if getattr(k_node, 'tag', None) == '!fn':
            if found:
                raise CompositionError(
                    "multiple !fn return markers in one template body",
                    context=node_source(k_node),
                )
            k_node.tag = 'tag:yaml.org,2002:str'
            k_node.value = _FN_RETURN_KEY
            found = True
    return found


def fn_template_from_loader_content(raw_content, file_ctx, components, loader, source, name):
    """Create a DraconCallable from raw loader content without post-processing it."""
    from dracon.callable import DraconCallable
    from dracon.diagnostics import CompositionError

    if not isinstance(raw_content, str):
        loader_name = components.main_path.split(':', 1)[0]
        raise CompositionError(
            f"!fn: loader '{loader_name}' returned {type(raw_content).__name__}, expected str",
            context=source,
        )
    from dracon.loader import compose_config_from_str as raw_compose
    raw_comp = raw_compose(loader.yaml, raw_content)
    if components.key_path:
        raw_comp = raw_comp.rerooted(KeyPath(components.key_path))
    return DraconCallable(
        template_node=raw_comp.root, loader=loader, source=source,
        file_context=file_ctx, name=name,
    )


def _fn_from_loader_str(include_str, loader, source, name):
    """Create a DraconCallable from a loader reference string (e.g. 'file:/path/foo.yaml')."""
    from dracon.diagnostics import CompositionError
    from dracon.include import parse_include_str

    if ':' not in include_str:
        raise CompositionError(
            f"!fn scalar must be a loader reference (file:..., pkg:...), got '{include_str}'",
            context=source,
        )
    components = parse_include_str(include_str)
    loader_name, path = components.main_path.split(':', 1)
    if loader_name not in loader.custom_loaders:
        available = ', '.join(sorted(loader.custom_loaders.keys()))
        raise CompositionError(
            f"!fn: unknown loader '{loader_name}'. Available: {available}",
            context=source,
        )
    raw_content, file_ctx = loader.custom_loaders[loader_name](path, draconloader=loader)
    return fn_template_from_loader_content(raw_content, file_ctx, components, loader, source, name)


def _has_loader_scheme(value_str, loaders):
    """Check if a string starts with a known loader scheme (file:, pkg:, etc.)."""
    if ':' not in value_str:
        return False
    return value_str.split(':', 1)[0] in loaders


def _create_fn_callable(value_node, loader, key_node):
    """Create a DraconCallable from an !fn value node."""
    from dracon.callable import DraconCallable
    from dracon.diagnostics import CompositionError

    source = node_source(key_node)
    name = key_node.value

    # interpolable with loader scheme: !fn file:$DIR/path -> resolve vars, then load
    if isinstance(value_node, InterpolableNode):
        if _has_loader_scheme(value_node.value, loader.custom_loaders):
            resolved = value_node.evaluate(
                engine=loader.interpolation_engine, context=value_node.context,
            )
            return _fn_from_loader_str(resolved, loader, source, name)
        # pure expression lambda: !fn ${expr}
        from dracon.nodes import reset_tag
        template_node = deepcopy(value_node)
        reset_tag(template_node)
        return DraconCallable(
            template_node=template_node, loader=loader, source=source, name=name,
        )

    if isinstance(value_node, DraconScalarNode):
        return _fn_from_loader_str(value_node.value, loader, source, name)

    elif isinstance(value_node, (DraconMappingNode, DraconSequenceNode)):
        from dracon.nodes import reset_tag
        template_node = deepcopy(value_node)
        reset_tag(template_node)
        has_return = False
        if isinstance(template_node, DraconMappingNode):
            has_return = _rewrite_fn_return_key(template_node)
        return DraconCallable(
            template_node=template_node, loader=loader, source=source, name=name,
            has_return=has_return,
        )

    else:
        raise CompositionError(
            f"!fn value must be a file reference or inline mapping, "
            f"got {type(value_node).__name__}",
            context=source,
        )


##────────────────────────────────────────────────────────────────────────────}}}

## {{{                          --     define     --
_COERCE_TYPES: dict[str, type] = {
    'int': int, 'float': float, 'str': str, 'bool': bool,
    'list': list, 'dict': dict,
}
_TYPED_DEFINE_RE = re.compile(r'^!define:(\w+)$')
# !set_default:foo — primitive coerce types match \w+; arbitrary type names
# (e.g. list[Event], pkg.Mod) are accepted as pure annotation metadata.
_TYPED_SET_DEFAULT_RE = re.compile(r'^!(?:define\?|set_default):(.+)$')
# !require:Type — pure annotation metadata
_TYPED_REQUIRE_RE = re.compile(r'^!require:(.+)$')
# !returns or !returns:Type
_RETURNS_RE = re.compile(r'^!returns(?::(.+))?$')

# tags that are dracon instructions or built-ins, never constructable types
_BUILTIN_TAGS = frozenset({
    '!include', '!include?', '!noconstruct', '!unset', '!fn', '!pipe',
    'tag:yaml.org,2002:map', 'tag:yaml.org,2002:seq',
    'tag:yaml.org,2002:str', 'tag:yaml.org,2002:int',
    'tag:yaml.org,2002:float', 'tag:yaml.org,2002:bool',
    'tag:yaml.org,2002:null', 'tag:yaml.org,2002:binary',
    'tag:yaml.org,2002:timestamp',
})


def _is_constructable_type_tag(node, loader) -> bool:
    """True iff the node's tag should be constructed lazily (via LazyConstructable)
    rather than eagerly during !define processing.

    Resolvable type tags are always deferred (the lazy path is the point).
    Unknown tags that look like plain identifiers are *also* deferred —
    vocabularies pulled in via `<<(<): !include vocab.yaml` attach their
    exports to node contexts during the merge pass, which runs after
    instructions. Eager construction inside a !define body would see a
    context without those exports and fail; LazyConstructable resolves
    later (when ${var} is evaluated) by which point merges have injected
    the vocabulary. If the name is still undefined at that point, the
    error surfaces there with full context.

    Compound tags (!fn:path, !pipe:name, !mod.Class) are NOT deferred here:
    they have dedicated eager handling in construct_object (or resolve via
    import) and need to produce a bound result at define-time so later tag
    references (e.g. `result: !fast`) can find it in the symbol table.
    """
    if not isinstance(node, (DraconMappingNode, DraconSequenceNode)):
        return False
    tag = getattr(node, 'tag', None)
    if not tag or not isinstance(tag, str) or not tag.startswith('!'):
        return False
    if tag in _BUILTIN_TAGS:
        return False
    if match_instruct(tag) is not None:
        return False
    if tag.startswith('!deferred'):
        return False
    tag_name = tag[1:]
    # symbol table lookup: check if name resolves to a type
    if loader and hasattr(loader, 'context'):
        from dracon.symbol_table import SymbolTable
        from dracon.symbols import SymbolKind
        ctx = loader.context
        if isinstance(ctx, SymbolTable):
            sym = ctx.lookup_symbol(tag_name)
            if sym is not None:
                iface = sym.interface()
                return iface.kind == SymbolKind.TYPE
        # fallback for non-SymbolTable contexts
        val = ctx.get(tag_name)
        if val is not None:
            return isinstance(val, type)
    # import fallback: tag resolves to a type now
    try:
        from dracon.draconstructor import resolve_type
        resolved = resolve_type(tag, localns={})
        if resolved is not Any:
            return True
    except (ValueError, ImportError):
        pass
    # unknown simple-identifier tag: defer in case a merge-included vocab
    # defines it. compound tags (with ':' or '.') fall through to the eager
    # path where !fn:/!pipe:/dotted-import handlers can resolve them.
    return tag_name.isidentifier()


class Define(Instruction):
    """
    `!define var_name : value`
    `!define:type var_name : value`  (explicit type coercion)

    Define a variable var_name with the value of the node
    and add it to the parent node's context
    The node is then removed from the parent node
    (if you want to define and keep the node, use !define_keep)

    Supported types for !define:type -- int, float, str, bool, list, dict.

    If value is an interpolation, this node triggers composition-time evaluation
    """

    def __init__(self, target_type=None):
        self.target_type = target_type

    @staticmethod
    def match(value: Optional[str]) -> Optional['Define']:
        if not value:
            return None
        if value == '!define':
            return Define()
        m = _TYPED_DEFINE_RE.match(value)
        if m:
            type_name = m.group(1)
            if type_name not in _COERCE_TYPES:
                from dracon.diagnostics import CompositionError
                raise CompositionError(
                    f"unknown type '{type_name}' in {value}. "
                    f"Supported types: {', '.join(_COERCE_TYPES)}"
                )
            return Define(target_type=_COERCE_TYPES[type_name])
        return None

    def get_name_and_value(self, comp_res, path, loader):
        from dracon.diagnostics import CompositionError
        key_node, value_node, parent_node = unpack_mapping_key(
            comp_res, path, self.__class__.__name__.lower()
        )

        var_name = key_node.value
        if not var_name.isidentifier():
            ctx = node_source(key_node)
            raise CompositionError(
                f"Invalid variable name '{var_name}' in !{self.__class__.__name__.lower()}. "
                f"Must be a valid Python identifier.",
                context=ctx,
            )

        if getattr(value_node, 'tag', None) == '!fn':
            value = _create_fn_callable(value_node, loader, key_node)
        elif getattr(value_node, 'tag', None) == '!pipe':
            from dracon.pipe import create_pipe_callable
            value = create_pipe_callable(value_node, loader, key_node)
        elif _has_fn_return_key(value_node):
            # implicit callable: !fn key inside body without outer !fn tag
            value = _create_fn_callable(value_node, loader, key_node)
        elif isinstance(value_node, InterpolableNode):
            value = evaluate_expression(
                value_node.value,
                current_path=path,
                root_obj=comp_res.root,
                engine=loader.interpolation_engine,
                context=value_node.context,
                source_context=value_node.source_context,
            )
        elif _is_constructable_type_tag(value_node, loader):
            value = LazyConstructable(
                node=value_node,
                loader=loader,
                source=node_source(key_node),
                defined_vars=comp_res.defined_vars,
                post_process=self.target_type,
            )
        else:
            value = loader.load_composition_result(CompositionResult(root=value_node))

        if self.target_type is not None and not isinstance(value, LazyConstructable):
            try:
                value = self.target_type(value)
            except (ValueError, TypeError) as e:
                ctx = node_source(key_node)
                raise CompositionError(
                    f"cannot coerce {value!r} to {self.target_type.__name__} in !define:{self.target_type.__name__}",
                    context=ctx,
                ) from e

        del parent_node[str(path[-1])]

        return var_name, value, parent_node

    @ftrace(watch=[])
    def process(self, comp_res: CompositionResult, path: KeyPath, loader):
        var_name, value, parent_node = self.get_name_and_value(comp_res, path, loader)

        def _add_and_harden(node):
            # fast path: directly set the key on the context instead of going through merged()
            ctx = getattr(node, 'context', None)
            if ctx is not None:
                ctx[var_name] = value
                sk = getattr(ctx, '_soft_keys', None)
                if sk is not None:
                    sk.discard(var_name)
            else:
                add_to_context({var_name: value}, node)

        walk_node(node=parent_node, callback=_add_and_harden)

        comp_res.defined_vars[var_name] = value

        return comp_res


class SetDefault(Define):
    """
    `!set_default var_name : default_value`
    `!set_default:TypeName var_name : default_value`  (typed annotation)

    Similar to !define, but only sets the variable if it doesn't already exist in the context.

    The optional `:TypeName` is metadata (surfaces in `InterfaceSpec.params`).
    For primitive types (int, float, str, bool, list, dict) the value is also
    coerced. For arbitrary type names, only the annotation is recorded.

    If value is an interpolation, this node triggers composition-time evaluation
    """

    def __init__(self, target_type=None, annotation_name: str | None = None):
        super().__init__(target_type=target_type)
        self.annotation_name = annotation_name

    @staticmethod
    def match(value: Optional[str]) -> Optional['SetDefault']:
        if not value:
            return None
        if value in ('!set_default', '!define?'):
            return SetDefault()
        m = _TYPED_SET_DEFAULT_RE.match(value)
        if m:
            type_name = m.group(1)
            target = _COERCE_TYPES.get(type_name)  # None for non-primitive types -> annotation only
            return SetDefault(target_type=target, annotation_name=type_name)
        return None

    def get_name_and_value(self, comp_res, path, loader):
        from dracon.diagnostics import CompositionError
        key_node = path.get_obj(comp_res.root)
        value_node = path.removed_mapping_key().get_obj(comp_res.root)
        if _is_cli_metadata_body(value_node):
            parent_node = path.parent.get_obj(comp_res.root)
            var_name = key_node.value
            if not var_name.isidentifier():
                raise CompositionError(
                    f"Invalid variable name '{var_name}' in !set_default. "
                    f"Must be a valid Python identifier.",
                    context=node_source(key_node),
                )
            directive, default_value = parse_directive_body(
                var_name, value_node, "set_default", self.target_type,
                key_node=key_node,
            )
            comp_res.cli_directives.append(directive)
            del parent_node[str(path[-1])]
            return var_name, default_value, parent_node

        # scalar / non-CLI-metadata body: fall through to legacy path, then
        # record a directive carrying the resolved scalar default.
        var_name, value, parent_node = super().get_name_and_value(comp_res, path, loader)
        comp_res.cli_directives.append(CliDirective(
            name=var_name, kind="set_default",
            default=value, python_type=self.target_type,
            source_context=node_source(key_node),
        ))
        return var_name, value, parent_node

    @ftrace(watch=[])
    def process(self, comp_res: CompositionResult, path: KeyPath, loader):
        var_name, value, parent_node = self.get_name_and_value(comp_res, path, loader)

        parent_context = getattr(parent_node, 'context', None) or {}
        parent_soft_keys = getattr(parent_context, '_soft_keys', set()) or set()
        context_has_value = var_name in loader.context and var_name in parent_context
        defined_has_value = var_name in comp_res.defined_vars
        existing_is_default = var_name in comp_res.default_vars
        if context_has_value:
            effective = loader.context[var_name]
            is_soft_default = False
        elif var_name in parent_context:
            effective = parent_context[var_name]
            is_soft_default = var_name in parent_soft_keys
        elif defined_has_value and not existing_is_default:
            effective = comp_res.defined_vars[var_name]
            is_soft_default = False
        elif defined_has_value:
            effective = value
            is_soft_default = True
        else:
            effective = value
            is_soft_default = True

        def _add_effective(node):
            add_to_context({var_name: effective}, node, merge_key=cached_merge_key('<<{>~}[>~]'))
            ctx = getattr(node, 'context', None)
            sk = getattr(ctx, '_soft_keys', None)
            if sk is not None and var_name in ctx:
                if is_soft_default:
                    sk.add(var_name)
                else:
                    sk.discard(var_name)

        walk_node(node=parent_node, callback=_add_effective)

        if context_has_value or (
            var_name in parent_context and var_name not in parent_soft_keys
        ):
            comp_res.defined_vars[var_name] = effective
            comp_res.default_vars.discard(var_name)
        elif not defined_has_value:
            comp_res.defined_vars[var_name] = effective
            comp_res.default_vars.add(var_name)
        elif existing_is_default:
            comp_res.default_vars.add(var_name)
        else:
            comp_res.default_vars.discard(var_name)

        return comp_res


##────────────────────────────────────────────────────────────────────────────}}}
## {{{                           --     each     --


class Each(Instruction):
    PATTERN = r"!each\(([a-zA-Z_]\w*)\)"

    """
    `!each(var_name) list-like-expr : value`

    Duplicate the value node for each item in the list-like node and assign the item 
    to the variable var_name (which is added to the context).
    
    If list-like-expr is an interpolation, this node triggers its composition-time evaluation.

    For sequence values:
        !each(i) ${range(3)}:
            - value_${i}
    
    For mapping values with dynamic keys:
        !each(i) ${range(3)}:
            key_${i}: value_${i}

    Removed from final composition.
    """

    def __init__(self, var_name: str):
        self.var_name = var_name

    @staticmethod
    def match(value: Optional[str]) -> Optional['Each']:
        if not value:
            return None
        match = re.match(Each.PATTERN, value)
        if match:
            var_name = match.group(1)
            return Each(var_name)
        return None

    def _generate_sequence_items(self, list_like, value_node, key_node, mkey):
        """Generate expanded sequence items from !each iteration."""
        result = []
        for item in list_like:
            item_ctx = ShallowDict({self.var_name: item})
            for node in value_node.value:
                if isinstance(node, DeferredNode):
                    new_value_node = node.copy(deepcopy_composition=False)
                else:
                    new_value_node = deepcopy(node)
                walk_node(
                    node=new_value_node,
                    callback=partial(add_to_context, item_ctx, merge_key=mkey),
                )
                result.append(new_value_node)
        return result

    @staticmethod
    def _all_each_with_seq_values(parent_node):
        """True iff every key in parent is an !each instruction with a sequence value."""
        if len(parent_node) == 0:
            return False
        for k, v in parent_node.items():
            tag = getattr(k, 'tag', None)
            if not tag:
                return False
            inst = match_instruct(str(tag) if not isinstance(tag, str) else tag)
            if not isinstance(inst, Each) or not isinstance(v, DraconSequenceNode):
                return False
        return True

    def _expand_all_each_siblings(self, parent_node, current_key_node, current_list_like,
                                  comp_res, path, loader, mkey):
        """Batch-expand all !each siblings with sequence values, in mapping order."""
        all_expanded = []
        for k_node, v_node in parent_node.items():
            if k_node is current_key_node:
                each_inst = self
                list_like = current_list_like
            else:
                tag_str = str(k_node.tag) if not isinstance(k_node.tag, str) else k_node.tag
                each_inst = Each.match(tag_str)
                list_like = evaluate_expression(
                    k_node.value,
                    current_path=path,
                    root_obj=comp_res.root,
                    engine=loader.interpolation_engine,
                    context=k_node.context,
                    source_context=k_node.source_context,
                )
            all_expanded.extend(each_inst._generate_sequence_items(list_like, v_node, k_node, mkey))
        return all_expanded

    def _is_inside_sequence(self, comp_res, path):
        """Check if this !each's parent mapping is an item inside a sequence."""
        parent_path = path.parent
        if len(parent_path) < 2:
            return False, None, None
        grandparent_path = parent_path.parent
        try:
            grandparent = grandparent_path.get_obj(comp_res.root)
            if isinstance(grandparent, DraconSequenceNode):
                idx = int(parent_path[-1])
                return True, grandparent, idx
        except (KeyError, ValueError, IndexError):
            pass
        return False, None, None

    @ftrace(inputs=False, watch=[])
    def process(self, comp_res: CompositionResult, path: KeyPath, loader):
        from dracon.diagnostics import CompositionError
        key_node, value_node, parent_node = unpack_mapping_key(comp_res, path, 'each')
        if not isinstance(key_node, InterpolableNode):
            ctx = node_source(key_node)
            raise CompositionError(
                f"!each key must contain an interpolation expression like ${{list}}, got '{key_node.value}'",
                context=ctx,
        )

        list_like = evaluate_expression(
            key_node.value,
            current_path=path,
            root_obj=comp_res.root,
            engine=loader.interpolation_engine,
            context=key_node.context,
            source_context=key_node.source_context,
        )

        mkey = cached_merge_key('{<~}[~<]')

        in_sequence, grandparent, seq_idx = self._is_inside_sequence(comp_res, path)
        all_each_seq = self._all_each_with_seq_values(parent_node)

        # auto-splice: all-!each-seq mapping inside a sequence
        if in_sequence and all_each_seq:
            expanded = self._expand_all_each_siblings(
                parent_node, key_node, list_like, comp_res, path, loader, mkey
            )
            new_value = grandparent.value[:seq_idx] + expanded + grandparent.value[seq_idx + 1 :]
            new_grandparent = DraconSequenceNode(
                tag=grandparent.tag,
                value=new_value,
                start_mark=grandparent.start_mark,
                end_mark=grandparent.end_mark,
                flow_style=grandparent.flow_style,
                comment=grandparent.comment,
                anchor=grandparent.anchor,
            )
            comp_res.set_at(path.parent.parent, new_grandparent)
            return comp_res

        if isinstance(value_node, DraconSequenceNode):
            # all sibling keys must also be !each with sequence values
            if not all_each_seq:
                ctx = node_source(key_node)
                raise CompositionError(
                    "!each with sequence value must be the only key in its mapping "
                    "(or all keys must be !each with sequence values)",
                    context=ctx,
                )
            expanded = self._expand_all_each_siblings(
                parent_node, key_node, list_like, comp_res, path, loader, mkey
            )
            new_parent = DraconSequenceNode.from_mapping(parent_node, empty=True)
            for node in expanded:
                new_parent.append(node)

        elif isinstance(value_node, DraconMappingNode):
            new_parent = parent_node.copy()
            del new_parent[key_node.value]
            value_items = list(value_node.items())
            has_single_instruction_child = len(value_items) == 1 and match_instruct(
                value_items[0][0].tag
            )

            if has_single_instruction_child:
                inner_knode, inner_vnode = value_items[0]
                inner_inst = match_instruct(inner_knode.tag)
                all_results = []

                for item in list_like:
                    item_ctx = merged(key_node.context, {self.var_name: item}, cached_merge_key('{<~}'))
                    new_inner_vnode = deepcopy(inner_vnode)
                    new_inner_knode = deepcopy(inner_knode)
                    add_to_context(item_ctx, new_inner_knode, mkey)
                    walk_node(
                        node=new_inner_vnode,
                        callback=partial(add_to_context, item_ctx, merge_key=mkey),
                    )
                    temp_mapping = DraconMappingNode(
                        tag='tag:yaml.org,2002:map', value=[(new_inner_knode, new_inner_vnode)]
                    )
                    temp_comp = CompositionResult(root=temp_mapping)
                    temp_path = KeyPath([KeyPathToken.ROOT, MAPPING_KEY, new_inner_knode.value])
                    temp_comp = inner_inst.process(temp_comp, temp_path, loader)
                    all_results.append(temp_comp.root)

                if all_results and isinstance(all_results[0], DraconSequenceNode):
                    expanded = []
                    for result in all_results:
                        expanded.extend(result.value)
                    # Check for auto-splice (parent is single-key mapping inside sequence)
                    if in_sequence and len(parent_node) == 1:
                        new_value = (
                            grandparent.value[:seq_idx]
                            + expanded
                            + grandparent.value[seq_idx + 1 :]
                        )
                        new_grandparent = DraconSequenceNode(
                            tag=grandparent.tag,
                            value=new_value,
                            start_mark=grandparent.start_mark,
                            end_mark=grandparent.end_mark,
                            flow_style=grandparent.flow_style,
                            comment=grandparent.comment,
                            anchor=grandparent.anchor,
                        )
                        comp_res.set_at(path.parent.parent, new_grandparent)
                        return comp_res
                    new_parent = DraconSequenceNode.from_mapping(parent_node, empty=True)
                    for elem in expanded:
                        new_parent.append(elem)
                else:
                    new_parent = parent_node.copy()
                    new_parent.value = []
                    for result in all_results:
                        for k, v in result.items():
                            new_parent.append((k, v))
            else:
                for item in list_like:
                    item_ctx = merged(key_node.context, {self.var_name: item}, cached_merge_key('{<~}'))
                    for knode, vnode in value_node.items():
                        new_vnode = deepcopy(vnode)
                        new_knode = deepcopy(knode)

                        if match_instruct(new_knode.tag):
                            add_to_context(item_ctx, new_knode, mkey)
                            walk_node(
                                node=new_vnode,
                                callback=partial(add_to_context, item_ctx, merge_key=mkey),
                            )
                            new_parent.append((new_knode, new_vnode))
                            continue

                        assert isinstance(knode, InterpolableNode), (
                            f"Keys inside an !each instruction must be interpolable (so that they're unique), but got {knode}"
                        )
                        add_to_context(item_ctx, new_knode, mkey)
                        scalar_knode = DraconScalarNode(
                            tag=new_knode.tag,
                            value=new_knode.evaluate(
                                engine=loader.interpolation_engine,
                                context=item_ctx,
                            ),
                        )
                        new_parent.append((scalar_knode, new_vnode))
                        walk_node(
                            node=new_vnode,
                            callback=partial(add_to_context, item_ctx, merge_key=mkey),
                        )
                        evaluate_nested_mapping_keys(new_vnode, loader.interpolation_engine, item_ctx)
        else:
            raise ValueError(
                f"Invalid value node for 'each' instruction: {value_node} of type {type(value_node)}"
            )

        comp_res.set_at(path.parent, new_parent)

        # record each expansion trace
        if comp_res.trace is not None:
            from dracon.loader import _record_subtree_trace
            _record_subtree_trace(
                comp_res, path.parent,
                via="each_expansion",
                detail=f"!each({self.var_name})",
            )

        return comp_res


##────────────────────────────────────────────────────────────────────────────}}}
## {{{                            --     if     --


def as_bool(value: str | int | bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return bool(value)
    if isinstance(value, str):
        try:
            return bool(int(value))
        except ValueError:
            pass
        if value.lower() in ['true']:
            return True
        if value.lower() in ['false', 'null', 'none', '']:
            return False
    raise ValueError(f"Could not convert {value} to bool")


class If(Instruction):
    """
    `!if expr : value`  (shorthand for then-only)
    `!if expr :
      then: value_if_true
      else: value_if_false`

    Evaluate the truthiness of expr (if it's an interpolation, it evaluates it).

    If then/else keys are present:
    - If truthy, use the 'then' branch value
    - If falsy, use the 'else' branch value (or remove if no else)

    If no then/else keys (shorthand):
    - If truthy, include the content
    - If falsy, remove the entire node
    """

    @staticmethod
    def match(value: Optional[str]) -> Optional['If']:
        if not value:
            return None
        if value == '!if':
            return If()
        return None

    def _get_then_else_nodes(self, value_node):
        """Extract then/else nodes, returns (then_node, else_node, is_then_else_style)"""
        if not isinstance(value_node, DraconMappingNode):
            return None, None, False

        keys = [k.value for k, _ in value_node.items()]
        if 'then' in keys or 'else' in keys:
            then_node = else_node = None
            for k, v in value_node.items():
                if k.value == 'then':
                    then_node = v
                elif k.value == 'else':
                    else_node = v
            return then_node, else_node, True
        return None, None, False

    def _add_content_to_parent(self, parent_node, content_node, comp_res, parent_path):
        """Add content node to parent, handling different node types"""
        if isinstance(content_node, DraconMappingNode):
            for key, node in content_node.items():
                parent_node.append((key, node))
        elif isinstance(content_node, DraconSequenceNode):
            comp_res.set_at(parent_path, content_node)
        else:
            # scalar node - replace parent entirely
            if not isinstance(parent_node, DraconMappingNode):
                from dracon.diagnostics import CompositionError
                raise CompositionError("!if with scalar result must appear inside a mapping")
            comp_res.set_at(parent_path, content_node)

    @ftrace(watch=[])
    def process(self, comp_res: CompositionResult, path: KeyPath, loader):
        from dracon.diagnostics import CompositionError
        if not path.is_mapping_key():
            raise CompositionError(f"!if must be a mapping key, got {path}")

        value_path = path.removed_mapping_key()
        parent_path = path.parent

        key_node = path.get_obj(comp_res.root)
        value_node = value_path.get_obj(comp_res.root)
        parent_node = parent_path.get_obj(comp_res.root)

        if key_node.tag != '!if':
            raise CompositionError(f"Expected tag '!if', got '{key_node.tag}'")

        # evaluate condition
        if isinstance(key_node, InterpolableNode):
            from dracon.merge import merged, MergeKey

            eval_context = merged(
                key_node.context or {}, loader.context or {}, cached_merge_key('{<+}')
            )
            # update __scope__ to reflect the fully merged context
            from dracon.symbol_table import SymbolTable
            if isinstance(eval_context, SymbolTable):
                eval_context['__scope__'] = eval_context
            result = evaluate_expression(
                key_node.value,
                path,
                comp_res.root,
                engine=loader.interpolation_engine,
                context=eval_context,
            )
            condition = bool(result)
        else:
            condition = as_bool(key_node.value)

        # check for then/else pattern
        then_node, else_node, is_then_else = self._get_then_else_nodes(value_node)

        if is_then_else:
            # then/else format
            selected_node = then_node if condition else else_node
            if selected_node is not None:
                self._add_content_to_parent(parent_node, selected_node, comp_res, parent_path)
        else:
            # shorthand format - include content if condition is true
            if condition:
                self._add_content_to_parent(parent_node, value_node, comp_res, parent_path)

        del parent_node[key_node.value]

        # if the parent mapping is now empty and lives inside a sequence,
        # remove the empty mapping from the sequence (false !if in a list)
        if (
            isinstance(parent_node, DraconMappingNode)
            and len(parent_node.value) == 0
            and parent_path.parent
        ):
            grandparent = parent_path.parent.get_obj(comp_res.root)
            if isinstance(grandparent, DraconSequenceNode):
                grandparent.value = [
                    item for item in grandparent.value if item is not parent_node
                ]

        # record if-branch trace
        if comp_res.trace is not None:
            branch = "then" if condition else "else"
            condition_str = key_node.value
            from dracon.composition_trace import keypath_to_dotted
            from dracon.loader import _record_subtree_trace
            _record_subtree_trace(
                comp_res, parent_path,
                via="if_branch",
                detail=f"!if {branch} ({condition_str})",
            )

        return comp_res


##────────────────────────────────────────────────────────────────────────────}}}
## {{{                         --     require     --


class Require(Instruction):
    """
    `!require var_name : "hint message"`
    `!require:TypeName var_name : "hint message"`  (typed for InterfaceSpec)

    Declares that var_name must be provided by some outer scope (define, set_default, CLI ++).
    If not satisfied by end of composition, raises CompositionError with the hint.
    Removed from the final tree (pure validation).

    The optional `:TypeName` is metadata: it does not perform runtime type
    checking. It surfaces in the template's `InterfaceSpec.params[i].annotation_name`
    so downstream tools can derive typed schemas from the same SSOT.
    """

    def __init__(self, annotation_name: str | None = None):
        self.annotation_name = annotation_name

    @staticmethod
    def match(value: Optional[str]) -> Optional['Require']:
        if not value:
            return None
        if value == '!require':
            return Require()
        m = _TYPED_REQUIRE_RE.match(value)
        if m:
            return Require(annotation_name=m.group(1).strip())
        return None

    @ftrace(watch=[])
    def process(self, comp_res: CompositionResult, path: KeyPath, loader):
        from dracon.diagnostics import CompositionError
        key_node, value_node, parent_node = unpack_mapping_key(comp_res, path, 'require')

        var_name = key_node.value
        if not var_name.isidentifier():
            ctx = node_source(key_node)
            raise CompositionError(
                f"Invalid variable name '{var_name}' in !require. Must be a valid Python identifier.",
                context=ctx,
            )

        if _is_cli_metadata_body(value_node):
            directive, hint = parse_directive_body(
                var_name, value_node, "require", None, key_node=key_node,
            )
        else:
            hint = value_node.value if hasattr(value_node, 'value') else str(value_node)
            directive = CliDirective(
                name=var_name, kind="require",
                help=hint or None, source_context=node_source(key_node),
            )

        del parent_node[str(path[-1])]
        comp_res.cli_directives.append(directive)

        if var_name in loader.context or var_name in comp_res.defined_vars:
            # mark as accessed: a satisfied !require is a real read of the
            # variable contract, even if no ${var} interpolation reads it.
            # this prevents the unused-var warning from firing on values
            # supplied solely to satisfy the require (--port, ++port, ...).
            try:
                _ = loader.context[var_name]
            except Exception:
                pass
            return comp_res

        ctx = node_source(key_node)
        comp_res.pending_requirements.append((var_name, hint, ctx))
        return comp_res


##────────────────────────────────────────────────────────────────────────────}}}
## {{{                          --     returns     --


class Returns(Instruction):
    """
    `!returns: TypeName`
    `!returns:TypeName : <ignored>`

    Pure metadata marker for `!fn` and `!deferred` bodies that records the
    return type in the symbol's `InterfaceSpec`. Removed from the final tree.
    The annotation is read by `_scan_returns_marker` during interface
    extraction. Processing here is a no-op cleanup so the marker doesn't
    leak into the constructed mapping.
    """

    def __init__(self, annotation_name: str | None = None):
        self.annotation_name = annotation_name

    @staticmethod
    def match(value: Optional[str]) -> Optional['Returns']:
        if not value:
            return None
        m = _RETURNS_RE.match(value)
        if m:
            return Returns(annotation_name=(m.group(1) or '').strip() or None)
        return None

    @ftrace(watch=[])
    def process(self, comp_res: CompositionResult, path: KeyPath, loader):
        # remove the marker from the tree; type metadata was already harvested
        # by interface scanning before composition processing.
        key_node, value_node, parent_node = unpack_mapping_key(comp_res, path, 'returns')
        del parent_node[str(path[-1])]
        return comp_res


##────────────────────────────────────────────────────────────────────────────}}}
## {{{                          --     assert     --


class Assert(Instruction):
    """
    `!assert ${expr} : "message"`

    Validates an invariant on the composed tree. Evaluates the key expression;
    if falsy, raises CompositionError with the message. Removed from the final tree.
    Runs after all other instructions (separate pass).
    """
    deferred = True

    @staticmethod
    def match(value: Optional[str]) -> Optional['Assert']:
        if not value:
            return None
        if value == '!assert':
            return Assert()
        return None

    @ftrace(watch=[])
    def process(self, comp_res: CompositionResult, path: KeyPath, loader):
        from dracon.diagnostics import CompositionError
        key_node, value_node, parent_node = unpack_mapping_key(comp_res, path, 'assert')

        msg = value_node.value if hasattr(value_node, 'value') else str(value_node)

        # evaluate condition expression
        if isinstance(key_node, InterpolableNode):
            eval_context = merged(
                key_node.context or {}, loader.context or {}, cached_merge_key('{<+}')
            )
            # update __scope__ to reflect the fully merged context
            from dracon.symbol_table import SymbolTable
            if isinstance(eval_context, SymbolTable):
                eval_context['__scope__'] = eval_context
            result = evaluate_expression(
                key_node.value,
                current_path=path,
                root_obj=comp_res.root,
                engine=loader.interpolation_engine,
                context=eval_context,
            )
            condition = bool(result)
        else:
            condition = as_bool(key_node.value)

        del parent_node[str(path[-1])]

        if not condition:
            ctx = node_source(key_node)
            raise CompositionError(f"assertion failed: {msg}", context=ctx)

        return comp_res


##────────────────────────────────────────────────────────────────────────────}}}

INSTRUCTION_REGISTRY: dict[str, type[Instruction]] = {
    '!define': Define,
    '!define?': SetDefault,      # weak define -- same pattern as !include vs !include?
    '!set_default': SetDefault,  # backwards compat alias
    '!each': Each,               # note: Each.match uses a regex, handled specially
    '!if': If,
    '!require': Require,
    '!returns': Returns,
    '!assert': Assert,
}


def register_instruction(tag: str, instruction_cls: type[Instruction]):
    """Register a custom instruction class for a YAML tag.

    The class must implement the Instruction protocol: a static `match(value)`
    method and a `process(comp_res, path, loader)` method.
    """
    if not tag.startswith('!'):
        tag = f'!{tag}'
    INSTRUCTION_REGISTRY[tag] = instruction_cls


_match_instruct_neg_cache: set[str] = set()


def match_instruct(value) -> Optional[Instruction]:
    value = str(value) if not isinstance(value, str) else value

    # negative cache: skip values we already know aren't instructions
    if value in _match_instruct_neg_cache:
        return None

    # fast path: exact tag match
    cls = INSTRUCTION_REGISTRY.get(value)
    if cls is not None:
        inst = cls.match(value)
        if inst is not None:
            return inst

    # slow path: pattern-based matching (e.g. !each(var_name))
    for cls in INSTRUCTION_REGISTRY.values():
        inst = cls.match(value)
        if inst is not None:
            return inst

    # trailing-colon detection for common YAML syntax mistakes
    if value.endswith(':'):
        stripped = value.rstrip(':')
        for cls in INSTRUCTION_REGISTRY.values():
            if cls.match(stripped):
                raise ValueError(
                    f"tag '{value}' looks like instruction '{stripped}' but has a trailing colon. "
                    f"YAML interprets `{value} key: val` as a tag named '{value}' (colon is part "
                    f"of the tag). Use `{stripped} key: val` (space, no colon after tag) instead."
                )

    _match_instruct_neg_cache.add(value)
    return None
