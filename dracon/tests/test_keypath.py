# filename: tests/test_keypath.py
import pytest
from dracon.keypath import KeyPath, KeyPathToken, MAPPING_KEY  # import MAPPING_KEY alias
from dracon.nodes import DraconMappingNode, DraconScalarNode  # assuming these are needed

# --- Test Data ---
D = {
    "a": 1,
    "b": {"c": 2},
    "d": [10, 20, 30],
    "e": [{"f": 100}, {"g": 200}],
    "escaped/key": 500,
}

D_old_dict_test = {  # data specific to test_get_obj_dict
    "a": {"b": {"c": 1}},
    "d": 2,
    "e": 3,
    "f": {"g": {"h": [4, 5, {"i": 6, "j": [7, 8, 9]}]}},
}

try:

    class DummyNode:
        def __init__(self, value):
            self.value = value
            self.tag = ''

        def __eq__(self, other):
            return isinstance(other, DummyNode) and self.value == other.value

        def __hash__(self):
            return hash(self.value)

    B = DraconMappingNode(
        tag='', value=[(DummyNode('b'), DraconMappingNode(tag='', value=[(DummyNode('c'), 1)]))]
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
                        )
                    ],
                ),
            )
        ],
    )
    M = DraconMappingNode(
        tag='',
        value=[(DummyNode('a'), B), (DummyNode('d'), 2), (DummyNode('e'), 3), (DummyNode('f'), F)],
    )
    MAPPING_NODE_TESTS_ENABLED = True
except NameError:
    MAPPING_NODE_TESTS_ENABLED = False
    print("\nWarning: DraconMappingNode/DummyNode not found. Skipping MappingNode tests.")


# --- Parsing Tests (without simplification) ---
def test_parse_string_root():
    kp = KeyPath("/", simplify=False)
    assert kp.parts == [KeyPathToken.ROOT]


def test_parse_string_simple():
    kp = KeyPath("a/b/c", simplify=False)
    assert kp.parts == ["a", "b", "c"]


def test_parse_int_simple():
    kp = KeyPath(1, simplify=False)
    assert kp.parts == ['1']


def test_parse_with_escaped_separator():
    kp = KeyPath("a/b\\/c/d", simplify=False)
    assert kp.parts == ["a", "b/c", "d"]


def test_parse_with_escaped_escape():
    kp = KeyPath("a/b\\\\c/d", simplify=False)
    assert kp.parts == ["a", "b\\c", "d"]


def test_parse_string_with_root():
    kp = KeyPath("/a/b/c", simplify=False)
    assert kp.parts == [KeyPathToken.ROOT, "a", "b", "c"]


def test_parse_string_with_up():
    kp = KeyPath("a/b/../c", simplify=False)
    assert kp.parts == ["a", "b", KeyPathToken.UP, "c"]


def test_parse_string_multiple_up():
    kp = KeyPath("a/b/../../c", simplify=False)
    assert kp.parts == ["a", "b", KeyPathToken.UP, KeyPathToken.UP, "c"]


def test_parse_string_up_at_start():
    kp = KeyPath("../a/b", simplify=False)
    assert kp.parts == [KeyPathToken.UP, "a", "b"]


def test_parse_string_up_at_end():
    kp = KeyPath("a/b/../", simplify=False)
    assert kp.parts == ["a", "b", KeyPathToken.UP]


def test_parse_string_just_up():
    kp = KeyPath("..", simplify=False)
    assert kp.parts == [KeyPathToken.UP]


def test_parse_string_with_integers():
    kp = KeyPath("a/0/b/1", simplify=False)
    assert kp.parts == ["a", '0', "b", '1']


def test_parse_string_mixed():
    kp = KeyPath("/a/0/../b/1/../..", simplify=False)
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


def test_parse_dot_string():
    kp = KeyPath(".", simplify=False)
    assert kp.parts == []


def test_parse_root_dot():
    kp = KeyPath("/.", simplify=False)
    assert kp.parts == [KeyPathToken.ROOT]


def test_parse_current_dir_prefix():
    kp = KeyPath("./a/b", simplify=False)
    assert kp.parts == ["a", "b"]


def test_parse_current_dir_prefix_with_up():
    kp = KeyPath("./a/../b", simplify=False)
    assert kp.parts == ["a", KeyPathToken.UP, "b"]


def test_parse_current_dir_prefix_at_root_ignored():
    kp = KeyPath("/./a/b", simplify=False)
    assert kp.parts == [KeyPathToken.ROOT, "a", "b"]


def test_parse_current_dir_only():
    kp = KeyPath("./", simplify=False)
    assert kp.parts == []


def test_parse_double_slash_means_root():
    kp = KeyPath("a/b//c/d", simplify=False)
    assert kp.parts == ["a", "b", "c", "d"]


# --- Simplification Tests (including string representation) ---
def test_simplify_root():
    kp = KeyPath("/")
    assert str(kp) == "/"
    assert kp.parts == [KeyPathToken.ROOT]


def test_simplify_simple_0():
    kp = KeyPath("a")
    assert str(kp) == "a"
    assert kp.parts == ["a"]


def test_simplify_simple():
    kp = KeyPath("a/b/./c")
    assert str(kp) == "a/b/c"
    assert kp.parts == ["a", "b", "c"]


def test_simplify_with_up():
    kp = KeyPath("a/b/.././c")
    assert str(kp) == "a/c"
    assert kp.parts == ["a", "c"]


def test_simplify_multiple_up():
    kp = KeyPath("a/b/../../c")
    assert str(kp) == "c"
    assert kp.parts == ["c"]


def test_simplify_up_at_start():
    kp = KeyPath("../a/b")
    assert str(kp) == "../a/b"
    assert kp.parts == [KeyPathToken.UP, "a", "b"]


def test_simplify_up_at_end():
    kp = KeyPath("a/b/../")
    assert str(kp) == "a"
    assert kp.parts == ["a"]


def test_simplify_with_root():
    kp = KeyPath("/a/b/../c")
    assert str(kp) == "/a/c"
    assert kp.parts == [KeyPathToken.ROOT, "a", "c"]


def test_simplify_to_root():
    kp = KeyPath("/a/b/../../")
    assert str(kp) == "/"
    assert kp.parts == [KeyPathToken.ROOT]


def test_simplify_beyond_root():
    kp = KeyPath("/a/b/.././../../")
    assert str(kp) == "/"
    assert kp.parts == [KeyPathToken.ROOT]


def test_simplify_with_integers():
    kp = KeyPath("a/0/b/1")
    assert str(kp) == "a/0/b/1"
    assert kp.parts == ["a", '0', "b", '1']


def test_simplify_mixed():
    kp = KeyPath("/a/0/../b/1")
    assert str(kp) == "/a/b/1"
    assert kp.parts == [KeyPathToken.ROOT, "a", "b", '1']


def test_simplify_empty():
    kp = KeyPath("")
    assert str(kp) == "."
    assert kp.parts == []


def test_simplify_dot():
    kp = KeyPath(".")
    assert str(kp) == "."
    assert kp.parts == []


def test_simplify_only_up():
    kp = KeyPath("../../")
    assert str(kp) == "../.."
    assert kp.parts == [KeyPathToken.UP, KeyPathToken.UP]  # corrected expected str


def test_simplify_only_up_to_root():
    kp = KeyPath("/../../../")
    assert str(kp) == "/"
    assert kp.parts == [KeyPathToken.ROOT]


def test_simplify_double_slash():
    kp = KeyPath("a//b")
    assert str(kp) == "a/b"
    assert kp.parts == ["a", "b"]
    kp_root = KeyPath("//a")
    assert str(kp_root) == "/a"
    assert kp_root.parts == [KeyPathToken.ROOT, "a"]


def test_simplify_current_dir_prefix():
    kp = KeyPath("./a/b")
    assert str(kp) == "a/b"
    assert kp.parts == ["a", "b"]


def test_simplify_current_dir_prefix_with_up():
    kp = KeyPath("./a/../b/./../b")
    assert str(kp) == "b"
    assert kp.parts == ["b"]


def test_simplify_current_dir_prefix_with_up_and_root():
    kp = KeyPath("/./a/../b/./../../../b")
    assert str(kp) == "/b"
    assert kp.parts == [KeyPathToken.ROOT, "b"]


def test_simplify_current_dir_prefix_at_root():
    kp = KeyPath("/./a/b")
    assert str(kp) == "/a/b"
    assert kp.parts == [KeyPathToken.ROOT, "a", "b"]


# --- String Representation Tests (Unsimplified) ---
def test_str_unsimplified_basic():
    kp = KeyPath("a/b/../c", simplify=False)
    assert str(kp) == "a/b/../c"


def test_str_unsimplified_root():
    kp = KeyPath("/a/b/../c", simplify=False)
    assert str(kp) == "/a/b/../c"


def test_str_unsimplified_leading_up():
    kp = KeyPath("../a", simplify=False)
    assert str(kp) == "../a"


def test_str_unsimplified_escape():
    kp = KeyPath("a/b\\/c", simplify=False)
    assert str(kp) == "a/b\\/c"


def test_str_unsimplified_mapping_key():
    kp = KeyPath(['a', MAPPING_KEY, 'b'], simplify=False)
    assert str(kp) == "a/<MAPPING_KEY>/b"  # corrected expected str


# --- Addition Tests ---
def test_addition():
    a = KeyPath("a/b")
    b = KeyPath("c/d")
    assert str(a + b) == "a/b/c/d"
    assert str(a + "e") == "a/b/e"
    assert str(KeyPath("f") + b) == "f/c/d"  # corrected prepend test


def test_addition_up():
    a = KeyPath("a/b")
    f = KeyPath("../f")
    assert str(a + f) == "a/f"


def test_addition_root():
    aroot = KeyPath("/a/b")
    broot = KeyPath("/c/d")
    assert str(aroot + broot) == "/c/d"
    assert str(aroot + KeyPath("c/d")) == "/a/b/c/d"


def test_addition_with_current_dir():
    a = KeyPath("x/y")
    b = KeyPath("./z")
    c = KeyPath("w/./v")
    assert str(a + b) == "x/y/z"
    assert str(a + c) == "x/y/w/v"


# --- Get Object Tests ---
def test_get_obj_dict():
    # uses D_old_dict_test
    assert KeyPath("d").get_obj(D_old_dict_test) == 2
    assert KeyPath("/f/g/h/1").get_obj(D_old_dict_test) == 5
    assert KeyPath("f/g/h/2/j/1").get_obj(D_old_dict_test) == 8
    assert KeyPath("/a").get_obj(D_old_dict_test) == {"b": {"c": 1}}
    assert KeyPath("/a/b").get_obj(D_old_dict_test) == {"c": 1}
    assert KeyPath("a/b/c/../../../d").get_obj(D_old_dict_test) == 2
    # corrected test - start from root object
    assert KeyPath("b/c/../c").get_obj(D_old_dict_test['a']) == 1  # path 'b/c' on D['a']


def test_get_obj_list_access():
    # uses D
    assert KeyPath("d/0").get_obj(D) == 10
    assert KeyPath("d/1").get_obj(D) == 20
    assert KeyPath("e/0/f").get_obj(D) == 100
    assert KeyPath("e/1/g").get_obj(D) == 200
    with pytest.raises(IndexError):
        KeyPath("d/3").get_obj(D)
    with pytest.raises(AttributeError):
        KeyPath("d/a").get_obj(D)


def test_get_obj_mixed():
    # uses data local to test
    data = {
        "users": [
            {"name": "alice", "groups": ["admin", "dev"]},
            {"name": "bob", "groups": ["dev", "test"]},
        ],
        "settings": {"timeout": 30},
    }
    assert KeyPath("users/0/name").get_obj(data) == "alice"
    assert KeyPath("users/1/groups/0").get_obj(data) == "dev"
    assert KeyPath("settings/timeout").get_obj(data) == 30
    assert KeyPath("users/0/groups/../name").get_obj(data) == "alice"


def test_get_obj_with_current_dir():
    # uses D
    assert KeyPath("./a").get_obj(D) == 1
    assert KeyPath("./c").get_obj(D["b"]) == 2
    assert KeyPath("c").get_obj(D["b"]) == 2
    assert KeyPath("./b/c").get_obj(D) == 2
    assert KeyPath("b/c").get_obj(D) == 2


@pytest.mark.skipif(not MAPPING_NODE_TESTS_ENABLED, reason="MappingNode tests disabled")
def test_get_obj_mappingnode():
    # uses M
    assert KeyPath("a/b/c").get_obj(M) == 1
    assert KeyPath("d").get_obj(M) == 2
    mk = KeyPath(['a', 'b', MAPPING_KEY, 'c'])
    assert mk.is_mapping_key()
    assert mk.get_obj(M) == DummyNode('c')
    mk_a_b = KeyPath(['a', MAPPING_KEY, 'b'])
    assert mk_a_b.is_mapping_key()
    assert mk_a_b.get_obj(M) == DummyNode('b')
    mk_incomplete = KeyPath(['a', 'b', MAPPING_KEY])
    with pytest.raises(ValueError):
        mk_incomplete.get_obj(M)
    newmk_err = KeyPath(['a', MAPPING_KEY, 'b', 'c'])
    with pytest.raises(ValueError):
        newmk_err.get_obj(M)
    newmk_up = mk_a_b.copy().up()
    assert not newmk_up.is_mapping_key()
    assert newmk_up.get_obj(M) == B
    newmk_up_twice = mk_a_b.copy() + [KeyPathToken.UP, KeyPathToken.UP]
    assert newmk_up_twice.get_obj(M) == M
    complex_mk = KeyPath(
        [
            'a',
            MAPPING_KEY,
            'b',
            KeyPathToken.UP,
            KeyPathToken.UP,
            MAPPING_KEY,
            'd',
            KeyPathToken.UP,
            'f',
            'g',
            MAPPING_KEY,
            'h',
        ]
    )
    assert complex_mk.is_mapping_key()
    assert complex_mk.get_obj(M) == DummyNode('h')
    valuek = complex_mk.removed_mapping_key() + "1"
    assert not valuek.is_mapping_key()
    assert valuek.get_obj(M) == 5


# --- is_mapping_key / removed_mapping_key Tests ---
def test_is_mapping_key():
    assert KeyPath(['a', MAPPING_KEY, 'b']).is_mapping_key()
    assert not KeyPath(['a', 'b']).is_mapping_key()
    assert not KeyPath(['a', 'b', MAPPING_KEY]).is_mapping_key()
    # corrected test - use list init for clarity
    assert KeyPath(['a', 'b', KeyPathToken.UP, MAPPING_KEY, 'c']).is_mapping_key()


def test_removed_mapping_key():
    kp = KeyPath(['a', MAPPING_KEY, 'b'])
    val_kp = kp.removed_mapping_key()
    assert str(val_kp) == 'a/b'
    assert not val_kp.is_mapping_key()
    kp_non = KeyPath('a/b')
    assert kp_non.removed_mapping_key() == kp_non


# --- Match Tests ---
def test_match_exact():
    assert KeyPath("a/b/c").match(KeyPath("a/b/c"))


def test_match_single_wildcard():
    pattern = KeyPath("a/*/c")
    assert pattern.match(KeyPath("a/b/c"))
    assert pattern.match(KeyPath("a/xyz/c"))
    assert not pattern.match(KeyPath("a/b/d"))
    assert not pattern.match(KeyPath("a/c"))


def test_match_multi_wildcard():
    pattern = KeyPath("a/**/d")
    assert pattern.match(KeyPath("a/b/c/d"))
    assert pattern.match(KeyPath("a/d"))
    assert pattern.match(KeyPath("a/x/y/z/d"))
    assert not pattern.match(KeyPath("a/b/c/e"))
    assert not pattern.match(KeyPath("b/c/d"))


def test_match_partial_segment():
    pattern = KeyPath("a/b*/d")
    assert pattern.match(KeyPath("a/b/d"))
    assert pattern.match(KeyPath("a/bcd/d"))
    assert pattern.match(KeyPath("a/bc123/d"))
    assert not pattern.match(KeyPath("a/c/d"))
    assert pattern.match(KeyPath("a/bd/d"))


def test_match_mixed_wildcards_and_partial():
    pattern = KeyPath("a/*/b*/**/c*d")
    assert pattern.match(KeyPath("a/x/by/cd"))
    assert pattern.match(KeyPath("a/x/bz/y/z/cd"))
    assert pattern.match(KeyPath("a/x/by/z/czzd"))
    assert not pattern.match(KeyPath("a/x/cy/z/d"))
    assert not pattern.match(KeyPath("a/x/by/cz/zd"))


def test_match_with_root():
    pattern = KeyPath("/a/b*/c")
    assert pattern.match(KeyPath("/a/b/c"))
    assert pattern.match(KeyPath("/a/bxyz/c"))
    assert not pattern.match(KeyPath("a/b/c"))
    assert not pattern.match(KeyPath("/a/c/c"))


def test_match_only_wildcards():
    pattern = KeyPath("*/**/*")
    assert pattern.match(KeyPath("a/b/c"))
    assert pattern.match(KeyPath("a/b/c/d/e"))
    assert not pattern.match(KeyPath("a"))
    pattern2 = KeyPath("**")
    assert pattern2.match(KeyPath("a/b/c"))
    assert pattern2.match(KeyPath("a"))
    assert pattern2.match(KeyPath(""))
    assert pattern2.match(KeyPath("."))


def test_match_empty():
    pattern = KeyPath(".")
    assert pattern.match(KeyPath(""))
    assert pattern.match(KeyPath("."))
    assert not pattern.match(KeyPath("a"))


def test_match_complex_pattern():
    pattern = KeyPath("/a/*/b*/**/c*/*d")
    assert pattern.match(KeyPath("/a/x/by/z/cz/yd"))
    assert pattern.match(KeyPath("/a/x/b/c/d"))
    assert not pattern.match(KeyPath("/a/x/by/z/c"))
    assert not pattern.match(KeyPath("a/x/by/z/cz/yd"))
    assert pattern.match(KeyPath("/a/x/by/z/czz/zzd"))


def test_match_with_integers():
    pattern = KeyPath("a/*/b*/**")
    assert pattern.match(KeyPath("a/0/b1/2/3"))
    assert pattern.match(KeyPath("a/x/by/z"))
    assert not pattern.match(KeyPath("a/0/c/2"))


def test_match_with_escaped_separators():
    pattern = KeyPath("a/*/b\\/c*/d")
    assert not pattern.match(KeyPath("a/x/b/c/d"))
    assert pattern.match(KeyPath("a/x/b\\/c123/d"))
    assert not pattern.match(KeyPath("a/x/b/c123/d"))
