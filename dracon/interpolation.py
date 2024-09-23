from asteval import Interpreter
from typing import (
    Any,
    Dict,
    Optional,
    List,
)
from dracon.keypath import KeyPath
from copy import copy
from typing import Protocol, runtime_checkable, Optional
from dracon.merge import merged, MergeKey
from dracon.interpolation_utils import (
    outermost_interpolation_exprs,
    InterpolationMatch,
    find_field_references,
    resolve_interpolable_variables,
)


class InterpolationError(Exception):
    pass


BASE_DRACON_SYMBOLS: Dict[str, Any] = {}

## {{{                           --     eval utils    --


@runtime_checkable
class LazyProtocol(Protocol):
    def resolve(self) -> Any: ...

    def get(self, owner_instance, setval=False) -> Any: ...

    name: str
    current_path: KeyPath
    root_obj: Any
    extra_symbols: Dict[str, Any]


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
            raise ValueError(f"Ampersand references in {expr} should have been handled earlier")
        else:
            raise ValueError(f"Invalid symbol {match.symbol} in {expr}")

        expr = expr[: match.start + offset] + newexpr + expr[match.end + offset :]
        original_len = match.end - match.start
        offset += len(newexpr) - original_len
    return expr


def preprocess_expr(expr: str, symbols: Optional[dict] = None):
    expr = resolve_field_references(expr)
    expr = resolve_interpolable_variables(expr, symbols or {})
    return expr


def do_safe_eval(expr: str, symbols: Optional[dict] = None):
    expr = preprocess_expr(expr, symbols)
    safe_eval = Interpreter(user_symbols=symbols or {}, max_string_length=1000)
    return safe_eval.eval(expr, raise_errors=True)


def prepare_symbols(current_path, root_obj, extra_symbols):
    symbols = copy(BASE_DRACON_SYMBOLS)
    symbols.update(
        {
            "__DRACON__CURRENT_PATH": current_path,
            "__DRACON__PARENT_PATH": current_path.parent,
            "__DRACON__CURRENT_ROOT_OBJ": root_obj,
            "__dracon_KeyPath": KeyPath,
        }
    )
    symbols.update(extra_symbols or {})
    return symbols


##────────────────────────────────────────────────────────────────────────────}}}

## {{{                     --     evaluate expression   --


def evaluate_expression(
    expr: str,
    current_path: str | KeyPath = '/',
    root_obj: Any = None,
    allow_recurse: int = 5,
    init_outermost_interpolations: Optional[List[InterpolationMatch]] = None,
    extra_symbols: Optional[Dict[str, Any]] = None,
) -> Any:
    # Initialize interpolations
    if init_outermost_interpolations is None:
        interpolations = outermost_interpolation_exprs(expr)
    else:
        interpolations = init_outermost_interpolations

    # Return the expression if there are no interpolations
    if not interpolations:
        return expr

    # Ensure current_path is a KeyPath instance
    if isinstance(current_path, str):
        current_path = KeyPath(current_path)

    # Prepare symbols for evaluation
    symbols = copy(BASE_DRACON_SYMBOLS)
    symbols.update(
        {
            "__DRACON__CURRENT_PATH": current_path,
            "__DRACON__PARENT_PATH": current_path.parent,
            "__DRACON__CURRENT_ROOT_OBJ": root_obj,
            "__dracon_KeyPath": KeyPath,
        }
    )
    symbols.update(extra_symbols or {})

    # Helper function to resolve Lazy instances
    def recurse_lazy_resolve(expr):
        if isinstance(expr, LazyProtocol):
            expr.current_path = current_path
            expr.root_obj = root_obj
            expr.extra_symbols = merged(expr.extra_symbols, extra_symbols, MergeKey(raw='{<+}'))
            expr = expr.resolve()
        return expr

    # Check if the entire expression is a single interpolation
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
            extra_symbols=extra_symbols,
        )
        evaluated_expr = do_safe_eval(str(resolved_expr), symbols)
        endexpr = recurse_lazy_resolve(evaluated_expr)
    else:
        # Process and replace each interpolation within the expression
        offset = 0
        for match in interpolations:
            resolved_expr = evaluate_expression(
                match.expr,
                current_path,
                root_obj,
                allow_recurse=allow_recurse,
                extra_symbols=extra_symbols,
            )
            evaluated_expr = do_safe_eval(str(resolved_expr), symbols)
            newexpr = str(recurse_lazy_resolve(evaluated_expr))
            expr = expr[: match.start + offset] + newexpr + expr[match.end + offset :]
            offset += len(newexpr) - (match.end - match.start)
        endexpr = expr

    # Recurse if allowed and necessary
    if allow_recurse != 0 and isinstance(endexpr, str):
        return evaluate_expression(endexpr, current_path, root_obj, allow_recurse=allow_recurse - 1)
    return endexpr


##────────────────────────────────────────────────────────────────────────────}}}
