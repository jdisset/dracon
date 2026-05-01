"""Tests that container access paths consistently resolve lazies.

Bug: see bugs/_archive/lazy-leak-on-non-getitem-container-access.md.
Only Mapping.__getitem__ used to resolve LazyInterpolable values.
Mapping.get/.values/.items/iteration and Sequence iteration leaked
raw wrappers when called from native Python (e.g. inside ${...}
helper callables). Default-tagged sequences were also constructed as
plain `list` instead of `Sequence`, so even __getitem__ leaked there.
"""

import dracon
from dracon.dracontainer import Mapping, Sequence
from dracon.lazy import LazyInterpolable


def _tname(x):
    return type(x).__name__


def _tnames(xs):
    return [type(x).__name__ for x in xs]


def _items_tnames(m):
    return [(k, type(v).__name__) for k, v in m.items()]


CTX = {
    'tname': _tname,
    'tnames': _tnames,
    'items_tnames': _items_tnames,
}


# ── Mapping access paths ──────────────────────────────────────────────


def test_mapping_getitem_resolves():
    out = dracon.loads(
        """
!set_default x: 10.0
!define m:
  a: ${x}
out: ${tname(m['a'])}
""",
        context=CTX,
    )
    assert out['out'] == 'float'


def test_mapping_get_returns_default_unmodified():
    """`.get(missing, default)` must return default as-is — stdlib semantics.

    Note: `.get()` is intentionally NOT overridden to resolve lazies —
    pydantic-core's Rust validator walks model inputs via `.get()` and
    expects raw `LazyInterpolable` objects so the Lazy[T] field
    validator can wrap them. Use `m[key]` for resolved single-key access.
    """
    sentinel = object()

    def is_sentinel(x):
        return x is sentinel

    out = dracon.loads(
        """
!set_default x: 10.0
!define m:
  a: ${x}
out: ${is_sentinel(m.get('missing', sentinel))}
""",
        context={'sentinel': sentinel, 'is_sentinel': is_sentinel},
    )
    assert out['out'] is True


def test_mapping_values_resolves():
    out = dracon.loads(
        """
!set_default x: 10.0
!define m:
  a: ${x}
  b: ${x}
out: ${tnames(list(m.values()))}
""",
        context=CTX,
    )
    assert out['out'] == ['float', 'float']


def test_mapping_items_resolves():
    out = dracon.loads(
        """
!set_default x: 10.0
!define m:
  a: ${x}
out: ${items_tnames(m)}
""",
        context=CTX,
    )
    assert out['out'] == [('a', 'float')]


def test_mapping_iter_via_keys_works():
    def via_keys(m):
        return [type(m[k]).__name__ for k in m]

    out = dracon.loads(
        """
!set_default x: 10.0
!define m:
  a: ${x}
out: ${via_keys(m)}
""",
        context={'via_keys': via_keys},
    )
    assert out['out'] == ['float']


def test_mapping_consume_pattern_works():
    """The realistic failure mode from the bug report."""

    def consume(m):
        return [float(v) for v in m.values()]

    out = dracon.loads(
        """
!set_default x: 10.0
!define m:
  a: ${x}
  b: ${x}
out: ${consume(m)}
""",
        context={'consume': consume},
    )
    assert out['out'] == [10.0, 10.0]


# ── Sequence access paths ─────────────────────────────────────────────


def test_sequence_getitem_resolves():
    out = dracon.loads(
        """
!set_default x: 10.0
!define s:
  - ${x}
out: ${tname(s[0])}
""",
        context=CTX,
    )
    assert out['out'] == 'float'


def test_sequence_iter_resolves():
    out = dracon.loads(
        """
!set_default x: 10.0
!define s:
  - ${x}
  - ${x}
out: ${tnames(list(s))}
""",
        context=CTX,
    )
    assert out['out'] == ['float', 'float']


def test_sequence_consume_pattern_works():
    def consume(s):
        return [float(v) for v in s]

    out = dracon.loads(
        """
!set_default x: 10.0
!define s:
  - ${x}
  - ${x}
out: ${consume(s)}
""",
        context={'consume': consume},
    )
    assert out['out'] == [10.0, 10.0]


# ── construct_sequence wraps in Sequence (SSOT with construct_mapping) ─


def test_default_tagged_sequence_is_sequence_type():
    """A default-tagged YAML sequence should round-trip into a dracon
    Sequence, mirroring the way default-tagged mappings become a Mapping.
    Otherwise lazy resolution can never apply on the !define-bound value."""

    out = dracon.loads(
        """
!set_default x: 10.0
!define s:
  - ${x}
out: ${tname(s)}
""",
        context=CTX,
    )
    assert out['out'] == 'Sequence'


def test_default_tagged_mapping_is_mapping_type():
    out = dracon.loads(
        """
!set_default x: 10.0
!define m:
  a: ${x}
out: ${tname(m)}
""",
        context=CTX,
    )
    assert out['out'] == 'Mapping'


# ── direct unit tests on the container types ──────────────────────────


_LAZY_EXPR = '${7}'


def test_unit_mapping_values_resolves():
    m = Mapping()
    dict.__setitem__(m, 'k', LazyInterpolable(value=_LAZY_EXPR))
    vs = list(m.values())
    assert all(not isinstance(v, LazyInterpolable) for v in vs)
    assert vs == [7]


def test_unit_mapping_items_resolves():
    m = Mapping()
    dict.__setitem__(m, 'k', LazyInterpolable(value=_LAZY_EXPR))
    its = list(m.items())
    assert its == [('k', 7)]


def test_unit_sequence_iter_resolves():
    s = Sequence()
    list.append(s, LazyInterpolable(value=_LAZY_EXPR))
    out = list(s)
    assert out == [7]
    assert all(not isinstance(v, LazyInterpolable) for v in out)


def test_unit_raw_data_view_still_bypasses():
    """`_data` is the SSOT escape hatch for raw access (representer relies
    on it). It must NOT resolve lazies."""
    m = Mapping()
    lazy = LazyInterpolable(value=_LAZY_EXPR)
    dict.__setitem__(m, 'k', lazy)
    raw = m._data['k']
    assert isinstance(raw, LazyInterpolable)
    raw_vals = list(m._data.values())
    assert isinstance(raw_vals[0], LazyInterpolable)


def test_unit_disabled_lazy_resolve_passes_through():
    """When _dracon_lazy_resolve=False, all access paths should
    return the raw lazy (escape hatch for resolution machinery)."""
    m = Mapping()
    dict.__setitem__(m, 'k', LazyInterpolable(value=_LAZY_EXPR))
    m._dracon_lazy_resolve = False
    assert isinstance(m['k'], LazyInterpolable)
    assert all(isinstance(v, LazyInterpolable) for v in m.values())
    assert all(isinstance(v, LazyInterpolable) for _, v in m.items())
