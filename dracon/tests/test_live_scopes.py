# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Jean Disset

"""End-to-end live scopes: lazy carries matched scope params,
`resolve_all_lazy` skips live lazies, `invoke()` validates required
params, dump round-trips back to `!live`.

Step 03 of the SSOT symbol-axis refactor.
"""

import pytest

import dracon as dr
from dracon import DraconLoader
from dracon.lazy import LazyInterpolable, resolve_all_lazy
from dracon.interpolation import InterpolationError
from dracon.symbols import SymbolKind


def _raw(cfg, *keys):
    """walk a Mapping without triggering lazy resolution."""
    cur = cfg
    for k in keys:
        cur = dict.__getitem__(cur, k) if isinstance(cur, dict) else cur[k]
    return cur


def test_lazy_under_live_keeps_scope_params():
    cfg = dr.loads("""
!live component:
  color: ${component.kind}
  size: 42
""")
    color = _raw(cfg, 'color')
    assert isinstance(color, LazyInterpolable)
    assert color._scope_params == frozenset({'component'})
    assert _raw(cfg, 'size') == 42


def test_lazy_without_live_has_empty_scope_params():
    cfg = dr.loads("""
val: ${1 + 1}
""")
    v = _raw(cfg, 'val')
    assert isinstance(v, LazyInterpolable)
    assert v._scope_params == frozenset()


def test_resolve_all_lazy_skips_live():
    cfg = dr.loads("""
!live component:
  color: ${component.kind}
  size: 42
""")
    resolve_all_lazy(cfg)
    assert isinstance(_raw(cfg, 'color'), LazyInterpolable)
    assert _raw(cfg, 'size') == 42


def test_resolve_all_lazy_resolves_non_live_lazies():
    cfg = dr.loads("""
!live component:
  color: ${component.kind}
val: ${2 + 3}
""")
    resolve_all_lazy(cfg)
    assert isinstance(_raw(cfg, 'color'), LazyInterpolable)
    assert _raw(cfg, 'val') == 5


def test_invoke_with_live_kwargs_resolves():
    cfg = dr.loads("""
!live component:
  color: ${component.kind}
""")
    resolve_all_lazy(cfg)

    class C:
        kind = "primary"

    color = _raw(cfg, 'color')
    assert color.invoke(component=C()) == "primary"


def test_invoke_missing_param_raises_interpolation_error():
    cfg = dr.loads("""
!live component:
  color: ${component.kind}
""")
    resolve_all_lazy(cfg)
    color = _raw(cfg, 'color')
    with pytest.raises(InterpolationError, match="missing live scope"):
        color.invoke()


def test_except_for_keeps_only_intersecting_lazies_lazy():
    cfg = dr.loads("""
!live a:
  !live b:
    x: ${a + b}
    y: ${b}
    z: ${a}
""")
    # only lazies whose _scope_params intersect {'b'} stay lazy
    resolve_all_lazy(cfg, except_for={'b'}, permissive=True)
    # x has both a and b: stays lazy (intersection nonempty)
    assert isinstance(_raw(cfg, 'x'), LazyInterpolable)
    # y has only b: stays lazy
    assert isinstance(_raw(cfg, 'y'), LazyInterpolable)


def test_except_for_empty_set_resolves_everything():
    cfg = dr.loads("""
!live component:
  v: ${1 + 1}
  c: ${component.kind}
""")
    resolve_all_lazy(cfg, except_for=frozenset(), permissive=True)
    # empty set intersects nothing -> all lazies resolve eagerly
    # v has no scope_params: resolves to 2
    assert _raw(cfg, 'v') == 2


def test_nested_live_intersects_union():
    cfg = dr.loads("""
!live component:
  !live theme:
    color: ${theme.colors[component.kind]}
""")
    color = _raw(cfg, 'color')
    assert color._scope_params == frozenset({'component', 'theme'})


def test_interface_reflects_scope_params():
    cfg = dr.loads("""
!live component:
  color: ${component.kind}
""")
    color = _raw(cfg, 'color')
    iface = color.interface()
    assert iface.kind == SymbolKind.VALUE
    assert {p.name for p in iface.params} == {'component'}


def test_dump_roundtrip_live_preserves_scope_params():
    yaml_str = """!live component:
  color: ${component.kind}
"""
    cfg = dr.loads(yaml_str)
    dumped = dr.dump(cfg)
    assert '!live' in dumped
    cfg2 = dr.loads(dumped)
    color = _raw(cfg2, 'color')
    assert isinstance(color, LazyInterpolable)
    assert color._scope_params == frozenset({'component'})


def test_dump_roundtrip_multi_name_live():
    cfg = dr.loads("""
!live a, b:
  x: ${a + b}
""")
    s = dr.dump(cfg)
    assert '!live' in s
    cfg2 = dr.loads(s)
    x = _raw(cfg2, 'x')
    assert x._scope_params == frozenset({'a', 'b'})


def test_dump_mixed_live_and_plain_keys():
    cfg = dr.loads("""
plain: 1
!live component:
  c: ${component.x}
""")
    s = dr.dump(cfg)
    cfg2 = dr.loads(s)
    assert _raw(cfg2, 'plain') == 1
    assert _raw(cfg2, 'c')._scope_params == frozenset({'component'})


def test_capture_globals_does_not_shadow_live_scope():
    import sys
    mod = sys.modules[__name__]
    setattr(mod, 'component', "leaked")
    try:
        loader = DraconLoader(enable_interpolation=True, capture_globals=True)
        cfg = loader.loads("""
!live component:
  x: ${component}
""")
        # x stays lazy despite `component` being in captured globals
        x = _raw(cfg, 'x')
        assert isinstance(x, LazyInterpolable)
        assert x._scope_params == frozenset({'component'})
        # resolve_all_lazy must also leave it alone
        resolve_all_lazy(cfg)
        assert isinstance(_raw(cfg, 'x'), LazyInterpolable)
    finally:
        if hasattr(mod, 'component'):
            delattr(mod, 'component')


def test_live_lazy_in_list_value():
    cfg = dr.loads("""
!live component:
  items:
    - ${component.a}
    - 42
""")
    resolve_all_lazy(cfg)
    items = _raw(cfg, 'items')
    first = list.__getitem__(items, 0)
    second = list.__getitem__(items, 1)
    assert isinstance(first, LazyInterpolable)
    assert first._scope_params == frozenset({'component'})
    assert second == 42
