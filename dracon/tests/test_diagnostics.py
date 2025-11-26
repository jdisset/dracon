# Copyright (c) 2025 Jean Disset
# MIT License - see LICENSE file for details.
"""Tests for Dracon's diagnostic error handling system."""

import pytest
from dracon.diagnostics import (
    SourceContext,
    SourceLocation,
    DraconError,
    CompositionError,
    EvaluationError,
    SchemaError,
    format_error,
)


## {{{                    --     SourceContext tests     --


def test_source_location_creation():
    """SourceLocation captures file, line, column."""
    loc = SourceLocation(file_path="config.yaml", line=10, column=5)
    assert loc.file_path == "config.yaml"
    assert loc.line == 10
    assert loc.column == 5


def test_source_location_str():
    """SourceLocation has readable string representation."""
    loc = SourceLocation(file_path="config.yaml", line=10, column=5)
    assert "config.yaml" in str(loc)
    assert "10" in str(loc)


def test_source_location_from_mark():
    """SourceLocation can be created from ruamel.yaml mark."""
    # create a mock mark similar to ruamel.yaml's
    class MockMark:
        name = "test.yaml"
        line = 5
        column = 3

    loc = SourceLocation.from_mark(MockMark())
    assert loc.file_path == "test.yaml"
    assert loc.line == 6  # ruamel uses 0-indexed, we use 1-indexed
    assert loc.column == 4


def test_source_context_creation():
    """SourceContext holds location and include trace."""
    ctx = SourceContext(
        file_path="prod.yaml",
        line=20,
        column=4,
    )
    assert ctx.file_path == "prod.yaml"
    assert ctx.line == 20
    assert ctx.column == 4
    assert ctx.include_trace == ()
    assert ctx.operation_context is None


def test_source_context_with_include_trace():
    """SourceContext can track include chain."""
    base = SourceLocation(file_path="base.yaml", line=5, column=0)
    prod = SourceLocation(file_path="prod.yaml", line=10, column=2)

    ctx = SourceContext(
        file_path="secrets.yaml",
        line=3,
        column=0,
        include_trace=(base, prod),
    )
    assert len(ctx.include_trace) == 2
    assert ctx.include_trace[0].file_path == "base.yaml"
    assert ctx.include_trace[1].file_path == "prod.yaml"


def test_source_context_with_operation():
    """SourceContext can capture operation context."""
    ctx = SourceContext(
        file_path="config.yaml",
        line=15,
        column=2,
        operation_context="inside !each loop on var 'i', iteration 3",
    )
    assert ctx.operation_context == "inside !each loop on var 'i', iteration 3"


def test_source_context_is_immutable():
    """SourceContext is immutable (frozen dataclass)."""
    ctx = SourceContext(file_path="config.yaml", line=1, column=0)
    with pytest.raises(AttributeError):
        ctx.line = 5


def test_source_context_with_child():
    """SourceContext can create child context with updated location."""
    parent = SourceContext(file_path="base.yaml", line=5, column=0)
    child = parent.with_child(file_path="included.yaml", line=10, column=2)

    # child should have new location
    assert child.file_path == "included.yaml"
    assert child.line == 10
    # child should have parent in include trace
    assert len(child.include_trace) == 1
    assert child.include_trace[0].file_path == "base.yaml"


##────────────────────────────────────────────────────────────────────────────}}}

## {{{                    --     Exception hierarchy tests     --


def test_dracon_error_base():
    """DraconError is the base class with SourceContext."""
    ctx = SourceContext(file_path="config.yaml", line=10, column=0)
    err = DraconError("something went wrong", context=ctx)

    assert str(err) == "something went wrong"
    assert err.context == ctx


def test_dracon_error_without_context():
    """DraconError can be created without context for backwards compat."""
    err = DraconError("generic error")
    assert str(err) == "generic error"
    assert err.context is None


def test_dracon_error_with_cause():
    """DraconError preserves original exception."""
    ctx = SourceContext(file_path="config.yaml", line=10, column=0)
    original = ValueError("original problem")
    err = DraconError("wrapped error", context=ctx, cause=original)

    assert err.__cause__ == original


def test_composition_error():
    """CompositionError for graph-building errors."""
    ctx = SourceContext(file_path="config.yaml", line=5, column=0)
    err = CompositionError("include not found: missing.yaml", context=ctx)

    assert isinstance(err, DraconError)
    assert "include not found" in str(err)


def test_evaluation_error():
    """EvaluationError for interpolation errors."""
    ctx = SourceContext(file_path="config.yaml", line=12, column=10)
    err = EvaluationError("undefined variable 'foo'", context=ctx, expression="${foo}")

    assert isinstance(err, DraconError)
    assert err.expression == "${foo}"


def test_schema_error():
    """SchemaError for Pydantic validation errors."""
    ctx = SourceContext(file_path="config.yaml", line=20, column=4)
    err = SchemaError(
        "expected int, got str",
        context=ctx,
        field_path=("db", "port"),
        expected_type=int,
        actual_value="five",
    )

    assert isinstance(err, DraconError)
    assert err.field_path == ("db", "port")
    assert err.expected_type == int
    assert err.actual_value == "five"


##────────────────────────────────────────────────────────────────────────────}}}

## {{{                    --     Error formatting tests     --


def test_format_error_simple():
    """format_error produces readable output for simple errors."""
    ctx = SourceContext(file_path="config.yaml", line=10, column=0)
    err = DraconError("invalid value", context=ctx)

    output = format_error(err)

    assert "config.yaml" in output
    assert "line 10" in output.lower() or "10" in output


def test_format_error_with_include_trace():
    """format_error shows the include trace."""
    base_loc = SourceLocation(file_path="base.yaml", line=5, column=0)
    ctx = SourceContext(
        file_path="prod.yaml", line=20, column=4, include_trace=(base_loc,)
    )
    err = DraconError("invalid value", context=ctx)

    output = format_error(err)

    assert "base.yaml" in output
    assert "prod.yaml" in output


def test_format_error_with_operation_context():
    """format_error shows operation context."""
    ctx = SourceContext(
        file_path="config.yaml",
        line=15,
        column=0,
        operation_context="during iteration 2 of !each(i)",
    )
    err = DraconError("invalid value", context=ctx)

    output = format_error(err)

    assert "iteration 2" in output or "each" in output


def test_format_error_evaluation():
    """format_error shows expression for EvaluationError."""
    ctx = SourceContext(file_path="config.yaml", line=12, column=10)
    err = EvaluationError("name 'foo' is not defined", context=ctx, expression="${foo + 1}")

    output = format_error(err)

    assert "${foo + 1}" in output or "foo + 1" in output


def test_format_error_schema():
    """format_error shows field path for SchemaError."""
    ctx = SourceContext(file_path="config.yaml", line=20, column=4)
    err = SchemaError(
        "expected int, got str",
        context=ctx,
        field_path=("db", "port"),
        expected_type=int,
        actual_value="five",
    )

    output = format_error(err)

    assert "db" in output or "port" in output
    assert "five" in output or "int" in output


def test_format_error_without_context():
    """format_error handles errors without context gracefully."""
    err = DraconError("something went wrong")
    output = format_error(err)
    assert "something went wrong" in output


##────────────────────────────────────────────────────────────────────────────}}}

## {{{                    --     Node source context tests     --


def test_nodes_have_source_context():
    """Nodes created by the composer should have source_context."""
    from dracon.loader import DraconLoader

    yaml_content = """
    key1: value1
    key2: 42
    nested:
      inner: data
    """

    loader = DraconLoader()
    comp = loader.compose_config_from_str(yaml_content)

    # root node should have source context
    root = comp.root
    assert hasattr(root, "source_context")
    assert root.source_context is not None


def test_scalar_nodes_track_source():
    """Scalar nodes should track their source location."""
    from dracon.loader import DraconLoader

    yaml_content = """key: value"""

    loader = DraconLoader()
    comp = loader.compose_config_from_str(yaml_content)

    # access the scalar value node
    root = comp.root
    value_node = root["key"]
    assert hasattr(value_node, "source_context")
    assert value_node.source_context is not None
    # line numbers are 1-indexed (first line is 1)
    assert value_node.source_context.line >= 1


def test_source_context_preserved_in_deepcopy():
    """Source context should survive deepcopy."""
    from dracon.loader import DraconLoader
    from copy import deepcopy

    yaml_content = """
    key: value
    """

    loader = DraconLoader()
    comp = loader.compose_config_from_str(yaml_content)

    original_context = comp.root.source_context
    copied = deepcopy(comp.root)

    assert hasattr(copied, "source_context")
    assert copied.source_context is not None
    assert copied.source_context.file_path == original_context.file_path
    assert copied.source_context.line == original_context.line


def test_include_trace_propagates():
    """When processing includes, the include trace should capture the keypath."""
    import tempfile
    import os
    from dracon.loader import DraconLoader

    with tempfile.TemporaryDirectory() as tmpdir:
        inc_path = os.path.join(tmpdir, "included.yaml")
        with open(inc_path, "w") as f:
            f.write("nested_value: 42\n")

        main_path = os.path.join(tmpdir, "main.yaml")
        with open(main_path, "w") as f:
            f.write(f"config: !include file:{inc_path}\n")

        loader = DraconLoader()
        comp = loader.compose(main_path)

        nested = comp.root["config"]["nested_value"]
        ctx = nested.source_context
        assert ctx is not None
        # verify include trace was added with keypath info
        assert len(ctx.include_trace) >= 1
        assert ctx.include_trace[0].keypath == "/config"
        assert ctx.keypath == "/nested_value"


def test_interpolable_nodes_have_context():
    """InterpolableNodes should have source context for error reporting."""
    from dracon.loader import DraconLoader
    from dracon.interpolation import InterpolableNode

    yaml_content = """
    computed: ${1 + 2}
    """

    loader = DraconLoader()
    comp = loader.compose_config_from_str(yaml_content)

    # the computed value should be an InterpolableNode with context
    computed_node = comp.root["computed"]
    assert isinstance(computed_node, InterpolableNode)
    assert hasattr(computed_node, "source_context")
    assert computed_node.source_context is not None


##────────────────────────────────────────────────────────────────────────────}}}

## {{{                    --     Integration tests     --


def test_error_in_interpolation():
    """Test that interpolation errors have proper source context."""
    from dracon.loader import DraconLoader
    from dracon.diagnostics import EvaluationError

    yaml_content = """
    value: ${undefined_var}
    """

    loader = DraconLoader()
    config = loader.loads(yaml_content)

    with pytest.raises(EvaluationError) as excinfo:
        config.resolve_all_lazy()

    # the error should be an EvaluationError with the expression
    err = excinfo.value
    assert "undefined_var" in str(err) or (err.expression and "undefined_var" in err.expression)


def test_evaluation_error_has_source_context():
    """Test that EvaluationError contains source context from the YAML node."""
    from dracon.loader import DraconLoader
    from dracon.diagnostics import EvaluationError
    from dracon.interpolation import InterpolableNode

    yaml_content = """
    line1: 1
    line2: 2
    computed: ${nonexistent_func()}
    """

    loader = DraconLoader()
    comp = loader.compose_config_from_str(yaml_content)

    # the computed node should have source context
    computed_node = comp.root["computed"]
    assert isinstance(computed_node, InterpolableNode)
    ctx = computed_node.source_context
    assert ctx is not None
    # line 4 (1-indexed) is where "computed:" is defined
    assert ctx.line >= 1


def test_error_in_pydantic_validation():
    """Test that Pydantic validation errors have proper source context."""
    from dracon.loader import DraconLoader
    from pydantic import BaseModel

    class Config(BaseModel):
        port: int

    yaml_content = """
    port: not_an_integer
    """

    loader = DraconLoader()

    with pytest.raises(Exception) as excinfo:
        config = loader.loads(yaml_content)
        Config.model_validate(config)

    assert excinfo.value is not None


def test_error_in_include():
    """Test that include errors have proper source context."""
    from dracon.loader import DraconLoader

    yaml_content = """
    config: !include file:nonexistent_file.yaml
    """

    loader = DraconLoader()

    with pytest.raises(Exception) as excinfo:
        loader.loads(yaml_content)

    assert excinfo.value is not None


##────────────────────────────────────────────────────────────────────────────}}}
