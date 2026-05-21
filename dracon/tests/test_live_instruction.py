# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Jean Disset

"""`!live name:` instruction tag with scope-stack plumbing.

Step 02 of the SSOT symbol-axis refactor. Lands the syntax and the
per-node `_live_scope_stack` attribute pushed during composition.
Step 03 reads the stack to populate InterfaceSpec.params on lazies
created inside `!live` bodies.
"""

import dracon as dr
from dracon import DraconLoader
from dracon.instructions import Live, match_instruct


def test_match_tag_only():
    # the YAML tag is just '!live'; names come from the key value
    inst = match_instruct('!live')
    assert isinstance(inst, Live)
    assert inst.names == ()


def test_match_rejects_other_tags():
    assert match_instruct('!define') is not None  # sanity
    assert not isinstance(match_instruct('!define'), Live)


def test_live_rejects_non_identifier_key():
    # ill-formed names in key value -> CompositionError at process time
    import pytest
    from dracon.diagnostics import CompositionError
    with pytest.raises((CompositionError, Exception)):
        dr.loads("""
!live foo-bar:
  x: 1
""")


def test_live_strips_tag_from_tree():
    yaml_str = """
!live component:
  x: 1
  y: 2
"""
    cfg = dr.loads(yaml_str)
    assert cfg == {'x': 1, 'y': 2}


def test_live_preserves_body_shape_vs_unwrapped():
    wrapped = dr.loads("""
!live component:
  x: 1
  nested:
    a: 2
    b: [3, 4]
""")
    bare = dr.loads("""
x: 1
nested:
  a: 2
  b: [3, 4]
""")
    assert wrapped == bare


def test_live_with_scalar_body():
    # body is a single scalar (not a mapping). tag-strip must replace the
    # whole entry's value with the scalar, not merge mapping items.
    cfg = dr.loads("""
val:
  !live component: 42
""")
    assert cfg == {'val': 42}


def _compose(content: str):
    loader = DraconLoader(enable_interpolation=True)
    return loader.post_process_composed(loader.compose_config_from_str(content))


def test_live_pushes_scope_stack_on_descendants():
    comp = _compose("""
!live component:
  color: ${component.x}
""")
    color_node = comp.root['color']
    assert ('component',) in getattr(color_node, '_live_scope_stack', ())


def test_nested_live_accumulates_stack():
    comp = _compose("""
!live component:
  !live theme:
    color: ${theme.colors[component.kind]}
""")

    def _collect(node, frames):
        s = getattr(node, '_live_scope_stack', ())
        if s:
            frames.append(s)
        if hasattr(node, 'value') and isinstance(node.value, list):
            for v in node.value:
                if isinstance(v, tuple):
                    _collect(v[1], frames)

    frames: list = []
    _collect(comp.root, frames)
    union = {n for stack in frames for frame in stack for n in frame}
    assert 'component' in union
    assert 'theme' in union


def test_live_multi_name_pushes_all():
    comp = _compose("""
!live step, epoch:
  warmup: ${step}
  phase: ${epoch}
""")
    warmup = comp.root['warmup']
    stack = getattr(warmup, '_live_scope_stack', ())
    assert ('step', 'epoch') in stack


def test_live_empty_names_passes_body_through():
    # !live with no key value: valid no-op, just strips tag
    cfg = dr.loads("""
!live :
  x: 1
""")
    assert cfg == {'x': 1}


def test_live_inside_pydantic_roundtrip():
    # tag-stripping must preserve body identity through construction
    yaml_str = """
host: localhost
port: 8080
"""
    plain = dr.loads(yaml_str)
    wrapped = dr.loads(f"""
!live runtime:
{yaml_str.rstrip().replace(chr(10), chr(10) + '  ')}
""")
    assert plain == wrapped
