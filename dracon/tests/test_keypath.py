import pytest
from dracon.keypath import KeyPath, KeyPathToken
from dracon.nodes import DraconMappingNode


# Tests for parsing without simplification
def test_parse_string_root():
    kp = KeyPath("/", simplify=False)
    assert kp.parts == [KeyPathToken.ROOT]


def test_parse_string_simple():
    kp = KeyPath("a.b.c", simplify=False)
    assert kp.parts == ["a", "b", "c"]


def test_parse_int_simple():
    kp = KeyPath(1, simplify=False)
    assert kp.parts == ['1']


def test_with_dots():
    kp = KeyPath("a.b\\.c.d", simplify=False)
    assert kp.parts == ["a", "b.c", "d"]


def test_parse_string_with_root():
    kp = KeyPath("/a.b.c", simplify=False)
    assert kp.parts == [KeyPathToken.ROOT, "a", "b", "c"]


def test_parse_string_with_up():
    kp = KeyPath("a.b..c", simplify=False)
    assert kp.parts == ["a", "b", KeyPathToken.UP, "c"]


def test_parse_string_multiple_up():
    kp = KeyPath("a.b...c", simplify=False)
    assert kp.parts == ["a", "b", KeyPathToken.UP, KeyPathToken.UP, "c"]


def test_parse_string_up_at_start():
    kp = KeyPath("..a.b", simplify=False)
    assert kp.parts == [KeyPathToken.UP, "a", "b"]


def test_parse_string_up_at_end():
    kp = KeyPath("a.b..", simplify=False)
    assert kp.parts == ["a", "b", KeyPathToken.UP]


def test_parse_string_with_integers():
    kp = KeyPath("a.0.b.1", simplify=False)
    assert kp.parts == ["a", '0', "b", '1']


def test_parse_string_mixed():
    kp = KeyPath("/a.0..b.1...", simplify=False)
    assert kp.parts == [
        KeyPathToken.ROOT,
        "a",
        '0',
        KeyPathToken.UP,
        "b",
        '1',
        KeyPathToken.UP,
        KeyPathToken.UP,
    ]


def test_parse_empty_string():
    kp = KeyPath("", simplify=False)
    assert kp.parts == []


# Tests for full construction with simplification
def test_simplify_root():
    kp = KeyPath("/")
    assert str(kp) == "/"


def test_simplify_simple_0():
    kp = KeyPath("a")
    assert str(kp) == "a"


def test_simplify_simple():
    kp = KeyPath("a.b.c")
    assert str(kp) == "a.b.c"


def test_simplify_with_up():
    kp = KeyPath("a.b..c")
    assert str(kp) == "a.c"


def test_simplify_multiple_up():
    kp = KeyPath("a.b...c", simplify=False)
    assert kp.parts == ["a", "b", KeyPathToken.UP, KeyPathToken.UP, "c"]
    assert str(kp) == "a.b...c"
    kp.simplify()
    assert str(kp) == "c"


def test_dont_simplify_up_at_start():
    kp = KeyPath("..a.b", simplify=False)
    assert kp.parts == [KeyPathToken.UP, "a", "b"]
    assert str(kp) == "..a.b"


def test_simplify_up_at_end():
    kp = KeyPath("a.b.")
    assert str(kp) == "a.b"


def test_simplify_with_root():
    kp = KeyPath("/a.b..c")
    assert str(kp) == "/a.c"


def test_simplify_to_root():
    kp = KeyPath("/a.b...")
    assert str(kp) == "/"


def test_simplify_beyond_root():
    kp = KeyPath("/a.b....")
    assert str(kp) == "/"


def test_simplify_with_integers():
    kp = KeyPath("a.0.b.1")
    assert str(kp) == "a.0.b.1"


def test_simplify_mixed():
    kp = KeyPath("/a.0..b.1")
    assert str(kp) == "/a.b.1"


def test_simplify_empty():
    kp = KeyPath("")
    assert str(kp) == ""


def test_simplify_only_up():
    kp = KeyPath("...")
    assert kp.parts == [KeyPathToken.UP, KeyPathToken.UP]
    assert str(kp) == "..."


def test_simplify_only_up_to_root():
    kp = KeyPath("/....", simplify=False)
    assert kp.parts == [KeyPathToken.ROOT, KeyPathToken.UP, KeyPathToken.UP, KeyPathToken.UP]
    assert str(kp) == "/...."
    kp.simplify()
    assert str(kp) == "/"


def test_root_anywhere():
    kp = KeyPath("a.b.c/..d.e")
    assert str(kp) == "/d.e"


def test_multuple_root():
    kp = KeyPath("/a.b.c//..d.e/..f.g.d..")
    assert str(kp) == "/f.g"


def test_addition():
    a = KeyPath("a.b")
    assert str(a) == "a.b"
    b = KeyPath("c.d")
    assert str(b) == "c.d"
    c = a + b
    assert str(a) == "a.b"
    assert str(b) == "c.d"
    assert str(c) == "a.b.c.d"
    d = a + KeyPath("e")
    assert str(d) == "a.b.e"
    e = KeyPath("f") + b
    assert str(e) == "f.c.d"

    f = KeyPath("..f")
    assert str(f) == "..f"
    assert (a + f).simplified() == KeyPath("a.f")

    aroot = KeyPath("/a.b")
    assert str(aroot) == "/a.b"
    broot = KeyPath("/c.d")
    assert str(broot) == "/c.d"
    croot = aroot + broot
    assert str(croot) == "/a.b/c.d"
    assert str(croot.simplified()) == "/c.d"


# test get on a dictionary
D = {
    "a": {"b": {"c": 1}},
    "d": 2,
    "e": 3,
    "f": {"g": {"h": [4, 5, {"i": 6, "j": [7, 8, 9]}]}},
}


def test_get():
    assert KeyPath("d").get_obj(D) == 2
    assert KeyPath("/f.g.h.1").get_obj(D) == 5
    assert KeyPath("f.g.h.2.j.1").get_obj(D) == 8
    assert KeyPath("a.b.c/a").get_obj(D) == {"b": {"c": 1}}
    assert KeyPath("a.b.c/a.b").get_obj(D) == {"c": 1}
    assert KeyPath("a.b.c....d").get_obj(D) == 2


class DummyNode:
    def __init__(self, value):
        self.value = value
        self.tag = ''


    def __eq__(self, other):
        return self.value == other.value


B = DraconMappingNode(
    tag='',
    value=[(DummyNode('b'), DraconMappingNode(tag='', value=[(DummyNode('c'), 1)]))],
)
F = DraconMappingNode(
    tag='',
    value=[
        (
            DummyNode('g'),
            DraconMappingNode(
                tag='',
                value=[
                    (
                        DummyNode('h'),
                        [4, 5, DraconMappingNode(tag='', value=[(DummyNode('i'), 6)])],
                    ),
                ],
            ),
        )
    ],
)

M = DraconMappingNode(
    tag='',
    value=[
        (
            DummyNode('a'),
            B,
        ),
        (DummyNode('d'), 2),
        (DummyNode('e'), 3),
        (DummyNode('f'), F),
    ],
)


def test_mappingkey():
    # test normal value keypaths:
    assert KeyPath("a.b.c").get_obj(M) == 1
    assert KeyPath("d").get_obj(M) == 2
    # test mapping key keypaths:
    mk = KeyPath("a.b") + KeyPathToken.MAPPING_KEY + KeyPath("c")
    assert mk.is_mapping_key()
    assert mk.get_obj(M) == DummyNode('c')
    mk = KeyPath("a.b") + KeyPathToken.MAPPING_KEY
    with pytest.raises(ValueError):
        mk.get_obj(M)

    mk = KeyPath("a") + KeyPathToken.MAPPING_KEY + KeyPath("b")
    assert mk.get_obj(M) == DummyNode('b')

    newmk = mk.copy() + KeyPath("c")
    with pytest.raises(ValueError):
        newmk.get_obj(M)

    newmk = mk.copy().up()
    assert not newmk.is_mapping_key()
    assert newmk.get_obj(M) == B

    newmk = mk.copy() + [KeyPathToken.UP, KeyPathToken.UP]
    assert newmk.get_obj(M) == M

    newmk = mk.copy() + [
        KeyPathToken.UP,
        KeyPathToken.UP,
        KeyPathToken.MAPPING_KEY,
        "d",
        KeyPathToken.UP,
        KeyPathToken.MAPPING_KEY,
        KeyPathToken.UP,
        "f",
        "g",
        KeyPathToken.MAPPING_KEY,
        "h",
    ]
    assert newmk.get_obj(M) == DummyNode('h')

    assert newmk.is_mapping_key()
    valuek = newmk.removed_mapping_key() + "1"
    assert newmk.is_mapping_key()
    assert not valuek.is_mapping_key()
    assert valuek.get_obj(M) == 5


def test_match_exact():
    pattern = KeyPath("a.b.c")
    target = KeyPath("a.b.c")
    assert pattern.match(target)


def test_match_single_wildcard():
    pattern = KeyPath("a.*.c")
    target1 = KeyPath("a.b.c")
    target2 = KeyPath("a.xyz.c")
    target3 = KeyPath("a.b.d")
    assert pattern.match(target1)
    assert pattern.match(target2)
    assert not pattern.match(target3)


def test_match_multi_wildcard():
    pattern = KeyPath("a.**.d")
    target1 = KeyPath("a.b.c.d")
    target2 = KeyPath("a.d")
    target3 = KeyPath("a.x.y.z.d")
    target4 = KeyPath("a.b.c.e")
    assert pattern.match(target1)
    assert pattern.match(target2)
    assert pattern.match(target3)
    assert not pattern.match(target4)


def test_match_partial_segment():
    pattern = KeyPath("a.b*.d")
    target1 = KeyPath("a.b.d")
    target2 = KeyPath("a.bcd.d")
    target3 = KeyPath("a.bc123.d")
    target4 = KeyPath("a.c.d")
    assert pattern.match(target1)
    assert pattern.match(target2)
    assert pattern.match(target3)
    assert not pattern.match(target4)


def test_match_mixed_wildcards_and_partial():
    pattern = KeyPath("a.*.b*.**.c*d")
    target1 = KeyPath("a.x.by.cd")
    target2 = KeyPath("a.x.bz.y.z.cd")
    target3 = KeyPath("a.x.by.z.czzd")
    target4 = KeyPath("a.x.cy.z.d")
    assert pattern.match(target1)
    assert pattern.match(target2)
    assert pattern.match(target3)
    assert not pattern.match(target4)


def test_match_with_root():
    pattern = KeyPath("/a.b*.c")
    target1 = KeyPath("/a.b.c")
    target2 = KeyPath("/a.bxyz.c")
    target3 = KeyPath("a.b.c")
    assert pattern.match(target1)
    assert pattern.match(target2)
    assert not pattern.match(target3)


def test_match_only_wildcards():
    pattern = KeyPath("*.**.*")
    target1 = KeyPath("a.b.c")
    target2 = KeyPath("a.b.c.d.e")
    target3 = KeyPath("a")
    assert pattern.match(target1)
    assert pattern.match(target2)
    assert not pattern.match(target3)


def test_match_empty():
    pattern = KeyPath("")
    target1 = KeyPath("")
    target2 = KeyPath("a")
    assert pattern.match(target1)
    assert not pattern.match(target2)


def test_match_complex_pattern():
    pattern = KeyPath("/a.*.b*.**.c*.*d")
    target1 = KeyPath("/a.x.by.z.cz.yd")
    target2 = KeyPath("/a.x.b.c.d")
    target3 = KeyPath("/a.x.by.z.c")
    target4 = KeyPath("a.x.by.z.cz.yd")
    assert pattern.match(target1)
    assert pattern.match(target2)
    assert not pattern.match(target3)
    assert not pattern.match(target4)


def test_match_with_integers():
    pattern = KeyPath("a.*.b*.**")
    target1 = KeyPath("a.0.b1.2.3")
    target2 = KeyPath("a.x.by.z")
    assert pattern.match(target1)
    assert pattern.match(target2)


def test_match_with_escaped_dots():
    pattern = KeyPath("a.*.b\\.c*.d")
    target1 = KeyPath("a.x.b.c.d")
    target2 = KeyPath("a.x.b\\.c123.d")
    assert not pattern.match(target1)
    assert pattern.match(target2)
