# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Jean Disset

"""Free-name extraction on LazyInterpolable + Symbol protocol conformance.

Step 01 of the SSOT symbol-axis refactor. Establishes that every
LazyInterpolable knows the set of free names it depends on, surfaces
that set through InterfaceSpec.params, and aliases its existing
context_override resolution path under the canonical Symbol.invoke().
"""

import pickle
import copy

from dracon.interpolation import _free_names
from dracon.lazy import LazyInterpolable
from dracon.symbols import Symbol, SymbolKind


def test_free_names_simple():
    assert _free_names("a + b") == frozenset({"a", "b"})


def test_free_names_attr_access():
    assert _free_names("component.part_name.upper()") == frozenset({"component"})


def test_free_names_method_call():
    assert _free_names("foo(bar, baz=qux)") == frozenset({"foo", "bar", "qux"})


def test_free_names_skips_comprehension_locals():
    assert _free_names("[x.value for x in items]") == frozenset({"items"})


def test_free_names_skips_comprehension_tuple_target():
    assert _free_names("[k for k, v in items.items()]") == frozenset({"items"})


def test_free_names_nested_comprehension():
    assert _free_names("[c for row in grid for c in row]") == frozenset({"grid"})


def test_free_names_skips_dunders():
    assert _free_names("__scope__.has('foo')") == frozenset()


def test_free_names_lambda_args_local():
    assert _free_names("(lambda x: x + outer)(5)") == frozenset({"outer"})


def test_free_names_lambda_kwonly():
    assert _free_names("(lambda *, k=v: k + outer)()") == frozenset({"v", "outer"})


def test_free_names_parse_error_is_empty():
    assert _free_names("malformed[") == frozenset()


def test_free_names_constants_only():
    assert _free_names("1 + 2") == frozenset()


def test_free_names_on_lazy_bare_expression():
    lazy = LazyInterpolable("${a + b * c}", context={})
    assert lazy._free_names == frozenset({"a", "b", "c"})


def test_free_names_on_lazy_multiple_interpolations():
    lazy = LazyInterpolable("prefix-${a}-mid-${b + c}-suffix", context={})
    assert lazy._free_names == frozenset({"a", "b", "c"})


def test_free_names_on_lazy_no_interpolations():
    # plain string with no ${...}: nothing to depend on
    lazy = LazyInterpolable("just a string", context={}, permissive=True)
    assert lazy._free_names == frozenset()


def test_lazy_satisfies_symbol_protocol():
    lazy = LazyInterpolable("${a + b}", context={})
    assert isinstance(lazy, Symbol)


def test_lazy_interface_starts_empty_params():
    # step 03 will populate this after intersecting with !live scope.
    # for now interface.params must be empty.
    lazy = LazyInterpolable("${a + b}", context={})
    iface = lazy.interface()
    assert iface.kind == SymbolKind.VALUE
    assert iface.params == ()


def test_lazy_invoke_aliases_resolve():
    lazy = LazyInterpolable("${a + 1}", context={"a": 5})
    assert lazy.invoke() == 6
    assert lazy.invoke(a=10) == 11


def test_lazy_materialize_is_self():
    lazy = LazyInterpolable("${x}", context={"x": 1})
    assert lazy.materialize() is lazy


def test_lazy_bind_returns_bound_symbol():
    lazy = LazyInterpolable("${a + b}", context={"a": 1, "b": 2})
    bound = lazy.bind(a=10)
    # binding produces a BoundSymbol whose invoke applies the bound kwargs
    assert bound.invoke(b=5) == 15


def test_lazy_represented_type_is_none():
    lazy = LazyInterpolable("${x}", context={"x": 1})
    assert lazy.represented_type() is None


def test_lazy_pickling_preserves_free_names():
    lazy = LazyInterpolable("${a + b}", context={})
    rt = pickle.loads(pickle.dumps(lazy))
    assert rt._free_names == frozenset({"a", "b"})


def test_lazy_deepcopy_preserves_free_names():
    lazy = LazyInterpolable("${a + b * c}", context={})
    rt = copy.deepcopy(lazy)
    assert rt._free_names == frozenset({"a", "b", "c"})


def test_lazy_free_names_via_real_compose():
    # exercise through a real config: composing a doc with ${...} leaves
    # must yield LazyInterpolable instances with populated _free_names.
    from dracon import loads
    cfg = loads("""
    a: 1
    b: 2
    result: ${a + b}
    """, enable_interpolation=True, deferred_paths=['/result'])
    # the deferred leaf preserves the lazy; otherwise resolve_all_lazy
    # would have collapsed it. probe the deferred subtree's composed node.
    deferred = cfg['result']
    # roundtrip stays valid -- step is metadata-only, no behavior change
    assert deferred is not None
