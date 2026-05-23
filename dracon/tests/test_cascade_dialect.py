# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Jean Disset

"""End-to-end tests for the unified `!cascade:NAME` instruction.

Inherit-mode dialects (e.g. built-in `strip_suffix`) and select-mode dialects
(custom predicate-keyed mappings) share one tag, one registry, one walker.
The strategy's `input_params` discriminates mode.
"""

from dataclasses import dataclass, field
from typing import Optional
import pickle

import pytest

import dracon as dr
from dracon.cascade import (
    CascadeStrategy,
    register_cascade_strategy,
    get_cascade_strategy,
    _CASCADE_STRATEGIES,
)
from dracon.symbols import CallableSymbol, SymbolKind


# ── built-in inherit-mode dialect: strip_suffix ────────────────────────────


def test_inherit_yaml_endtoend():
    yaml_str = """
cfg: !cascade:strip_suffix(_params)
  smooth_2d_params:
    draw_colorbar: true
    heatmap_params:
      contours: 0
  smooth_3d_params:
    smooth_2d_params:
      draw_colorbar: false
"""
    cfg = dr.loads(yaml_str)
    inner = cfg['cfg']['smooth_3d_params']['smooth_2d_params']
    assert inner['draw_colorbar'] is False
    assert inner['heatmap_params'] == {'contours': 0}


def test_inherit_preserves_unrelated_keys():
    yaml_str = """
cfg: !cascade:strip_suffix(_params)
  smooth_2d_params:
    x: 1
  unrelated: leave alone
"""
    cfg = dr.loads(yaml_str)
    assert cfg['cfg']['unrelated'] == 'leave alone'


def test_inherit_result_is_plain_dict():
    yaml_str = """
cfg: !cascade:strip_suffix(_params)
  a_params:
    x: 1
"""
    cfg = dr.loads(yaml_str)
    assert isinstance(cfg['cfg'], dict)
    assert not isinstance(cfg['cfg'], CallableSymbol)


# ── select-mode test dialect ────────────────────────────────────────────────


@dataclass
class DialectKey:
    type_name: str
    tag: Optional[str] = None

    @property
    def specificity(self):
        return (1 if self.tag else 0, 1)


def _parse(s):
    if ':' in s:
        t, tag = s.split(':', 1)
        return DialectKey(t, tag)
    if s and s[0].isalpha() and s.replace('_', '').isalnum():
        return DialectKey(s)
    return None


def _matches(key, comp):
    if key.type_name != comp.type:
        return False
    return key.tag is None or key.tag in comp.tags


@dataclass
class Component:
    type: str
    tags: list = field(default_factory=list)


STRATEGY = CascadeStrategy(
    name='test_dialect',
    input_params=('component',),
    parse=_parse,
    matches=_matches,
    specificity=lambda k: k.specificity,
)


def setup_module(module):
    register_cascade_strategy(STRATEGY)


def test_basic_dispatch():
    yaml_str = """
rules: !cascade:test_dialect
  Button:
    color: blue
  "Button:primary":
    color: red
"""
    cfg = dr.loads(yaml_str)
    sym = cfg['rules']
    assert isinstance(sym, CallableSymbol)
    assert sym.invoke(component=Component('Button')) == {'color': 'blue'}
    assert sym.invoke(component=Component('Button', ['primary'])) == {'color': 'red'}


def test_select_mode_specificity_ordering():
    # higher-specificity tagged key wins over plain key when both match
    yaml_str = """
rules: !cascade:test_dialect
  Button:
    a: 1
    b: 2
  "Button:primary":
    b: 99
"""
    cfg = dr.loads(yaml_str)
    sym = cfg['rules']
    out = sym.invoke(component=Component('Button', ['primary']))
    assert out == {'a': 1, 'b': 99}


def test_no_match_returns_empty():
    yaml_str = """
rules: !cascade:test_dialect
  Button:
    color: blue
"""
    cfg = dr.loads(yaml_str)
    assert cfg['rules'].invoke(component=Component('Other')) == {}


def test_match_symbol_reports_dispatch_kind():
    yaml_str = """
rules: !cascade:test_dialect
  Button:
    color: blue
"""
    cfg = dr.loads(yaml_str)
    iface = cfg['rules'].interface()
    assert iface.kind == SymbolKind.DISPATCH
    assert tuple(p.name for p in iface.params) == ('component',)


def test_cli_excludes_dispatch_param():
    # the dispatch input_param is filled by runtime code, not CLI flags;
    # CLI discovery filters DISPATCH-kind interfaces out of _CLI_FLAG_KINDS
    from dracon.cli_discovery import _CLI_FLAG_KINDS
    assert SymbolKind.DISPATCH not in _CLI_FLAG_KINDS
    # behaviour: a match symbol's interface kind is DISPATCH, so a CLI walk
    # over symbol-table contents skips its params
    yaml_str = """
rules: !cascade:test_dialect
  Button:
    color: blue
"""
    cfg = dr.loads(yaml_str)
    sym = cfg['rules']
    assert sym.interface().kind not in _CLI_FLAG_KINDS


def test_live_scope_auto_opened_for_dispatch_param():
    yaml_str = """
rules: !cascade:test_dialect
  Button:
    color: ${component.tags[0] if component.tags else 'default'}
"""
    cfg = dr.loads(yaml_str)
    result = cfg['rules'].invoke(component=Component('Button', ['warn']))
    assert result == {'color': 'warn'}


def test_strategy_not_registered_errors():
    yaml_str = """
x: !cascade:no_such_dialect
  Key: {}
"""
    with pytest.raises(Exception, match="unknown cascade strategy"):
        dr.loads(yaml_str)


def test_dump_roundtrip_select():
    yaml_str = """
rules: !cascade:test_dialect
  Button:
    color: blue
"""
    cfg = dr.loads(yaml_str)
    dumped = dr.dump(cfg)
    assert '!cascade:test_dialect' in dumped
    cfg2 = dr.loads(dumped)
    assert cfg2['rules'].invoke(component=Component('Button')) == {'color': 'blue'}


def test_dump_roundtrip_inherit():
    yaml_str = """
cfg: !cascade:strip_suffix(_params)
  a_params:
    x: 1
    a_params:
      y: 2
"""
    cfg = dr.loads(yaml_str)
    # inherit-mode resolves at compose time; dump emits plain mapping
    dumped = dr.dump(cfg)
    cfg2 = dr.loads(dumped)
    assert cfg2['cfg']['a_params']['a_params']['x'] == 1
    assert cfg2['cfg']['a_params']['a_params']['y'] == 2


def test_inherit_and_select_share_instruction():
    inherit_yaml = """
x: !cascade:strip_suffix(_p)
  a_p:
    v: 1
"""
    select_yaml = """
x: !cascade:test_dialect
  Button:
    color: blue
"""
    assert isinstance(dr.loads(inherit_yaml)['x'], dict)
    assert isinstance(dr.loads(select_yaml)['x'], CallableSymbol)


def test_invoke_missing_dispatch_param_errors():
    yaml_str = """
rules: !cascade:test_dialect
  Button:
    color: blue
"""
    cfg = dr.loads(yaml_str)
    with pytest.raises(ValueError, match="missing"):
        cfg['rules'].invoke()


def test_pickle_roundtrip_select():
    yaml_str = """
rules: !cascade:test_dialect
  Button:
    color: blue
"""
    cfg = dr.loads(yaml_str)
    sym = cfg['rules']
    blob = pickle.dumps(sym)
    sym2 = pickle.loads(blob)
    assert sym2.invoke(component=Component('Button')) == {'color': 'blue'}


def test_parametric_strip_suffix_with_custom_suffix():
    yaml_str = """
cfg: !cascade:strip_suffix(_opts)
  smooth_opts:
    x: 1
  outer_opts:
    smooth_opts:
      y: 2
"""
    cfg = dr.loads(yaml_str)
    leaf = cfg['cfg']['outer_opts']['smooth_opts']
    assert leaf['x'] == 1
    assert leaf['y'] == 2


def test_register_replaces_by_name():
    # re-register the same name with a different specificity to check last-write-wins
    alt = CascadeStrategy(
        name='replaceable_test',
        input_params=('c',),
        parse=lambda s: DialectKey(s) if s.isidentifier() else None,
        matches=lambda k, c: k.type_name == c,
        specificity=lambda k: (0,),
    )
    register_cascade_strategy(alt)
    assert get_cascade_strategy('replaceable_test') is alt
    alt2 = CascadeStrategy(
        name='replaceable_test', input_params=('c',),
        parse=alt.parse, matches=alt.matches, specificity=alt.specificity,
    )
    register_cascade_strategy(alt2)
    assert get_cascade_strategy('replaceable_test') is alt2


# ── context propagation into cascade bodies (regression tests) ──────────────
# cascade must defer past `<<(<):` so its body's `${var}` lazies see vars
# brought in by `!set_default` / `!define` from outer included files.


def test_select_body_sees_propagating_merge_setdefault(tmp_path):
    (tmp_path / 'vars.yaml').write_text('!set_default vlim_min_floor: 0.0\n')
    (tmp_path / 'theme.yaml').write_text(
        '<<(<): !include file:$DIR/vars.yaml\n'
        'rules: !cascade:test_dialect\n'
        '  Button:\n'
        '    color: ${vlim_min_floor}\n'
    )
    cfg = dr.load(str(tmp_path / 'theme.yaml'))
    out = cfg['rules'].invoke(component=Component('Button'))
    assert out == {'color': 0.0}


def test_select_body_sees_propagating_merge_define(tmp_path):
    (tmp_path / 'vars.yaml').write_text('!define accent_color: "red"\n')
    (tmp_path / 'theme.yaml').write_text(
        '<<(<): !include file:$DIR/vars.yaml\n'
        'rules: !cascade:test_dialect\n'
        '  Button:\n'
        '    color: ${accent_color}\n'
    )
    cfg = dr.load(str(tmp_path / 'theme.yaml'))
    out = cfg['rules'].invoke(component=Component('Button'))
    assert out == {'color': 'red'}


def test_select_body_sees_propagating_merge_through_selector_include(tmp_path):
    (tmp_path / 'vars.yaml').write_text('!set_default vlim_min_floor: 0.5\n')
    (tmp_path / 'theme.yaml').write_text(
        '<<(<): !include file:$DIR/vars.yaml\n'
        'rules: !cascade:test_dialect\n'
        '  Button:\n'
        '    color: ${vlim_min_floor}\n'
    )
    (tmp_path / 'user.yaml').write_text(
        '<<(<): !include file:$DIR/vars.yaml\n'
        'figure:\n'
        '  theme: !include file:$DIR/theme.yaml@rules\n'
    )
    cfg = dr.load(str(tmp_path / 'user.yaml'))
    out = cfg['figure']['theme'].invoke(component=Component('Button'))
    assert out == {'color': 0.5}


def test_inherit_body_sees_propagating_merge_setdefault(tmp_path):
    (tmp_path / 'vars.yaml').write_text('!set_default cb_value: true\n')
    (tmp_path / 'cfg.yaml').write_text(
        '<<(<): !include file:$DIR/vars.yaml\n'
        'cfg: !cascade:strip_suffix(_params)\n'
        '  a_params:\n'
        '    draw_colorbar: ${cb_value}\n'
        '  b_params:\n'
        '    a_params:\n'
        '      style: solid\n'
    )
    cfg = dr.load(str(tmp_path / 'cfg.yaml'))
    assert cfg['cfg']['a_params']['draw_colorbar'] is True
    assert cfg['cfg']['b_params']['a_params']['draw_colorbar'] is True
    assert cfg['cfg']['b_params']['a_params']['style'] == 'solid'


def test_select_body_chained_propagating_merges(tmp_path):
    (tmp_path / 'a.yaml').write_text('!set_default a_val: 1\n')
    (tmp_path / 'b.yaml').write_text(
        '<<(<): !include file:$DIR/a.yaml\n'
        '!set_default b_val: 2\n'
    )
    (tmp_path / 'theme.yaml').write_text(
        '<<(<): !include file:$DIR/b.yaml\n'
        'rules: !cascade:test_dialect\n'
        '  Button:\n'
        '    a: ${a_val}\n'
        '    b: ${b_val}\n'
    )
    cfg = dr.load(str(tmp_path / 'theme.yaml'))
    out = cfg['rules'].invoke(component=Component('Button'))
    assert out == {'a': 1, 'b': 2}


def test_select_body_propagating_merge_inside_body_still_works(tmp_path):
    # a `<<(<):` inside the body is the body's own compose problem; don't defer outer
    (tmp_path / 'shared.yaml').write_text('!set_default panel_w: 5\n')
    (tmp_path / 'theme.yaml').write_text(
        'rules: !cascade:test_dialect\n'
        '  <<(<): !include file:$DIR/shared.yaml\n'
        '  Button:\n'
        '    width: ${panel_w}\n'
    )
    cfg = dr.load(str(tmp_path / 'theme.yaml'))
    out = cfg['rules'].invoke(component=Component('Button'))
    assert out == {'width': 5}


def test_select_body_propagating_merge_no_false_defer(tmp_path):
    # sibling merge (not ancestor) must not block the cascade
    (tmp_path / 'shared.yaml').write_text('extra: hello\n')
    (tmp_path / 'theme.yaml').write_text(
        'cfg:\n'
        '  rules: !cascade:test_dialect\n'
        '    Button:\n'
        '      color: red\n'
        '  other:\n'
        '    <<(<): !include file:$DIR/shared.yaml\n'
    )
    cfg = dr.load(str(tmp_path / 'theme.yaml'))
    out = cfg['cfg']['rules'].invoke(component=Component('Button'))
    assert out == {'color': 'red'}
    assert cfg['cfg']['other']['extra'] == 'hello'


def test_select_body_propagates_cli_override(tmp_path):
    (tmp_path / 'vars.yaml').write_text('!set_default accent: "blue"\n')
    (tmp_path / 'theme.yaml').write_text(
        '<<(<): !include file:$DIR/vars.yaml\n'
        'rules: !cascade:test_dialect\n'
        '  Button:\n'
        '    color: ${accent}\n'
    )
    loader = dr.DraconLoader(context={'accent': 'green'})
    cfg = loader.load(str(tmp_path / 'theme.yaml'))
    out = cfg['rules'].invoke(component=Component('Button'))
    assert out == {'color': 'green'}


# ── peer-cascade merge (regression: same-strategy cascades on either side of a
# merge boundary must combine their rule sets, not overwrite one another) ───


def test_peer_cascade_merge_via_stack(tmp_path):
    # two files declare top-level cascades of the same strategy; stacking them
    # must yield the union of rules (later wins on conflict, both disjoint
    # selectors preserved).
    (tmp_path / 'default.yaml').write_text(
        'rules: !cascade:test_dialect\n'
        '  Button:\n'
        '    color: red\n'
        '  Link:\n'
        '    underline: true\n'
    )
    (tmp_path / 'overlay.yaml').write_text(
        'rules: !cascade:test_dialect\n'
        '  Button:\n'
        '    weight: bold\n'
    )
    loader = dr.DraconLoader()
    cfg = loader.stack(
        f"file:{tmp_path}/default.yaml",
        f"file:{tmp_path}/overlay.yaml",
    ).construct()
    sym = cfg['rules']
    assert isinstance(sym, CallableSymbol)
    # Link rule (default only) must survive
    assert sym.invoke(component=Component('Link')) == {'underline': True}
    # Button rule must contain both default's color and overlay's weight
    assert sym.invoke(component=Component('Button')) == {
        'color': 'red', 'weight': 'bold',
    }


def test_peer_cascade_merge_stack_later_wins_on_conflict(tmp_path):
    (tmp_path / 'a.yaml').write_text(
        'rules: !cascade:test_dialect\n'
        '  Button:\n'
        '    color: red\n'
    )
    (tmp_path / 'b.yaml').write_text(
        'rules: !cascade:test_dialect\n'
        '  Button:\n'
        '    color: blue\n'
    )
    loader = dr.DraconLoader()
    cfg = loader.stack(
        f"file:{tmp_path}/a.yaml",
        f"file:{tmp_path}/b.yaml",
    ).construct()
    assert cfg['rules'].invoke(component=Component('Button')) == {'color': 'blue'}


def test_peer_cascade_merge_three_layer_stack(tmp_path):
    (tmp_path / 'a.yaml').write_text(
        'rules: !cascade:test_dialect\n'
        '  Button:\n'
        '    color: red\n'
    )
    (tmp_path / 'b.yaml').write_text(
        'rules: !cascade:test_dialect\n'
        '  Link:\n'
        '    underline: true\n'
    )
    (tmp_path / 'c.yaml').write_text(
        'rules: !cascade:test_dialect\n'
        '  Button:\n'
        '    weight: bold\n'
    )
    loader = dr.DraconLoader()
    cfg = loader.stack(
        f"file:{tmp_path}/a.yaml",
        f"file:{tmp_path}/b.yaml",
        f"file:{tmp_path}/c.yaml",
    ).construct()
    sym = cfg['rules']
    assert sym.invoke(component=Component('Button')) == {
        'color': 'red', 'weight': 'bold',
    }
    assert sym.invoke(component=Component('Link')) == {'underline': True}


def test_peer_cascade_merge_via_in_file_merge_key():
    yaml_str = """
rules: !cascade:test_dialect
  Button:
    color: red
  Link:
    underline: true
<<{<+}:
  rules: !cascade:test_dialect
    Button:
      weight: bold
"""
    cfg = dr.loads(yaml_str)
    sym = cfg['rules']
    assert isinstance(sym, CallableSymbol)
    assert sym.invoke(component=Component('Link')) == {'underline': True}
    assert sym.invoke(component=Component('Button')) == {
        'color': 'red', 'weight': 'bold',
    }


def test_peer_cascade_inherit_mode_merge_via_stack(tmp_path):
    # inherit-mode cascades (strip_suffix) produce a plain dict; same-strategy
    # peers across the stack must union, not overwrite.
    (tmp_path / 'a.yaml').write_text(
        'cfg: !cascade:strip_suffix(_params)\n'
        '  smooth_2d_params:\n'
        '    color: red\n'
    )
    (tmp_path / 'b.yaml').write_text(
        'cfg: !cascade:strip_suffix(_params)\n'
        '  smooth_2d_params:\n'
        '    weight: bold\n'
    )
    loader = dr.DraconLoader()
    cfg = loader.stack(
        f"file:{tmp_path}/a.yaml",
        f"file:{tmp_path}/b.yaml",
    ).construct()
    leaf = cfg['cfg']['smooth_2d_params']
    assert leaf['color'] == 'red'
    assert leaf['weight'] == 'bold'


def test_peer_cascade_merge_preserves_lazy_interpolation_via_stack(tmp_path):
    # cascade body lazies authored in one layer must keep their captured
    # context after merging with a peer cascade in another layer.
    (tmp_path / 'a.yaml').write_text(
        '!define accent: "lime"\n'
        'rules: !cascade:test_dialect\n'
        '  Button:\n'
        '    color: ${accent}\n'
    )
    (tmp_path / 'b.yaml').write_text(
        'rules: !cascade:test_dialect\n'
        '  Button:\n'
        '    weight: bold\n'
    )
    loader = dr.DraconLoader()
    cfg = loader.stack(
        f"file:{tmp_path}/a.yaml",
        f"file:{tmp_path}/b.yaml",
    ).construct()
    out = cfg['rules'].invoke(component=Component('Button'))
    assert out == {'color': 'lime', 'weight': 'bold'}


def test_peer_cascade_merge_nested_in_subtree(tmp_path):
    # peer cascade lives under a nested key, not at the root: merge engine
    # must still recurse through and union them.
    (tmp_path / 'a.yaml').write_text(
        'figure:\n'
        '  theme: !cascade:test_dialect\n'
        '    Button:\n'
        '      color: red\n'
    )
    (tmp_path / 'b.yaml').write_text(
        'figure:\n'
        '  theme: !cascade:test_dialect\n'
        '    Link:\n'
        '      underline: true\n'
    )
    loader = dr.DraconLoader()
    cfg = loader.stack(
        f"file:{tmp_path}/a.yaml",
        f"file:{tmp_path}/b.yaml",
    ).construct()
    sym = cfg['figure']['theme']
    assert sym.invoke(component=Component('Button')) == {'color': 'red'}
    assert sym.invoke(component=Component('Link')) == {'underline': True}


def test_peer_cascade_deep_body_value_merge(tmp_path):
    # overlapping selector keys with disjoint property keys: the property
    # bags themselves must deep-merge, not replace.
    (tmp_path / 'a.yaml').write_text(
        'rules: !cascade:test_dialect\n'
        '  Button:\n'
        '    color: red\n'
        '    size: 10\n'
    )
    (tmp_path / 'b.yaml').write_text(
        'rules: !cascade:test_dialect\n'
        '  Button:\n'
        '    weight: bold\n'
        '    size: 12\n'   # later wins on conflict
    )
    loader = dr.DraconLoader()
    cfg = loader.stack(
        f"file:{tmp_path}/a.yaml",
        f"file:{tmp_path}/b.yaml",
    ).construct()
    out = cfg['rules'].invoke(component=Component('Button'))
    assert out == {'color': 'red', 'weight': 'bold', 'size': 12}


def test_peer_cascade_dump_roundtrip_after_stack_merge(tmp_path):
    # the post-merge cascade must round-trip through dr.dump as a single
    # !cascade:NAME mapping with the unioned body.
    (tmp_path / 'a.yaml').write_text(
        'rules: !cascade:test_dialect\n'
        '  Button:\n'
        '    color: red\n'
    )
    (tmp_path / 'b.yaml').write_text(
        'rules: !cascade:test_dialect\n'
        '  Link:\n'
        '    underline: true\n'
    )
    loader = dr.DraconLoader()
    cfg = loader.stack(
        f"file:{tmp_path}/a.yaml",
        f"file:{tmp_path}/b.yaml",
    ).construct()
    dumped = dr.dump(cfg)
    assert '!cascade:test_dialect' in dumped
    cfg2 = dr.loads(dumped)
    assert cfg2['rules'].invoke(component=Component('Button')) == {'color': 'red'}
    assert cfg2['rules'].invoke(component=Component('Link')) == {'underline': True}


def test_peer_cascade_different_strategies_replace_not_merge(tmp_path):
    # two cascades with different strategy names should NOT silently merge;
    # later wins (current replace semantics).
    other = CascadeStrategy(
        name='alt_dialect', input_params=('component',),
        parse=_parse, matches=_matches,
        specificity=lambda k: k.specificity,
    )
    register_cascade_strategy(other)
    (tmp_path / 'a.yaml').write_text(
        'rules: !cascade:test_dialect\n'
        '  Button:\n'
        '    color: red\n'
    )
    (tmp_path / 'b.yaml').write_text(
        'rules: !cascade:alt_dialect\n'
        '  Button:\n'
        '    weight: bold\n'
    )
    loader = dr.DraconLoader()
    cfg = loader.stack(
        f"file:{tmp_path}/a.yaml",
        f"file:{tmp_path}/b.yaml",
    ).construct()
    # later cascade (different strategy) wins; first one is replaced
    sym = cfg['rules']
    assert sym._cascade_strategy.name == 'alt_dialect'
    assert sym.invoke(component=Component('Button')) == {'weight': 'bold'}


# ── sibling-define propagation into cascade body (regression for
# `2026-05-24-cascade-body-does-not-see-sibling-defines.md`) ────────────────
# A `!define X: <value>` at the same nesting level as a `!cascade:NAME` block
# must make `X` discoverable as a tag from inside the cascade body — same as
# anywhere else in the document. The bug was that scalar nodes inside the
# cascade body lost their dynamically-attached `.context` (populated by Define
# at composition time) during the cascade's `deepcopy` of its subject tree.


def test_select_body_sees_sibling_define_as_tag():
    yaml_str = """
!define f: ${mk()}
rules: !cascade:test_dialect
  Button:
    color: !f dark
"""
    loader = dr.DraconLoader(
        enable_interpolation=True,
        context={'mk': lambda: (lambda ch: f'<{ch}>')},
    )
    cfg = loader.loads(yaml_str)
    out = cfg['rules'].invoke(component=Component('Button'))
    assert out == {'color': '<dark>'}


def test_select_body_sees_sibling_define_as_tag_with_mapping_arg():
    def mk_url(host, port):
        return f'https://{host}:{port}'
    yaml_str = """
!define mk_url: ${mk_url_fn}
rules: !cascade:test_dialect
  Button:
    endpoint: !mk_url
      host: api.local
      port: 443
"""
    loader = dr.DraconLoader(
        enable_interpolation=True,
        context={'mk_url_fn': mk_url},
    )
    cfg = loader.loads(yaml_str)
    out = cfg['rules'].invoke(component=Component('Button'))
    assert out == {'endpoint': 'https://api.local:443'}


def test_inherit_body_sees_sibling_define_as_tag():
    def wrap(s):
        return f'<{s}>'
    yaml_str = """
!define f: ${wrap_fn}
cfg: !cascade:strip_suffix(_params)
  a_params:
    color: !f red
  b_params:
    a_params:
      width: 10
"""
    loader = dr.DraconLoader(
        enable_interpolation=True,
        context={'wrap_fn': wrap},
    )
    cfg = loader.loads(yaml_str)
    # color inherited via cascade AND must survive tag resolution
    assert cfg['cfg']['a_params']['color'] == '<red>'
    assert cfg['cfg']['b_params']['a_params']['color'] == '<red>'


def test_select_body_sees_sibling_define_via_interpolation():
    # control: ${f(...)} form must keep working — exercises the lazy-context path
    def wrap(s):
        return f'<{s}>'
    yaml_str = """
!define f: ${wrap_fn}
rules: !cascade:test_dialect
  Button:
    color: ${f('dark')}
"""
    loader = dr.DraconLoader(
        enable_interpolation=True,
        context={'wrap_fn': wrap},
    )
    cfg = loader.loads(yaml_str)
    out = cfg['rules'].invoke(component=Component('Button'))
    assert out == {'color': '<dark>'}


# ── node deepcopy preserves dynamic attributes (SSOT regression) ───────────
# The root cause of the sibling-define cascade bug was that `DraconScalarNode`
# silently dropped its dynamically-attached `.context` (populated by composer
# passes like Define) on deepcopy, while mapping/sequence nodes preserved it.
# Same issue affected `_live_scope_stack` (worked around ad hoc in Cascade).
# These tests pin down the SSOT contract: any dynamic attribute attached to a
# node during composition must survive a deepcopy.


def test_scalar_node_deepcopy_preserves_context():
    from copy import deepcopy
    from dracon.nodes import DraconScalarNode

    n = DraconScalarNode(tag='!f', value='dark')
    n.context = {'f': 'value'}
    c = deepcopy(n)
    assert getattr(c, 'context', None) == {'f': 'value'}
    # mutation isolation: copy must be independent
    n.context['f'] = 'mutated'
    assert c.context['f'] == 'value'


def test_scalar_node_deepcopy_preserves_live_scope_stack():
    from copy import deepcopy
    from dracon.nodes import DraconScalarNode

    n = DraconScalarNode(tag='tag:yaml.org,2002:str', value='x')
    n._live_scope_stack = (('component',),)
    c = deepcopy(n)
    assert getattr(c, '_live_scope_stack', ()) == (('component',),)


def test_mapping_node_deepcopy_preserves_live_scope_stack():
    from copy import deepcopy
    from dracon.nodes import DraconMappingNode, DraconScalarNode

    k = DraconScalarNode(tag='tag:yaml.org,2002:str', value='k')
    v = DraconScalarNode(tag='tag:yaml.org,2002:str', value='v')
    n = DraconMappingNode(tag='tag:yaml.org,2002:map', value=[(k, v)])
    n._live_scope_stack = (('component',),)
    c = deepcopy(n)
    assert getattr(c, '_live_scope_stack', ()) == (('component',),)


def test_sequence_node_deepcopy_preserves_context():
    from copy import deepcopy
    from dracon.nodes import DraconSequenceNode, DraconScalarNode

    n = DraconSequenceNode(
        tag='tag:yaml.org,2002:seq',
        value=[DraconScalarNode(tag='tag:yaml.org,2002:int', value='1')],
    )
    n.context = {'x': 1}
    c = deepcopy(n)
    assert getattr(c, 'context', None) == {'x': 1}
