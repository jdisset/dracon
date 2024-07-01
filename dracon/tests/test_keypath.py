import pytest
from dracon.keypath import KeyPath, KeyPathToken


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
    "a": {
        "b": {
            "c": 1
        }
    },
    "d": 2,
    "e": 3,
    "f": {
        "g": {
            "h": [4, 5, {"i": 6, "j": [7, 8, 9]}]
        }
    },
}

def test_get():
    assert KeyPath("d").get_obj(D) == 2
    assert KeyPath("/f.g.h.1").get_obj(D) == 5
    assert KeyPath("f.g.h.2.j.1").get_obj(D) == 8
    assert KeyPath("a.b.c/a").get_obj(D) == {"b": {"c": 1}}
    assert KeyPath("a.b.c/a.b").get_obj(D) == {"c": 1}
    assert KeyPath("a.b.c....d").get_obj(D) == 2





