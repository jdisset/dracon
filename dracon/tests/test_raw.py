"""Tests for !raw tag -- opaque values that survive all dracon phases."""

import pytest
from dracon import loads, dump, DraconLoader


def test_raw_scalar_basic():
    """!raw wraps a string into a RawExpression."""
    from dracon.raw import RawExpression
    result = loads("val: !raw 'channels.messages(\"bugs\")'")
    assert isinstance(result["val"], RawExpression)
    assert result["val"] == 'channels.messages("bugs")'


def test_raw_no_interpolation():
    """!raw prevents ${...} from being interpolated."""
    from dracon.raw import RawExpression
    result = loads("""
        !define x: 42
        val: !raw "${x} + 1"
    """)
    assert isinstance(result["val"], RawExpression)
    assert result["val"] == "${x} + 1"


def test_raw_survives_fn():
    """!raw values flow through !fn invocations as opaque blobs."""
    from dracon.raw import RawExpression
    result = loads("""
        !define tmpl: !fn
            !require expr: "an expression"
            !fn :
                env:
                    VAL: ${expr}
        out: !tmpl { expr: !raw "runtime.eval('foo')" }
    """)
    assert isinstance(result["out"]["env"]["VAL"], RawExpression)
    assert result["out"]["env"]["VAL"] == "runtime.eval('foo')"


def test_raw_roundtrip():
    """!raw survives dump -> loads cycle."""
    from dracon.raw import RawExpression
    original = loads("val: !raw 'some.expr()'")
    dumped = dump(original)
    assert "!raw" in dumped
    reloaded = loads(dumped)
    assert isinstance(reloaded["val"], RawExpression)
    assert reloaded["val"] == "some.expr()"


def test_raw_in_list():
    """!raw works inside sequences."""
    from dracon.raw import RawExpression
    result = loads("""
        vals:
            - !raw "a.b()"
            - normal
            - !raw "c.d()"
    """)
    assert isinstance(result["vals"][0], RawExpression)
    assert result["vals"][1] == "normal"
    assert isinstance(result["vals"][2], RawExpression)


def test_raw_is_str():
    """RawExpression is a str subclass -- works anywhere str does."""
    from dracon.raw import RawExpression
    result = loads("val: !raw 'hello'")
    assert isinstance(result["val"], str)
    assert result["val"].upper() == "HELLO"


def test_raw_with_dollar_escape_inside():
    """$${} inside !raw is NOT unescaped -- the whole string is literal."""
    from dracon.raw import RawExpression
    result = loads("val: !raw '$${foo}'")
    assert result["val"] == "$${foo}"


# adversarial strings that exercise every interpolation/escaping code path.
# a !raw value must survive ALL of these exactly as-is.
_ADVERSARIAL_RAW_STRINGS = [
    "plain text",
    "${runtime.eval('x')}",         # interpolation syntax
    "$${escaped}",                   # double-dollar escape
    "prefix_$${mid}_suffix",        # escape inside larger string
    # note: backslash escapes are tested in roundtrip only, not fn-passthrough,
    # because repr() + yaml single-quoting double-escapes backslashes.
    "$VAR",                          # shorthand var
    "${a} and ${b}",                 # multiple interpolations
    "${nested_${deep}}",             # nested interpolation
    "channels.messages('bugs')",     # no special chars at all
    "",                              # empty string
]


@pytest.mark.parametrize("raw_str", _ADVERSARIAL_RAW_STRINGS)
def test_raw_exact_preservation_through_fn(raw_str):
    """!raw values survive !fn + lazy resolution with exact string content."""
    from dracon.raw import RawExpression
    loader = DraconLoader(enable_interpolation=True)
    # use block style to avoid yaml quoting issues with special chars
    yaml_str = f"""
        !define tmpl: !fn
            !require val: "a value"
            !fn :
                out: ${{val}}
        result: !tmpl
            val: !raw {repr(raw_str)}
    """
    result = loader.loads(yaml_str)
    assert isinstance(result["result"]["out"], RawExpression), \
        f"RawExpression type lost for: {raw_str!r}"
    assert result["result"]["out"] == raw_str, \
        f"Content mangled: expected {raw_str!r}, got {result['result']['out']!r}"


_ROUNDTRIP_RAW_STRINGS = _ADVERSARIAL_RAW_STRINGS + [
    "\\${backslash_escape}",        # backslash escape
]


@pytest.mark.parametrize("raw_str", _ROUNDTRIP_RAW_STRINGS)
def test_raw_roundtrip_preservation(raw_str):
    """!raw values survive dump -> loads with exact content."""
    from dracon.raw import RawExpression
    original = {"val": RawExpression(raw_str)}
    from dracon import dump
    dumped = dump(original)
    reloaded = loads(dumped)
    assert isinstance(reloaded["val"], RawExpression)
    assert reloaded["val"] == raw_str


def test_raw_survives_resolve_all_lazy():
    """resolve_all_lazy leaves RawExpression untouched."""
    from dracon.raw import RawExpression
    from dracon.lazy import resolve_all_lazy
    data = {"a": RawExpression("${x}"), "b": 42}
    resolved = resolve_all_lazy(data)
    assert isinstance(resolved["a"], RawExpression)
    assert resolved["a"] == "${x}"


def test_raw_in_pydantic_model():
    """RawExpression can be a field value in a pydantic model."""
    from pydantic import BaseModel
    from dracon.raw import RawExpression

    class Cfg(BaseModel):
        expr: RawExpression | str

    result = loads("!Cfg\nexpr: !raw 'runtime.x()'", context={"Cfg": Cfg})
    assert isinstance(result, Cfg)
    assert isinstance(result.expr, RawExpression)
    assert result.expr == "runtime.x()"


def test_raw_with_interpolation_syntax_in_fn():
    """!raw containing ${...} survives !fn without recursive interpolation."""
    from dracon.raw import RawExpression
    result = loads("""
        !define tmpl: !fn
            !require expr: "an expression"
            !fn :
                val: ${expr}
        out: !tmpl
            expr: !raw "${runtime.eval('x')}"
    """)
    assert isinstance(result["out"]["val"], RawExpression)
    assert result["out"]["val"] == "${runtime.eval('x')}"


def test_raw_nested_fn():
    """!raw flows through multiple levels of !fn nesting."""
    from dracon.raw import RawExpression
    result = loads("""
        !define inner: !fn
            !require val: "a value"
            !fn :
                x: ${val}

        !define outer: !fn
            !require v: "a value"
            !fn :
                wrapped: !inner
                    val: ${v}

        out: !outer
            v: !raw "deep.expr()"
    """)
    assert isinstance(result["out"]["wrapped"]["x"], RawExpression)
    assert result["out"]["wrapped"]["x"] == "deep.expr()"
