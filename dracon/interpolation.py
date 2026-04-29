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
    unescape_dracon_specials,
)


import ast
import re
import logging

logger = logging.getLogger(__name__)

##────────────────────────────────────────────────────────────────────────────}}}


# import diagnostics for new error types (these are the authoritative versions)
from dracon.diagnostics import (
    DraconError,
    EvaluationError,
    UndefinedNameError,
    SourceContext,
)


# keep InterpolationError as alias for backwards compatibility
class InterpolationError(EvaluationError):
    """Backwards compatibility alias for EvaluationError."""
    def __init__(self, message, context=None, cause=None, expression=None):
        super().__init__(message, context=context, cause=cause, expression=expression)


# base symbols available in all interpolation expressions
BASE_DRACON_SYMBOLS: Dict[str, Any] = {}

try:
    import numpy as np
    BASE_DRACON_SYMBOLS['np'] = np
except ImportError:
    pass  # numpy not installed


class _UnresolvedSentinel:
    _instance = None
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    def __repr__(self): return 'UNRESOLVED'
    def __bool__(self): return False

UNRESOLVED_SENTINEL = _UnresolvedSentinel()


class PartiallyResolved:
    __slots__ = ('expr',)
    def __init__(self, expr: str): self.expr = expr
    def __repr__(self): return f'PartiallyResolved({self.expr!r})'


_FOLDABLE = (str, int, float, bool, type(None))

# compiled regex for extracting undefined name from NameError messages
_UNDEF_NAME_RE = re.compile(r"name '(\w+)' is not defined")


class _Folder(ast.NodeTransformer):
    """AST node transformer that substitutes known variables and folds constant sub-expressions."""

    def __init__(self, symbols: dict):
        self.symbols = symbols

    def _try_fold(self, node, children):
        """Attempt to fold a node whose children are all constants."""
        if all(isinstance(c, ast.Constant) for c in children):
            try:
                val = eval(compile(ast.Expression(body=node), '<fold>', 'eval'))
                return ast.copy_location(ast.Constant(value=val), node)
            except Exception:
                pass
        return node

    def visit_Name(self, node):
        if node.id.startswith('__'):
            return node
        if node.id in self.symbols and isinstance(self.symbols[node.id], _FOLDABLE):
            return ast.copy_location(ast.Constant(value=self.symbols[node.id]), node)
        return node

    def visit_BinOp(self, node):
        self.generic_visit(node)
        return self._try_fold(node, [node.left, node.right])

    def visit_UnaryOp(self, node):
        self.generic_visit(node)
        return self._try_fold(node, [node.operand])

    def visit_Compare(self, node):
        self.generic_visit(node)
        return self._try_fold(node, [node.left] + node.comparators)

    def visit_BoolOp(self, node):
        self.generic_visit(node)
        return self._try_fold(node, node.values)

    def visit_IfExp(self, node):
        self.generic_visit(node)
        if isinstance(node.test, ast.Constant):
            return node.body if node.test.value else node.orelse
        return node


def fold_known_vars(expr: str, symbols: dict) -> str:
    """Fold known variables into an expression, leaving unknowns as-is.

    Pure function using stdlib ast. Returns the simplified expression string.
    """
    try:
        tree = ast.parse(expr, mode='eval')
    except SyntaxError:
        return expr

    folded = _Folder(symbols).visit(tree)
    ast.fix_missing_locations(folded)
    return ast.unparse(folded)


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


_LC_SENTINEL = object()


class LazyResolutionPending(Exception):
    """Signal that a LazyConstructable could not resolve *yet*: a subsequent
    composition step (process_includes, process_merges) may make resolution
    succeed. Propagates unchanged through evaluate_expression; caught by
    process_instructions, which defers the triggering instruction for retry.

    The loader's `_composition_phase` flag gates this behavior: while True,
    LazyConstructable raises Pending on failure; once False (after retry),
    failures propagate as normal CompositionError.
    """


class LazyConstructable:
    """Deferred construction marker for !define with type tags.
    NOT a proxy; resolved by the interpolation engine before user code sees it."""

    __slots__ = ('_node', '_loader', '_source', '_result', '_post_process', '_defined_vars', '_resolving')

    def __init__(self, node, loader, source=None, defined_vars=None, post_process=None):
        self._node = node
        self._loader = loader
        self._source = source
        self._result = _LC_SENTINEL
        self._post_process = post_process
        self._defined_vars = defined_vars
        self._resolving = False

    def resolve(self) -> Any:
        if self._result is not _LC_SENTINEL:
            return self._result

        from dracon.composer import CompositionResult, walk_node
        from dracon.diagnostics import CompositionError
        from dracon.merge import add_to_context, cached_merge_key
        from functools import partial

        if self._resolving:
            raise CompositionError(
                f"circular dependency: !define at {self._source} "
                f"triggers construction of itself"
            )
        self._resolving = True
        try:
            comp = CompositionResult(root=self._node)
            if self._defined_vars:
                # existing-wins: node contexts already carry authoritative
                # bindings (from outer !define / loader.context / CLI);
                # defined_vars is only here to RESTORE siblings that were not
                # present in the original node context, not to CLOBBER them.
                walk_node(
                    comp.root,
                    partial(
                        add_to_context,
                        self._defined_vars,
                        merge_key=cached_merge_key('<<{>~}[>~]'),
                    ),
                )
            self._result = self._loader.load_composition_result(comp)
            if self._post_process is not None:
                self._result = self._post_process(self._result)
            return self._result
        except Exception as e:
            # during composition, a failure may be transient: an unresolved
            # tag could become available after includes/merges run. Signal
            # "retry later" instead of burning the call stack with a real
            # error. Outside the composition phase, fail loud.
            if getattr(self._loader, '_composition_phase', False):
                raise LazyResolutionPending(e) from e
            tag = getattr(self._node, 'tag', '?')
            raise CompositionError(
                f"error constructing {tag} "
                f"(defined at {self._source})"
            ) from e
        finally:
            self._resolving = False

    def __deepcopy__(self, memo):
        clone = LazyConstructable.__new__(LazyConstructable)
        memo[id(self)] = clone
        clone._node = deepcopy(self._node, memo)
        clone._loader = self._loader
        clone._source = self._source
        clone._result = _LC_SENTINEL
        clone._post_process = self._post_process
        clone._defined_vars = self._defined_vars
        clone._resolving = False
        return clone

    def __repr__(self):
        tag = getattr(self._node, 'tag', '?')
        resolved = self._result is not _LC_SENTINEL
        return f"LazyConstructable({tag}, resolved={resolved})"


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


_IDENT_RE = re.compile(r'\b([a-zA-Z_][a-zA-Z0-9_]*)\b')


def _extract_identifiers(expr: str) -> set:
    """extract potential variable names from an expression using simple regex."""
    return set(_IDENT_RE.findall(expr))


def _analyze_eval_error(expr: str, error: Exception, symbols: Optional[dict]) -> str:
    """Analyze an evaluation error and produce a helpful hint."""
    error_msg = str(error)
    hints = []

    # pattern: 'X' object has no attribute 'Y'
    attr_match = re.search(r"'(\w+)' object has no attribute '(\w+)'", error_msg)
    if attr_match:
        obj_type, attr_name = attr_match.groups()
        # find which variable in the expression has this type
        if symbols:
            for var_name, var_val in symbols.items():
                if var_name.startswith('_'):
                    continue
                if type(var_val).__name__ == obj_type:
                    # check if this variable is used with .attr_name in the expression
                    if re.search(rf'\b{re.escape(var_name)}\.{re.escape(attr_name)}\b', expr):
                        if isinstance(var_val, (list, tuple)):
                            hints.append(f"'{var_name}' is a {obj_type} with {len(var_val)} item(s), not a single object")
                            hints.append(f"Try: '{var_name}[0].{attr_name}' to access the first item, or use !each to iterate")
                        else:
                            hints.append(f"'{var_name}' is a {obj_type} which doesn't have attribute '{attr_name}'")
                        break

    # pattern: name 'X' is not defined
    undef_match = _UNDEF_NAME_RE.search(error_msg)
    if undef_match:
        var_name = undef_match.group(1)
        hints.append(f"Variable '{var_name}' is not defined in this context")
        if symbols:
            # suggest similar names
            similar = [k for k in symbols.keys() if not k.startswith('_') and (var_name.lower() in k.lower() or k.lower() in var_name.lower())]
            if similar:
                hints.append(f"Did you mean: {', '.join(similar[:3])}?")

    # pattern: list indices must be integers or slices, not str
    if "list indices must be integers" in error_msg and "not str" in error_msg:
        hints.append("You're trying to use a string key on a list (which requires integer indices)")
        hints.append("Check if you meant to access a dict or need to use an integer index")

    # pattern: 'NoneType' object ...
    if "'NoneType' object" in error_msg:
        hints.append("A value in the expression is None - check if a variable failed to load or is missing")

    return "\n".join(hints) if hints else ""


@ftrace(watch=[], inputs=['expr'])
def do_safe_eval(expr: str, engine: str, symbols: Optional[dict] = None, source_context: Optional[SourceContext] = None, permissive: bool = False) -> Any:
    original_expr = expr
    expr = preprocess_expr(expr)

    # pre-access symbols that appear in the expression to trigger tracking
    # this ensures accesses are recorded before copying to eval namespace
    # resolve any lazy symbols so the eval engine gets concrete values
    if symbols is not None:
        identifiers = _extract_identifiers(expr)
        for ident in identifiers:
            if ident in symbols and not ident.startswith('__'):
                val = symbols.get(ident)  # triggers TrackedContext tracking
                if isinstance(val, (LazyConstructable, LazyProtocol)):
                    symbols[ident] = val.resolve()

    try:
        return _do_safe_eval_engine(expr, engine, symbols, source_context, original_expr)
    except UndefinedNameError:
        if not permissive:
            raise
        folded = fold_known_vars(expr, symbols or {})
        if folded != expr:
            return PartiallyResolved(folded)
        return UNRESOLVED_SENTINEL


_asteval_proto: Optional[Interpreter] = None
_asteval_base_symtable: Optional[dict] = None
_asteval_depth: int = 0  # reentrancy depth counter


def _get_asteval_proto() -> tuple[Interpreter, dict]:
    """lazily create a reusable asteval prototype interpreter + base symtable."""
    global _asteval_proto, _asteval_base_symtable
    if _asteval_proto is None:
        _asteval_proto = Interpreter(max_string_length=1000)
        _asteval_base_symtable = dict(_asteval_proto.symtable)
    return _asteval_proto, _asteval_base_symtable


def _asteval_eval(expr: str, symbols: Optional[dict]) -> Any:
    """eval an expression reusing a single Interpreter prototype (5x faster).
    Falls back to fresh Interpreter on reentrant calls to avoid symtable corruption."""
    global _asteval_depth
    _asteval_depth += 1
    try:
        if _asteval_depth > 1:
            # reentrant: fall back to fresh instance to avoid symtable clobber
            interp = Interpreter(user_symbols=symbols or {}, max_string_length=1000)
            return interp.eval(expr, raise_errors=True)
        proto, base = _get_asteval_proto()
        proto.symtable.clear()
        proto.symtable.update(base)
        if symbols:
            proto.symtable.update(symbols)
        proto.error = []
        proto.retval = None
        proto.expr = None
        proto._calldepth = 0
        proto.lineno = 0
        return proto.eval(expr, raise_errors=True)
    finally:
        _asteval_depth -= 1


def _do_safe_eval_engine(expr: str, engine: str, symbols: Optional[dict], source_context: Optional[SourceContext], original_expr: str) -> Any:
    if engine == 'asteval':
        try:
            res = _asteval_eval(expr, symbols)
        except Exception as e:
            # detect undefined name errors before generic handling
            if isinstance(e, NameError):
                m = _UNDEF_NAME_RE.search(str(e))
                if m:
                    raise UndefinedNameError(m.group(1), context=source_context, cause=e, expression=original_expr, available_symbols=symbols) from e
            hint = _analyze_eval_error(expr, e, symbols)
            # asteval populates error list even when raising - extract location info
            proto, _ = _get_asteval_proto()
            error_location = ""
            if proto.error:
                err_holder = proto.error[0]
                if err_holder.node and hasattr(err_holder.node, 'col_offset'):
                    col = err_holder.node.col_offset
                    end_col = getattr(err_holder.node, 'end_col_offset', col + 1)
                    # create a visual pointer to the error location
                    error_location = f"\n  {expr}\n  {' ' * col}{'^' * (end_col - col)}"
            msg = f"Error evaluating expression: {e}"
            if error_location:
                msg += error_location
            if hint:
                msg += f"\n\nHint:\n{hint}"
            raise EvaluationError(msg, context=source_context, cause=e, expression=original_expr, available_symbols=symbols) from e

        proto, _ = _get_asteval_proto()
        if proto.error:
            errormsg = '\n'.join(': '.join(e.get_error()) for e in proto.error)
            raise EvaluationError(f"Expression evaluation failed:\n{errormsg}", context=source_context, expression=original_expr, available_symbols=symbols)
        return res

    elif engine == 'eval':
        try:
            eval_globals = {}
            eval_globals.update(__builtins__)  # type: ignore
            eval_globals.update(symbols or {})
            # compile with meaningful identifier for better tracebacks
            identifier = "<dracon expression>"
            if source_context:
                import os
                # try to get a real filename (not <unicode string>)
                file_path = source_context.file_path
                if file_path and file_path.startswith('<') and source_context.include_trace:
                    # use the last entry in include_trace that has a real path
                    for loc in reversed(source_context.include_trace):
                        if loc.file_path and not loc.file_path.startswith('<'):
                            file_path = loc.file_path
                            break
                if file_path and not file_path.startswith('<'):
                    filename = os.path.basename(file_path)
                    identifier = f"<expr in {filename}:{source_context.line}>"
                elif source_context.line:
                    identifier = f"<expr at line {source_context.line}>"
            code_obj = compile(expr, identifier, 'eval')
            return eval(code_obj, eval_globals)
        except SyntaxError as e:
            # syntax errors have offset info
            error_location = ""
            if e.text and e.offset:
                error_location = f"\n  {e.text.rstrip()}\n  {' ' * (e.offset - 1)}^"
            msg = f"Syntax error in expression: {e.msg}"
            if error_location:
                msg += error_location
            raise EvaluationError(msg, context=source_context, cause=e, expression=original_expr, available_symbols=symbols) from e
        except Exception as e:
            # detect undefined name errors before generic handling
            if isinstance(e, NameError):
                name = getattr(e, 'name', None)
                if name:
                    raise UndefinedNameError(name, context=source_context, cause=e, expression=original_expr, available_symbols=symbols) from e
            hint = _analyze_eval_error(expr, e, symbols)
            msg = f"Error evaluating expression: {e}"
            if hint:
                msg += f"\n\nHint:\n{hint}"
            raise EvaluationError(msg, context=source_context, cause=e, expression=original_expr, available_symbols=symbols) from e
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

    # add dracon-specific internal symbols (always override)
    symbols["__DRACON__CURRENT_PATH"] = current_path
    symbols["__DRACON__PARENT_PATH"] = current_path.parent
    symbols["__DRACON__CURRENT_ROOT_OBJ"] = root_obj
    symbols["__DRACON_RESOLVE"] = dracon_resolve
    symbols["__dracon_KeyPath"] = KeyPath

    # add base symbols only if not already in context
    for k, v in BASE_DRACON_SYMBOLS.items():
        if k not in symbols:
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
    permissive: bool = False,
    _unescape_result: bool = True,
) -> Any:
    from dracon.merge import merged, cached_merge_key

    if enable_shorthand_vars:
        expr = transform_dollar_vars(expr)

    if init_outermost_interpolations is None:
        interpolations = outermost_interpolation_exprs(expr)
    else:
        interpolations = init_outermost_interpolations

    if not interpolations:
        if _unescape_result and isinstance(expr, str):
            return unescape_dracon_specials(expr)
        return expr

    if isinstance(current_path, str):
        current_path = KeyPath(current_path)

    symbols = prepare_symbols(current_path, root_obj, context)

    def recurse_lazy_resolve(expr):
        if isinstance(expr, LazyProtocol):
            expr.current_path = current_path
            expr.root_obj = root_obj
            expr.context = merged(expr.context, context, cached_merge_key('{<+}'))
            expr = expr.resolve()
        return expr

    made_progress = False

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
            permissive=permissive,
            _unescape_result=False,
        )
        evaluated_expr = do_safe_eval(str(resolved_expr), engine, symbols, source_context, permissive=permissive)
        if evaluated_expr is UNRESOLVED_SENTINEL:
            endexpr = expr  # leave ${...} as-is
        elif isinstance(evaluated_expr, PartiallyResolved):
            endexpr = '${' + evaluated_expr.expr + '}'
            made_progress = True
        else:
            endexpr = recurse_lazy_resolve(evaluated_expr)
            made_progress = True
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
                permissive=permissive,
                _unescape_result=False,
            )
            evaluated_expr = do_safe_eval(str(resolved_expr), engine, symbols, source_context, permissive=permissive)
            if evaluated_expr is UNRESOLVED_SENTINEL:
                continue  # leave this ${...} block as-is
            elif isinstance(evaluated_expr, PartiallyResolved):
                newexpr = '${' + evaluated_expr.expr + '}'
                made_progress = True
            else:
                newexpr = str(recurse_lazy_resolve(evaluated_expr))
                made_progress = True
            expr = expr[: match.start + offset] + newexpr + expr[match.end + offset :]
            offset += len(newexpr) - (match.end - match.start)
        endexpr = expr

    # short-circuit recursion if permissive and no progress made
    if permissive and not made_progress:
        if _unescape_result and type(endexpr) is str:
            return unescape_dracon_specials(endexpr)
        return endexpr

    # only recurse / unescape plain str, never str subclasses (e.g. RawExpression).
    # type() is str fails closed: marked strings are automatically excluded.
    if allow_recurse != 0 and type(endexpr) is str and '${' in endexpr:
        return evaluate_expression(
            endexpr,
            current_path,
            root_obj,
            allow_recurse=allow_recurse - 1,
            engine=engine,
            context=context,
            enable_shorthand_vars=enable_shorthand_vars,
            source_context=source_context,
            permissive=permissive,
            _unescape_result=_unescape_result,
        )
    if _unescape_result and type(endexpr) is str:
        endexpr = unescape_dracon_specials(endexpr)
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

    def evaluate(self, path='/', root_obj=None, engine=DEFAULT_EVAL_ENGINE, context=None, permissive=False):
        context = context or {}
        context = {**self.context, **context}
        newval = evaluate_expression(
            self.value,
            current_path=path,
            root_obj=root_obj,
            engine=engine,
            context=context,  # type: ignore
            source_context=self.source_context,
            permissive=permissive,
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
            # else: @/& outside ${...} — literal text, not a reference

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
