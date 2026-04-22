"""Tests for !if instructions inside sequences.

Regression tests for the sibling-path bug: when a !if evaluates false
inside a sequence, the empty mapping is removed from the sequence and
subsequent siblings shift into lower indices. The instruction dispatcher
must not mistake the shifted sibling for an already-processed path.
"""

import pytest
from dracon import resolve_all_lazy
from dracon.loader import DraconLoader


def _load(yaml: str):
    """Load + force lazy resolution (permissive)."""
    out = DraconLoader().loads(yaml)
    return resolve_all_lazy(out, permissive=True)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# baseline — single !if (was already working)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_single_false_if_in_sequence_is_pruned():
    out = _load("""
!set_default pipe: true
items:
  - !if ${not pipe}:
      then:
        - target: {input: hello}
          name: boot
""")
    assert out['items'] == []


def test_single_true_if_in_sequence_is_expanded():
    out = _load("""
!set_default pipe: false
items:
  - !if ${not pipe}:
      then:
        - target: {input: hello}
          name: boot
""")
    # when true, the then: list replaces the !if mapping entry
    assert len(out['items']) == 1
    # the replacement may nest another sequence; either way, the name is reachable
    inner = out['items'][0]
    if hasattr(inner, '__iter__') and not isinstance(inner, str) and 'name' not in (inner if hasattr(inner, 'keys') else {}):
        inner = inner[0]
    assert inner['name'] == 'boot'


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# regression — multiple sibling !if in a sequence
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_two_false_if_siblings_in_sequence():
    """All false !if siblings should be pruned without leaving stale nodes."""
    out = _load("""
!set_default pipe: true
!set_default prompt: "x"
items:
  - !if ${not pipe}:
      then:
        - target:
            input: ${prompt}
          name: boot
  - !if ${not pipe}:
      then:
        - target:
            input: ${prompt}
          name: first
""")
    assert out['items'] == []


def test_three_false_if_siblings_in_sequence():
    """N false !if siblings - verifies index shifting is handled."""
    out = _load("""
!set_default pipe: true
items:
  - !if ${not pipe}:
      then:
        - {name: a}
  - !if ${not pipe}:
      then:
        - {name: b}
  - !if ${not pipe}:
      then:
        - {name: c}
""")
    assert out['items'] == []


def test_mixed_true_false_if_siblings():
    """False !if pruned, true !if expanded."""
    out = _load("""
!set_default a: true
!set_default b: false
!set_default c: true
items:
  - !if ${a}:
      then: {name: alpha}
  - !if ${b}:
      then: {name: beta}
  - !if ${c}:
      then: {name: gamma}
""")
    names = [x['name'] for x in out['items']]
    assert names == ['alpha', 'gamma']


def test_if_siblings_with_interpolations_in_bodies():
    """Exact minimal reproduction from bug report —
    sibling !if with ${...} interpolations in their then: bodies.
    """
    out = _load("""
!define MakeJob: !fn
  !set_default pipe: false
  !set_default prompt: "hello"
  !fn :
    then:
      - !if ${not pipe}:
          then:
            - target:
                input: ${prompt}
              name: boot
      - !if ${not pipe}:
          then:
            - target:
                input: ${prompt}
              name: first

job_pipe: !MakeJob { pipe: true, prompt: "x" }
""")
    assert out['job_pipe']['then'] == []


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# adjacent generalizations — nested instructions, !each-generated sequences
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_nested_if_in_sequence():
    """Outer mapping has 'items', inner sequence has multiple false !if."""
    out = _load("""
!set_default pipe: true
items:
  - !if ${not pipe}:
      then:
        inner: boot
  - !if ${not pipe}:
      then:
        inner: first
extras:
  - !if ${not pipe}:
      then:
        inner: x
  - !if ${not pipe}:
      then:
        inner: y
""")
    assert out['items'] == []
    assert out['extras'] == []


def test_many_if_siblings_stress():
    """Stress test: 5 siblings, alternating."""
    out = _load("""
!set_default t: true
!set_default f: false
items:
  - !if ${t}: {then: {i: 0}}
  - !if ${f}: {then: {i: 1}}
  - !if ${t}: {then: {i: 2}}
  - !if ${f}: {then: {i: 3}}
  - !if ${t}: {then: {i: 4}}
""")
    idxs = [x['i'] for x in out['items']]
    assert idxs == [0, 2, 4]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# fn-template invocation — reprocess-after-mutation class of bug
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_fn_template_with_sibling_false_if():
    """!fn invocation deep-copies and reprocesses instructions. Siblings
    shifted in the deep-copied tree must still be processed.
    """
    out = _load("""
!define Make: !fn
  !set_default enable: true
  !fn :
    items:
      - !if ${not enable}: {then: {x: 1}}
      - !if ${not enable}: {then: {x: 2}}

result: !Make {enable: true}
""")
    assert out['result']['items'] == []


def test_fn_template_with_mixed_if_siblings():
    """!fn invocation with some false siblings pruned and true ones kept."""
    out = _load("""
!define Make: !fn
  !set_default mode: 'a'
  !fn :
    items:
      - !if ${mode == 'a'}: {then: {n: 'a'}}
      - !if ${mode == 'b'}: {then: {n: 'b'}}
      - !if ${mode == 'a'}: {then: {n: 'c'}}

result: !Make {mode: 'a'}
""")
    names = [x['n'] for x in out['result']['items']]
    assert names == ['a', 'c']


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# adjacent: !each-generated siblings should not be masked either
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_if_sibling_after_each_in_sequence():
    """Combination of !each-generated entries and !if siblings.
    Verifies that instruction dispatch handles generated siblings alongside
    pruned siblings without cross-contamination.
    """
    out = _load("""
!set_default enabled: false
!define names: [a, b]
extras:
  - !if ${enabled}:
      then: {v: 1}
  - !if ${enabled}:
      then: {v: 2}
""")
    assert out['extras'] == []
