# Copyright (c) 2025 Jean Disset
# MIT License - see LICENSE file for details.

## {{{                          --     imports     --
from asteval import Interpreter
from typing import (
    Any,
    Dict,
    Optional,
    List,
)
from dracon.keypath import KeyPath
from copy import copy
from typing import (
    Protocol,
    runtime_checkable,
)
from dracon.utils import DictLike, ftrace, deepcopy, ser_debug, DEFAULT_EVAL_ENGINE
import dracon.utils as utils
from dracon.nodes import DraconMappingNode, ContextNode

from dracon.interpolation_utils import (
    outermost_interpolation_exprs,
    InterpolationMatch,
    find_field_references,
    transform_dollar_vars,
)


import logging

logger = logging.getLogger(__name__)

##────────────────────────────────────────────────────────────────────────────}}}


# import diagnostics for new error types (these are the authoritative versions)
from dracon.diagnostics import (
    DraconError,
    EvaluationError,
    SourceContext,
)


# keep InterpolationError as alias for backwards compatibility
class InterpolationError(EvaluationError):
    """Backwards compatibility alias for EvaluationError."""
    def __init__(self, message, context=None, cause=None, expression=None):
        super().__init__(message, context=context, cause=cause, expression=expression)


BASE_DRACON_SYMBOLS: Dict[str, Any] = {}


def debug_string_state(label: str, s: str):
    print(f"\n=== {label} ===")
    print(f"Raw string: {repr(s)}")
    print("Backslash count: ", {s.count('\\')})
    print("=" * 40)


## {{{                        --     NodeLookup     --


class NodeLookup:
    """a DictLike that allows for keypaths to be used as keys"""

    def __init__(self, root_node=None):
        self.root_node = root_node
        self.available_paths: set[str] = set()

    def __getitem__(self, keypathstr: str):
        if keypathstr not in self.available_paths:
            raise KeyError(
                f"KeyPath {keypathstr} not found in NodeLookup. Available paths: {self.available_paths}"
            )
        keypath = KeyPath(keypathstr)
        obj = keypath.get_obj(self.root_node)
        return obj

    def items(self):
        for keypathstr in self.available_paths:
            yield keypathstr, self[keypathstr]

    def __repr__(self):
        return f"NodeLookup(root_obj={self.root_node}, available_paths={self.available_paths})"

    def merged_with(
        self,
        other,
        *_,
        **__,
    ):
        assert self.root_node == other.root_node, 'Root object mismatch'
        new = NodeLookup(self.root_node)
        new.available_paths = self.available_paths.union(other.available_paths)
        return new

    def __deepcopy__(self, memo):
        new = NodeLookup(self.root_node)
        new.available_paths = self.available_paths.copy()
        return new


##────────────────────────────────────────────────────────────────────────────}}}


## {{{                           --     eval utils    --


@runtime_checkable
class LazyProtocol(Protocol):
    def resolve(self) -> Any: ...

    name: str
    current_path: KeyPath
    root_obj: Any
    context: DictLike


def resolve_field_references(expr: str):
    keypath_matches = find_field_references(expr)
    if not keypath_matches:
        return expr
    offset = 0
    for match in keypath_matches:
        if match.symbol == '@':
            newexpr = (
                f"(__DRACON__PARENT_PATH + __dracon_KeyPath('{match.expr}'))"
                f".get_obj(__DRACON__CURRENT_ROOT_OBJ)"
            )
        elif match.symbol == '&':
            # '&' should only appear in InterpolableNode preprocessing
            # this function runs *during* eval, so '&' shouldn't be here
            raise ValueError(
                f"Unexpected ampersand reference '{match.expr}' during expression evaluation"
            )
        else:
            raise ValueError(f"invalid symbol {match.symbol} in {expr}")

        expr = expr[: match.start + offset] + newexpr + expr[match.end + offset :]
        original_len = match.end - match.start
        offset += len(newexpr) - original_len
    return expr


@ftrace(watch=[], inputs=['expr'])
def preprocess_expr(expr: str):
    expr = resolve_field_references(expr)
    expr = expr.strip()
    return expr


def _extract_identifiers(expr: str) -> set:
    """extract potential variable names from an expression using simple regex."""
    import re
    # match python identifiers but exclude keywords and numbers
    pattern = r'\b([a-zA-Z_][a-zA-Z0-9_]*)\b'
    return set(re.findall(pattern, expr))


@ftrace(watch=[], inputs=['expr'])
def do_safe_eval(expr: str, engine: str, symbols: Optional[dict] = None, source_context: Optional[SourceContext] = None) -> Any:
    original_expr = expr
    expr = preprocess_expr(expr)

    # pre-access symbols that appear in the expression to trigger tracking
    # this ensures accesses are recorded before copying to eval namespace
    if symbols is not None:
        identifiers = _extract_identifiers(expr)
        for ident in identifiers:
            if ident in symbols and not ident.startswith('__'):
                _ = symbols.get(ident)

    if engine == 'asteval':
        safe_eval = Interpreter(user_symbols=symbols or {}, max_string_length=1000)
        try:
            res = safe_eval.eval(expr, raise_errors=True)
        except Exception as e:
            raise EvaluationError(f"Error evaluating expression: {e}", context=source_context, cause=e, expression=original_expr) from e

        errors = safe_eval.error
        if errors:
            errormsg = '\n'.join(': '.join(e.get_error()) for e in errors)
            raise EvaluationError(f"Expression evaluation failed:\n{errormsg}", context=source_context, expression=original_expr)
        return res

    elif engine == 'eval':
        try:
            eval_globals = {}
            eval_globals.update(__builtins__)  # type: ignore
            eval_globals.update(symbols or {})
            return eval(expr, eval_globals)
        except Exception as e:
            raise EvaluationError(f"Error evaluating expression: {e}", context=source_context, cause=e, expression=original_expr) from e
    else:
        raise ValueError(f"Unknown interpolation engine: {engine}")


@ftrace(watch=[])
def dracon_resolve(obj, **ctx):
    from dracon.resolvable import Resolvable
    from dracon.merge import add_to_context
    from dracon.composer import walk_node
    from functools import partial

    err = ser_debug(obj, operation='deepcopy')
    if err:
        print(f"Error in deepcopy when resolving {obj}")

    if isinstance(obj, Resolvable):
        newobj = deepcopy(obj).resolve(ctx)
        return newobj

    node = deepcopy(obj)
    walk_node(
        node=node,
        callback=partial(add_to_context, ctx),
    )

    return node


def prepare_symbols(current_path, root_obj, context):
    # if context has special behavior (e.g. TrackedContext), preserve it
    if context is not None and hasattr(context, 'copy'):
        symbols = context.copy()
    else:
        symbols = dict(context) if context else {}

    # add base symbols and dracon-specific symbols
    base_symbols = copy(BASE_DRACON_SYMBOLS)
    base_symbols.update(
        {
            "__DRACON__CURRENT_PATH": current_path,
            "__DRACON__PARENT_PATH": current_path.parent,
            "__DRACON__CURRENT_ROOT_OBJ": root_obj,
            "__DRACON_RESOLVE": dracon_resolve,
            "__dracon_KeyPath": KeyPath,
        }
    )
    # update symbols with base (context values take precedence for non-internal keys)
    for k, v in base_symbols.items():
        if k.startswith('__') or k not in symbols:
            symbols[k] = v
    return symbols


##────────────────────────────────────────────────────────────────────────────}}}

## {{{                     --     evaluate expression   --


@ftrace(watch=[])
def evaluate_expression(
    expr: str,
    current_path: str | KeyPath = '/',
    root_obj: Any = None,
    allow_recurse: int = 5,
    init_outermost_interpolations: Optional[List[InterpolationMatch]] = None,
    engine: str = DEFAULT_EVAL_ENGINE,
    context: Optional[Dict[str, Any]] = None,
    enable_shorthand_vars: bool = True,
    source_context: Optional[SourceContext] = None,
) -> Any:
    from dracon.merge import merged, MergeKey

    if enable_shorthand_vars:
        expr = transform_dollar_vars(expr)

    if init_outermost_interpolations is None:
        interpolations = outermost_interpolation_exprs(expr)
    else:
        interpolations = init_outermost_interpolations

    if not interpolations:
        return expr

    if isinstance(current_path, str):
        current_path = KeyPath(current_path)

    symbols = prepare_symbols(current_path, root_obj, context)

    def recurse_lazy_resolve(expr):
        if isinstance(expr, LazyProtocol):
            expr.current_path = current_path
            expr.root_obj = root_obj
            expr.context = merged(expr.context, context, MergeKey(raw='{<+}'))
            expr = expr.resolve()
        return expr

    # check if the entire expression is a single interpolation
    if (
        len(interpolations) == 1
        and interpolations[0].start == 0
        and interpolations[0].end == len(expr)
    ):
        # Resolve and evaluate the single interpolation
        interpolation_expr = interpolations[0].expr
        resolved_expr = evaluate_expression(
            interpolation_expr,
            current_path,
            root_obj,
            allow_recurse=allow_recurse,
            engine=engine,
            context=context,
            enable_shorthand_vars=enable_shorthand_vars,
            source_context=source_context,
        )
        evaluated_expr = do_safe_eval(str(resolved_expr), engine, symbols, source_context)
        endexpr = recurse_lazy_resolve(evaluated_expr)
    else:
        # process and replace each interpolation within the expression
        offset = 0
        for match in interpolations:
            resolved_expr = evaluate_expression(
                match.expr,
                current_path,
                root_obj,
                allow_recurse=allow_recurse,
                engine=engine,
                context=context,
                enable_shorthand_vars=enable_shorthand_vars,
                source_context=source_context,
            )
            evaluated_expr = do_safe_eval(str(resolved_expr), engine, symbols, source_context)
            newexpr = str(recurse_lazy_resolve(evaluated_expr))
            expr = expr[: match.start + offset] + newexpr + expr[match.end + offset :]
            offset += len(newexpr) - (match.end - match.start)
        endexpr = expr

    if allow_recurse != 0 and isinstance(endexpr, str):
        return evaluate_expression(
            endexpr,
            current_path,
            root_obj,
            allow_recurse=allow_recurse - 1,
            engine=engine,
            context=context,
            enable_shorthand_vars=enable_shorthand_vars,
            source_context=source_context,
        )
    return endexpr


##────────────────────────────────────────────────────────────────────────────}}}


## {{{                     --     InterpolableNode     --
class InterpolableNode(ContextNode):
    def __init__(
        self,
        value,
        start_mark=None,
        end_mark=None,
        tag=None,
        anchor=None,
        comment=None,
        init_outermost_interpolations=None,
        context=None,
        source_context=None,
    ):
        self.init_outermost_interpolations = init_outermost_interpolations

        ContextNode.__init__(
            self,
            value,
            start_mark=start_mark,
            end_mark=end_mark,
            tag=tag,
            comment=comment,
            anchor=anchor,
            context=context,
            source_context=source_context,
        )
        self.referenced_nodes = NodeLookup()

    def __getstate__(self):
        state = super().__getstate__()
        state['init_outermost_interpolations'] = self.init_outermost_interpolations
        state['referenced_nodes'] = self.referenced_nodes
        return state

    def __setstate__(self, state):
        super().__setstate__(state)
        self.init_outermost_interpolations = state['init_outermost_interpolations']
        self.referenced_nodes = state['referenced_nodes']

    def evaluate(self, path='/', root_obj=None, engine=DEFAULT_EVAL_ENGINE, context=None):
        context = context or {}
        context = {**self.context, **context}
        newval = evaluate_expression(
            self.value,
            current_path=path,
            root_obj=root_obj,
            engine=engine,
            context=context,  # type: ignore
            source_context=self.source_context,
        )
        return newval

    def preprocess_ampersand_references(self, match, comp_res, current_path):
        available_anchors = comp_res.anchor_paths
        context_str = ''

        # references can also have a list of variable definitions attached to them
        # syntax is ${&unique_id:var1=expr1,var2=expr2}
        # these come from the surrounding expression or context and should be passed
        # to the resolve method. It's sort of a asteval-specific limitation becasue there's no
        # locals() or globals() accessible from "inside" the expression...

        if ':' in match.expr:
            match.expr, vardefs = match.expr.split(':')
            if vardefs:
                context_str = ',' + vardefs

        match_parts = match.expr.split('.', 1)
        if match_parts[0] in available_anchors:  # we're matching an anchor
            keypath = available_anchors[match_parts[0]].copy()
            keypath = keypath.down(match_parts[1]) if len(match_parts) > 1 else keypath
        else:  # we're trying to match a keypath
            keypath = current_path.parent.down(KeyPath(match.expr))

        if self.referenced_nodes.root_node is not None:
            assert self.referenced_nodes.root_node == comp_res.root, 'Root object mismatch'
        else:
            self.referenced_nodes.root_node = comp_res.root

        keypathstr = str(keypath.simplified())
        self.referenced_nodes.available_paths.add(keypathstr)
        newexpr = f'__DRACON_RESOLVE(__DRACON_NODES["{keypathstr}"] {context_str})'

        if '__DRACON_NODES' not in self.context:
            self.context['__DRACON_NODES'] = self.referenced_nodes

        return newexpr

    def preprocess_references(self, comp_res, current_path):
        """
        Preprocess field references in the node's value by handling ampersand ('&')
        symbols within interpolation expressions. At ('@') references are handled at a later stage.

        Scans the node's value for field references and, for each ampersand reference that is located
        within an interpolation, replaces it with a "_DRACON_RESOLVE_(...)" call that resolves the referenced node.

        If the current node is used as a mapping key, the parent's mapping
        is recomputed to reflect any changes.

        """

        if self.init_outermost_interpolations is None:
            self.init_outermost_interpolations = outermost_interpolation_exprs(self.value)

        assert self.init_outermost_interpolations is not None
        interps = self.init_outermost_interpolations
        references = find_field_references(self.value)

        offset = 0
        for match in references:
            newexpr = match.expr
            if match.symbol == '&' and any([i.contains(match.start) for i in interps]):
                newexpr = self.preprocess_ampersand_references(match, comp_res, current_path)

                self.value = (
                    self.value[: match.start + offset] + newexpr + self.value[match.end + offset :]
                )
                offset += len(newexpr) - match.end + match.start
            elif match.symbol == '@' and any([i.contains(match.start) for i in interps]):
                ...  # handled in postproc
            else:
                raise ValueError(f'Unknown interpolation symbol: {match.symbol}')

        if references:
            self.init_outermost_interpolations = outermost_interpolation_exprs(self.value)

        if current_path.is_mapping_key():
            parent_node = current_path.parent.get_obj(comp_res.root)
            assert isinstance(parent_node, DraconMappingNode)
            parent_node._recompute_map()

    def flush_references(self):
        if '__DRACON_NODES' in self.context:
            del self.context['__DRACON_NODES']

    def copy(self):
        """Create a copy of the interpolable node with shallow copied context and referenced nodes."""
        new_node = self.__class__(
            value=self.value,
            start_mark=self.start_mark,
            end_mark=self.end_mark,
            tag=self.tag,
            anchor=self.anchor,
            comment=self.comment,
            context=self.context.copy(),
            init_outermost_interpolations=self.init_outermost_interpolations,
            source_context=self._source_context,
        )
        if hasattr(self, 'referenced_nodes') and self.referenced_nodes is not None:
            new_node.referenced_nodes = self.referenced_nodes
        return new_node


##───────────────────────────────────────────────────────────────────────────}}}


def preprocess_references(comp_res):
    comp_res.find_special_nodes('interpolable', lambda n: isinstance(n, InterpolableNode))
    comp_res.sort_special_nodes('interpolable')

    for path in comp_res.pop_all_special('interpolable'):
        node = path.get_obj(comp_res.root)
        assert isinstance(node, InterpolableNode), f"Invalid node type: {type(node)}  => {node}"
        node.preprocess_references(comp_res, path)

    return comp_res
