# Copyright (c) 2025 Jean Disset
# MIT License - see LICENSE file for details.

"""CLI-visible directive records.

`!require` and `!set_default` are context contracts. With a mapping body
they also carry CLI metadata (help, short, default, hidden). This module
owns the shared parser. The record type itself lives in `cli_param.py`
as the unified `CliParam`; `CliDirective` is a factory back-compat alias.
"""

from __future__ import annotations

from typing import Any, Optional

from dracon.cli_param import CliDirective, CliParam, DeclKind
from dracon.diagnostics import CompositionError, SourceContext
from dracon.nodes import node_source


def _node_source_with_file(node) -> Optional[SourceContext]:
    """Like ``node_source``, but enriches ``<unicode string>`` source paths
    with the node's ``FILE_PATH`` / ``FILE`` context — the actual layered file
    is what we want to surface in help output, not the in-memory stream."""
    src = node_source(node) if node is not None else None
    if src is None or src.file_path not in ('<unicode string>', '<unknown>'):
        return src
    fp = (getattr(node, 'context', None) or {}).get('FILE_PATH') \
        or (getattr(node, 'context', None) or {}).get('FILE')
    if not fp:
        return src
    return SourceContext(
        file_path=fp, line=src.line, column=src.column,
        keypath=src.keypath, include_trace=src.include_trace,
        operation_context=src.operation_context,
    )

# allowed body keys per kind. SSOT for grammar validation.
_REQUIRE_KEYS = frozenset({"help", "short", "hidden"})
_SET_DEFAULT_KEYS = frozenset({"help", "short", "hidden", "default"})


def _normalise_short(raw: Any, key_node) -> Optional[str]:
    """Accept `-p` or `p`, reject `--port`, `--`, multi-char, empty."""
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise CompositionError(
            f"`short` must be a string, got {type(raw).__name__}",
            context=node_source(key_node),
        )
    s = raw.strip()
    if s.startswith("--"):
        raise CompositionError(
            f"`short` must be a single-dash flag like `-p`, got {raw!r}",
            context=node_source(key_node),
        )
    if s.startswith("-"):
        s = s[1:]
    if len(s) != 1:
        raise CompositionError(
            f"`short` must be exactly one character, got {raw!r}",
            context=node_source(key_node),
        )
    return f"-{s}"


def _coerce_default(value: Any, python_type: Optional[type], key_node) -> Any:
    """Apply primitive coercion when a typed directive carries one."""
    if python_type is None or value is None:
        return value
    if isinstance(value, python_type):
        return value
    try:
        return python_type(value)
    except (TypeError, ValueError) as e:
        raise CompositionError(
            f"cannot coerce default {value!r} to {python_type.__name__}",
            context=node_source(key_node),
        ) from e


_YAML_SCALAR_COERCE = {
    "tag:yaml.org,2002:int": int,
    "tag:yaml.org,2002:float": float,
    "tag:yaml.org,2002:bool": lambda v: str(v).strip().lower() in ("true", "yes", "on"),
    "tag:yaml.org,2002:null": lambda v: None,
}


def _scalar_value(value_node) -> Any:
    """Pull the python value out of a scalar node, applying YAML scalar tag
    coercion for typed forms (int/float/bool/null)."""
    if not hasattr(value_node, "value"):
        return value_node
    raw = value_node.value
    coerce = _YAML_SCALAR_COERCE.get(getattr(value_node, "tag", None))
    if coerce is None:
        return raw
    try:
        return coerce(raw)
    except (TypeError, ValueError):
        return raw


def _is_mapping_body(value_node) -> bool:
    # local import to avoid pulling composer at module-import time
    from dracon.composer import DraconMappingNode
    return isinstance(value_node, DraconMappingNode)


def parse_directive_body(
    var_name: str,
    value_node,
    kind: DeclKind,
    python_type: Optional[type],
    key_node=None,
) -> tuple[CliParam, Any]:
    """Parse the body of `!require` / `!set_default` into a `CliParam`.

    Returns `(param, scalar_value)` where `scalar_value` carries the
    legacy scalar semantics for the caller:

      - `!require`        -> the hint string (may be ``""``)
      - `!set_default`    -> the default value (already coerced if typed)

    `scalar_value` is also derived from the mapping body when present
    (`body['help']` for `!require`, `body['default']` for `!set_default`).
    """
    src = _node_source_with_file(key_node)

    if _is_mapping_body(value_node):
        body = _read_mapping_body(value_node, kind)
        help_str = body.get("help")
        short = _normalise_short(body.get("short"), key_node)
        hidden = bool(body.get("hidden", False))

        if kind == "require":
            scalar = help_str or ""
            param = CliDirective(
                name=var_name, kind=kind,
                help=help_str, short=short, hidden=hidden,
                python_type=python_type, source_context=src,
            )
        else:
            default = _coerce_default(body.get("default"), python_type, key_node)
            scalar = default
            param = CliDirective(
                name=var_name, kind=kind,
                help=help_str, short=short, hidden=hidden,
                default=default, python_type=python_type, source_context=src,
            )
        return param, scalar

    # scalar body: legacy meaning
    raw = _scalar_value(value_node)
    if kind == "require":
        hint = raw if isinstance(raw, str) else ("" if raw is None else str(raw))
        param = CliDirective(
            name=var_name, kind=kind,
            help=hint or None, python_type=python_type, source_context=src,
        )
        return param, hint

    # set_default scalar: defer coercion to the caller's existing path so
    # interpolations / nested types keep working. We don't pre-coerce here.
    param = CliDirective(
        name=var_name, kind=kind,
        help=None,
        default=raw if not hasattr(value_node, "value") else None,
        python_type=python_type, source_context=src,
    )
    return param, raw


def _read_mapping_body(value_node, kind: DeclKind) -> dict[str, Any]:
    """Walk a mapping body, validate keys, return a plain dict.

    Forbids unknown keys and the `!require` + `default` combination.
    """
    allowed = _REQUIRE_KEYS if kind == "require" else _SET_DEFAULT_KEYS
    out: dict[str, Any] = {}
    for k_node, v_node in value_node.value:
        key = getattr(k_node, "value", None)
        if not isinstance(key, str):
            raise CompositionError(
                f"`!{kind}` body keys must be strings, got {type(key).__name__}",
                context=node_source(k_node),
            )
        if key not in allowed:
            if kind == "require" and key == "default":
                raise CompositionError(
                    "`!require` cannot carry a `default`. A required variable "
                    "has no default by definition.",
                    context=node_source(k_node),
                )
            raise CompositionError(
                f"unknown key `{key}` in `!{kind}` body. "
                f"Allowed keys: {', '.join(sorted(allowed))}",
                context=node_source(k_node),
            )
        out[key] = _scalar_value(v_node)
    return out


__all__ = ["CliDirective", "DeclKind", "parse_directive_body"]
