# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Jean Disset
"""Forwarding already-constructed objects through `<<{<+}: ${__extras__}`.

The kwarg-passthrough idiom

    !define Panel: !fn
      !require label: "..."
      !fn : !SomeModel
        label: ${label}
        <<{<+}: ${__extras__}     # forward anything not declared

used to realise the merge source by *deep-serialising* the resolved value
(`dump_to_node`) and then walking every produced node for context propagation.
When an extra kwarg carried a constructed object (a pydantic model holding a
numpy array, a child panel, ...) this was O(payload) work AND broke round-trip
for objects whose class isn't importable at `module.qualname` (e.g. classes
built dynamically). Fix: hold already-constructed values by reference (the
`!__py__` / PyValueNode rail) instead of serialising them.
"""
import textwrap

import pytest
from pydantic import BaseModel, ConfigDict

import dracon
from dracon import DraconLoader


def _loads(src, **ctx):
    loader = DraconLoader(enable_interpolation=True, context=ctx)
    out = loader.loads(textwrap.dedent(src).lstrip())
    return out


class Container(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    items: list = []


class Child(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    name: str = "child"
    payload: object = None


# ── identity: forwarded constructed objects are held by reference ─────────────


def test_extras_merge_forwards_constructed_objects_by_identity():
    """A list of pre-built objects forwarded through the extras merge must come
    out as the *same* objects, not dump->reconstruct copies."""
    children = [Child(name="a"), Child(name="b")]
    src = """
    !define Box: !fn
      !fn : !Container
        <<{<+}: ${__extras__}
    root: !Box
      items: ${children}
    """
    out = _loads(src, Container=Container, children=children)
    root = out["root"]
    while hasattr(root, "resolve"):
        root = root.resolve()
    assert root.items[0] is children[0]
    assert root.items[1] is children[1]


def test_extras_merge_does_not_serialise_opaque_payload():
    """An extra carrying an object that can't survive dump/deepcopy must still
    forward cleanly, held by reference."""

    class Opaque:
        def __init__(self, tag):
            self.tag = tag

        def __deepcopy__(self, memo):
            raise TypeError("Opaque refuses to be copied")

    op = Opaque("live-handle")
    holder = Child(name="h", payload=op)
    src = """
    !define Box: !fn
      !fn : !Container
        <<{<+}: ${__extras__}
    root: !Box
      items: ${things}
    """
    out = _loads(src, Container=Container, things=[holder])
    root = out["root"]
    while hasattr(root, "resolve"):
        root = root.resolve()
    assert root.items[0] is holder
    assert root.items[0].payload is op


def test_extras_merge_forwards_dynamically_created_class():
    """Reported correctness failure: a constructed object whose class is not
    importable at its module.qualname (built dynamically) must survive the
    forward. dump->reconstruct would tag it `!nonexistent...` and fail."""
    Dyn = type("Dyn", (BaseModel,), {"__annotations__": {"n": int}, "n": 0})
    Dyn.__module__ = "nonexistent.dynamic.module"
    inst = Dyn(n=7)
    src = """
    !define Box: !fn
      !fn : !Container
        <<{<+}: ${__extras__}
    root: !Box
      items: ${things}
    """
    out = _loads(src, Container=Container, things=[inst])
    root = out["root"]
    while hasattr(root, "resolve"):
        root = root.resolve()
    assert root.items[0] is inst
    assert root.items[0].n == 7


def test_extras_merge_holds_heavy_array_by_reference():
    """A model field holding a big array must not be `.tolist()`-serialised:
    the array that comes out is the *same* object."""
    np = pytest.importorskip("numpy")
    arr = np.arange(200_000, dtype=float)
    holder = Child(name="heavy", payload=arr)
    src = """
    !define Box: !fn
      !fn : !Container
        <<{<+}: ${__extras__}
    root: !Box
      items: ${things}
    """
    out = _loads(src, Container=Container, things=[holder])
    root = out["root"]
    while hasattr(root, "resolve"):
        root = root.resolve()
    assert root.items[0].payload is arr  # identity, not a tolist round-trip


def test_nested_panel_nest_forwards_by_reference():
    """The bug's exact shape: panels nested via `children`, each carrying a
    payload, forwarded through __extras__ at every level."""

    class Panel(BaseModel):
        model_config = ConfigDict(arbitrary_types_allowed=True)
        label: str = "panel"
        data: object = None
        children: list = []

    src = """
    !define Panel: !fn
      !require label: "label"
      !fn : !Panel
        label: ${label}
        <<{<+}: ${__extras__}

    root: !Panel
      label: L0
      data: ${payload}
      children:
        - !Panel
            label: L1
            data: ${payload}
            children:
              - !Panel { label: L2, data: ${payload} }
    """
    payload = object()
    out = _loads(src, Panel=Panel, payload=payload)
    root = out["root"]
    while hasattr(root, "resolve"):
        root = root.resolve()
    assert root.label == "L0"
    assert root.children[0].label == "L1"
    assert root.children[0].children[0].label == "L2"
    # both the child panels and the payloads are forwarded through __extras__ at
    # every level and held by reference -- same payload object throughout.
    assert root.data is payload
    assert root.children[0].data is payload
    assert root.children[0].children[0].data is payload


# ── regression: plain dict/scalar merges still expand structurally ────────────


def test_extras_merge_scalar_dict_still_merges_structurally():
    """Plain scalar extras still splice into the parent mapping (the original
    `<<: ${dict}` realisation behaviour)."""
    src = """
    !define wrap: !fn
      !require name: "..."
      result:
        name: ${name}
        <<{<+}: ${__extras__}
    out: !wrap { name: foo, color: red, size: big }
    """
    out = _loads(src)
    dracon.resolve_all_lazy(out)
    assert out["out"]["result"] == {"name": "foo", "color": "red", "size": "big"}


def test_extras_merge_nested_plain_dict_merges_into_parent():
    """A plain nested dict forwarded through extras deep-merges with a matching
    parent sub-dict (structural merge preserved, not held opaque)."""
    src = """
    conf:
      opts:
        a: 1
      <<{<+}: ${overrides}
    """
    out = _loads(src, overrides={"opts": {"b": 2}, "extra": 9})
    dracon.resolve_all_lazy(out)
    assert dict(out["conf"]["opts"]) == {"a": 1, "b": 2}
    assert out["conf"]["extra"] == 9


def test_top_level_model_merge_still_expands_fields():
    """`<<: ${model}` (model as the whole merge source) still expands the
    model's fields into the parent mapping."""

    class M(BaseModel):
        a: int = 1
        b: int = 2

    src = """
    conf:
      x: 10
      <<{<+}: ${m}
    """
    out = _loads(src, m=M(a=5, b=6))
    dracon.resolve_all_lazy(out)
    assert dict(out["conf"]) == {"x": 10, "a": 5, "b": 6}


# ── tagged merge source (`<<: !Model{...}`) -- same by-reference rail ──────────


def test_tagged_model_merge_source_holds_fields_by_reference():
    """`<<: !Holder{...}` constructs Holder then merges its fields; a field
    holding a constructed object must be held by reference, not deep-serialised
    (the tagged sibling of the __extras__ bug)."""
    payload = object()

    class Holder(BaseModel):
        model_config = ConfigDict(arbitrary_types_allowed=True)
        payload: object = None
        label: str = "h"

    src = """
    conf:
      keep: yes
      <<: !Holder { payload: ${p}, label: viaTag }
    """
    out = _loads(src, Holder=Holder, p=payload)
    dracon.resolve_all_lazy(out)
    conf = out["conf"]
    # merged result reconstructs as the tagged type, with the parent key kept
    assert isinstance(conf, Holder)
    assert conf.payload is payload
    assert conf.label == "viaTag"


def test_tagged_template_merge_source_still_merges_as_plain_mapping():
    """`<<: !fn-template{...}` (result is a plain dict) keeps merging as an
    untagged mapping -- no spurious type tag from the realiser."""
    src = """
    !define Defaults: !fn
      !set_default port: 8080
      port: ${port}
      protocol: http
    service:
      <<: !Defaults { port: 9000 }
      name: api
    """
    out = _loads(src)
    dracon.resolve_all_lazy(out)
    assert dict(out["service"]) == {"port": 9000, "protocol": "http", "name": "api"}


# ── unit: PyValueNode copy transparency ───────────────────────────────────────


def test_pyvaluenode_deepcopy_shares_py_value():
    from copy import deepcopy
    from dracon.loaders.py import PyValueNode

    class NoCopy:
        def __deepcopy__(self, memo):
            raise TypeError("must not be copied")

    obj = NoCopy()
    node = PyValueNode(obj, label="held")
    clone = deepcopy(node)
    assert clone is not node
    assert clone.py_value is obj
    assert clone.tag == node.tag
    assert clone.value == node.value


def test_fast_copy_node_tree_shares_pyvalue():
    from dracon.composer import fast_copy_node_tree
    from dracon.loaders.py import PyValueNode

    class NoCopy:
        def __deepcopy__(self, memo):
            raise TypeError("must not be copied")

    obj = NoCopy()
    node = PyValueNode(obj, label="held")
    clone = fast_copy_node_tree(node)
    assert clone.py_value is obj
