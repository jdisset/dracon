import pytest
from dracon.keypath import KeyPath, ROOTPATH
from dracon.composer import CompositionResult
from ruamel.yaml.nodes import ScalarNode


class UniqueNode(ScalarNode):

    def __init__(
        self,
        value=None,
        start_mark=None,
        end_mark=None,
        tag=None,
        anchor=None,
        comment=None,
    ):
        ScalarNode.__init__(self, tag, value, start_mark, end_mark, comment=comment, anchor=anchor)


def test_composition_result_initialization():
    nr, na, nb = UniqueNode(), UniqueNode(), UniqueNode()
    cr = CompositionResult(
        node_map={
            KeyPath("/"): nr,
            KeyPath("/a"): na,
            KeyPath("/a.b"): nb,
        },
        include_nodes=[KeyPath("/a.b")],
        anchor_paths={"anchor1": KeyPath("/a")},
    )
    assert len(cr.node_map) == 3
    assert len(cr.include_nodes) == 1
    assert len(cr.anchor_paths) == 1

    assert cr.node_map[KeyPath("/")] == nr
    assert cr.node_map[KeyPath("/a")] == na
    assert cr.node_map[KeyPath("/a.b")] == nb
    assert cr.include_nodes[0] == KeyPath("/a.b")

    assert nr in cr.reverse_map
    assert na in cr.reverse_map
    assert nb in cr.reverse_map

    assert cr.reverse_map[nr] == {KeyPath("/")}
    assert cr.reverse_map[na] == {KeyPath("/a")}
    assert cr.reverse_map[nb] == {KeyPath("/a.b")}



def test_root_method():
    root_node = UniqueNode()
    cr = CompositionResult(node_map={ROOTPATH: root_node})
    assert cr.root() == root_node


def test_rerooted_method():
    cr = CompositionResult(
        node_map={
            KeyPath("/"): UniqueNode(),
            KeyPath("/a"): UniqueNode(),
            KeyPath("/a.b"): UniqueNode(),
            KeyPath("/a.b.c"): UniqueNode(),
        },
        include_nodes=[KeyPath("/a.b")],
        anchor_paths={"anchor1": KeyPath("/a.b")},
    )

    new_cr = cr.rerooted(KeyPath("/a"))

    assert len(new_cr.node_map) == 3
    assert KeyPath("/") in new_cr.node_map
    assert KeyPath("/b") in new_cr.node_map
    assert KeyPath("/b.c") in new_cr.node_map
    assert new_cr.include_nodes == [KeyPath("/b")]
    assert new_cr.anchor_paths == {"anchor1": KeyPath("/b")}


def test_rerooted_method_invalid_path():
    cr = CompositionResult(node_map={KeyPath("/"): UniqueNode()})
    with pytest.raises(AssertionError):
        cr.rerooted(KeyPath("/invalid"))


def test_replace_at_method():

    nr, na, nb = UniqueNode(), UniqueNode(), UniqueNode()
    nr2, nx, ny = UniqueNode(), UniqueNode(), UniqueNode()

    cr = CompositionResult(
        node_map={
            KeyPath("/"): nr,
            KeyPath("/a"): na,
            KeyPath("/b"): nb,
            KeyPath("/refs.b2"): nb,
            KeyPath("/refs.a2"): na,
        },
        include_nodes=[KeyPath("/a")],
        anchor_paths={},
    )

    new_root = CompositionResult(
        node_map={
            KeyPath("/"): nr2,
            KeyPath("/x"): nx,
            KeyPath("/y"): ny,
        },
        include_nodes=[KeyPath("/x")],
        anchor_paths={"new_anchor": KeyPath("/y")},
    )

    cr.replace_at(KeyPath("/a"), new_root)

    assert KeyPath("/a") in cr.node_map
    assert KeyPath("/a.x") in cr.node_map
    assert KeyPath("/a.y") in cr.node_map

    assert cr.include_nodes == [KeyPath("/a.x")]
    assert cr.anchor_paths == {"new_anchor": KeyPath("/a.y")}

    assert cr.node_map[KeyPath("/")] == nr
    assert cr.node_map[KeyPath("/b")] == nb
    assert cr.node_map[KeyPath("/refs.b2")] == nb

    assert cr.node_map[KeyPath("/a")] == nr2
    assert cr.node_map[KeyPath("/a.x")] == nx
    assert cr.node_map[KeyPath("/a.y")] == ny
    assert cr.node_map[KeyPath("/refs.a2")] == nr2

    assert nr in cr.reverse_map
    assert na not in cr.reverse_map
    assert nb in cr.reverse_map
    assert nr2 in cr.reverse_map
    assert nx in cr.reverse_map
    assert ny in cr.reverse_map



def test_replace_at_method_with_existing_anchor():
    cr = CompositionResult(
        node_map={
            KeyPath("/"): UniqueNode(),
            KeyPath("/existing"): UniqueNode(),
            KeyPath("/replacement"): UniqueNode(),
        },
        include_nodes=[],
        anchor_paths={"existing_anchor": KeyPath("/existing")},
    )

    new_root = CompositionResult(
        node_map={KeyPath("/"): UniqueNode()},
        include_nodes=[],
        anchor_paths={"existing_anchor": KeyPath("/new")},
    )

    cr.replace_at(KeyPath("/replacement"), new_root)

    assert cr.anchor_paths["existing_anchor"] == KeyPath("/existing")
