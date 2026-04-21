"""Tests for lazy construction in !define with tagged nodes."""
import pytest
from copy import deepcopy
from pydantic import BaseModel
from typing import Optional
from dracon.loader import DraconLoader
from dracon.diagnostics import CompositionError
from dracon.interpolation import LazyConstructable, _LC_SENTINEL


class SimpleModel(BaseModel):
    field: int
    name: str = "default"

    def double_field(self):
        return self.field * 2


class DependentModel(BaseModel):
    values: list
    label: str = ""


class RefModel(BaseModel):
    ref: Optional[int] = None
    tag: str = ""


class Counter(BaseModel):
    """model with a class-level counter to verify construction count"""
    value: int
    _count = 0

    def model_post_init(self, __context):
        Counter._count += 1


CTX = {'SimpleModel': SimpleModel}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# core behavior
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_lazy_define_basic():
    config = DraconLoader(context=CTX).loads("""
    !define x: !SimpleModel
      field: 42
    result: ${x.field}
    """)
    config.resolve_all_lazy()
    assert config['result'] == 42


def test_lazy_define_isinstance():
    """result is the actual type, not a proxy"""
    config = DraconLoader(context=CTX).loads("""
    !define x: !SimpleModel
      field: 1
    result: ${isinstance(x, SimpleModel)}
    """)
    config.resolve_all_lazy()
    assert config['result'] is True


def test_lazy_define_forward_reference():
    """!define with tagged node works when referencing variables defined AFTER"""
    config = DraconLoader(context=CTX).loads("""
    !define x: !SimpleModel
      field: ${y}
    !define y: ${42}
    result: ${x.field}
    """)
    config.resolve_all_lazy()
    assert config['result'] == 42


def test_lazy_define_backward_reference():
    """!define with tagged node works when referencing variables defined BEFORE"""
    config = DraconLoader(context=CTX).loads("""
    !define y: ${42}
    !define x: !SimpleModel
      field: ${y}
    result: ${x.field}
    """)
    config.resolve_all_lazy()
    assert config['result'] == 42


def test_lazy_define_attribute_access():
    config = DraconLoader(context=CTX).loads("""
    !define x: !SimpleModel
      field: 7
      name: hello
    result: ${x.name}
    """)
    config.resolve_all_lazy()
    assert config['result'] == 'hello'


def test_lazy_define_method_call():
    config = DraconLoader(context=CTX).loads("""
    !define x: !SimpleModel
      field: 5
    result: ${x.double_field()}
    """)
    config.resolve_all_lazy()
    assert config['result'] == 10


def test_lazy_define_cached():
    """referenced twice, only constructed once"""
    Counter._count = 0
    config = DraconLoader(context={'Counter': Counter}).loads("""
    !define x: !Counter
      value: 3
    a: ${x.value}
    b: ${x.value}
    """)
    config.resolve_all_lazy()
    assert config['a'] == 3
    assert config['b'] == 3
    assert Counter._count == 1


def test_lazy_define_unreferenced_not_constructed():
    """unreferenced lazy !define is never constructed"""
    Counter._count = 0
    config = DraconLoader(context={'Counter': Counter}).loads("""
    !define x: !Counter
      value: 999
    result: 42
    """)
    config.resolve_all_lazy()
    assert config['result'] == 42
    assert Counter._count == 0


def test_define_plain_value_unchanged():
    config = DraconLoader().loads("""
    !define x: ${[1, 2, 3]}
    result: ${x}
    """)
    config.resolve_all_lazy()
    assert config['result'] == [1, 2, 3]


def test_define_plain_scalar_unchanged():
    config = DraconLoader().loads("""
    !define x: ${42}
    result: ${x + 1}
    """)
    config.resolve_all_lazy()
    assert config['result'] == 43


def test_define_untagged_mapping_not_lazy():
    """mapping without a type tag is eagerly constructed as a dict"""
    config = DraconLoader().loads("""
    !define x:
      a: 1
      b: 2
    result_a: ${x['a']}
    """)
    config.resolve_all_lazy()
    assert config['result_a'] == 1


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# tag detection
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_scalar_type_tag_not_lazy():
    """!int, !float etc are scalar tags, not lazy-constructable"""
    config = DraconLoader().loads("""
    !define x: !int 42
    result: ${x}
    """)
    config.resolve_all_lazy()
    assert config['result'] == 42


def test_instruction_tag_not_lazy():
    """!define value with !if is processed as instruction, not lazy"""
    config = DraconLoader().loads("""
    !define x:
      !if ${True}:
        then: 42
        else: 0
    result: ${x}
    """)
    config.resolve_all_lazy()
    assert config['result'] == 42


def test_context_resolved_type_tag_is_lazy():
    config = DraconLoader(context=CTX).loads("""
    !define x: !SimpleModel
      field: 7
    result: ${x.field}
    """)
    config.resolve_all_lazy()
    assert config['result'] == 7


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# error handling
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_construction_error_includes_tag():
    with pytest.raises(Exception, match="SimpleModel"):
        config = DraconLoader(context=CTX).loads("""
        !define x: !SimpleModel
          wrong_field: 42
        result: ${x}
        """)
        config.resolve_all_lazy()


def test_construction_error_includes_source():
    with pytest.raises(Exception, match="defined at"):
        config = DraconLoader(context=CTX).loads("""
        !define x: !SimpleModel
          wrong_field: 42
        result: ${x}
        """)
        config.resolve_all_lazy()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# circular dependencies
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_circular_self_reference():
    with pytest.raises(Exception):
        config = DraconLoader(context=CTX).loads("""
        !define x: !SimpleModel
          field: ${x.field}
        result: ${x}
        """)
        config.resolve_all_lazy()


def test_circular_mutual_reference():
    with pytest.raises(Exception):
        config = DraconLoader(context={'RefModel': RefModel}).loads("""
        !define a: !RefModel
          ref: ${b.ref}
          tag: a
        !define b: !RefModel
          ref: ${a.ref}
          tag: b
        result: ${a.tag}
        """)
        config.resolve_all_lazy()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# coercion (!define:type)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_define_type_coercion_with_non_lazy():
    config = DraconLoader().loads("""
    !define:float x: ${2 + 3}
    result: ${x}
    """)
    config.resolve_all_lazy()
    assert config['result'] == 5.0
    assert isinstance(config['result'], float)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# !set_default interaction
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_set_default_lazy():
    config = DraconLoader(context=CTX).loads("""
    !set_default x: !SimpleModel
      field: 99
    result: ${x.field}
    """)
    config.resolve_all_lazy()
    assert config['result'] == 99


def test_set_default_lazy_overridden_by_define():
    config = DraconLoader(context=CTX).loads("""
    !set_default x: !SimpleModel
      field: 1
    !define x: !SimpleModel
      field: 2
    result: ${x.field}
    """)
    config.resolve_all_lazy()
    assert config['result'] == 2


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# pipeline style
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_pipeline():
    config = DraconLoader(context=CTX).loads("""
    !define model: !SimpleModel
      field: 10
    !define doubled: ${model.double_field()}
    output: ${doubled}
    """)
    config.resolve_all_lazy()
    assert config['output'] == 20


def test_chained_objects():
    config = DraconLoader(context={
        'SimpleModel': SimpleModel,
        'DependentModel': DependentModel,
    }).loads("""
    !define base: !SimpleModel
      field: 5
    !define dep: !DependentModel
      values: ${[base.field, base.double_field()]}
      label: computed
    result_values: ${dep.values}
    result_label: ${dep.label}
    """)
    config.resolve_all_lazy()
    assert config['result_values'] == [5, 10]
    assert config['result_label'] == 'computed'


def test_three_stage_pipeline():
    config = DraconLoader(context={
        'SimpleModel': SimpleModel,
        'DependentModel': DependentModel,
    }).loads("""
    !define stage1: !SimpleModel
      field: 3
    !define stage2: !SimpleModel
      field: ${stage1.double_field()}
    !define stage3: !DependentModel
      values: ${[stage1.field, stage2.field]}
    result: ${stage3.values}
    """)
    config.resolve_all_lazy()
    assert config['result'] == [3, 6]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# !each interaction
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_lazy_outside_each_shared():
    """lazy-defined object outside !each is constructed once, shared"""
    config = DraconLoader(context=CTX).loads("""
    !define model: !SimpleModel
      field: 10
    items:
      !each(i) ${[1, 2, 3]}:
        - ${model.field + i}
    """)
    config.resolve_all_lazy()
    assert config['items'] == [11, 12, 13]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# !if interaction
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_conditional_object_binding_then():
    """!if selects the then branch, lazy define constructs it"""
    config = DraconLoader(context=CTX).loads("""
    !define fast_mode: ${True}
    !define strategy:
      !if ${fast_mode}:
        then: !SimpleModel
          field: 16
        else: !SimpleModel
          field: 64
    result: ${strategy.field}
    """)
    config.resolve_all_lazy()
    assert config['result'] == 16


def test_conditional_object_binding_else():
    config = DraconLoader(context=CTX).loads("""
    !define fast_mode: ${False}
    !define strategy:
      !if ${fast_mode}:
        then: !SimpleModel
          field: 16
        else: !SimpleModel
          field: 64
    result: ${strategy.field}
    """)
    config.resolve_all_lazy()
    assert config['result'] == 64


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# existing behavior preserved
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_root_tag_with_define():
    config = DraconLoader(context=CTX).loads("""
    !SimpleModel
    !define val: ${42}
    field: ${val}
    name: hello
    """)
    assert isinstance(config, SimpleModel)
    assert config.field == 42
    assert config.name == 'hello'


def test_existing_eager_define_still_works():
    config = DraconLoader().loads("""
    !define x: !int 42
    !define y: ${x + 1}
    result: ${y}
    """)
    config.resolve_all_lazy()
    assert config['result'] == 43


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# LazyConstructable unit tests
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_lazy_constructable_repr_unresolved():
    from dracon.nodes import DraconScalarNode
    node = DraconScalarNode(tag='!Foo', value='bar')
    lc = LazyConstructable(node=node, loader=None)
    assert 'Foo' in repr(lc)
    assert 'resolved=False' in repr(lc)


def test_lazy_constructable_deepcopy_clears_result():
    from dracon.nodes import DraconScalarNode
    node = DraconScalarNode(tag='!Foo', value='bar')
    lc = LazyConstructable(node=node, loader=None)
    lc._result = "resolved_value"
    clone = deepcopy(lc)
    assert clone._result is _LC_SENTINEL
    assert clone._loader is lc._loader
    assert clone._source is lc._source


def test_lazy_constructable_deepcopy_shares_defined_vars():
    from dracon.nodes import DraconScalarNode
    node = DraconScalarNode(tag='!Foo', value='bar')
    dv = {'x': 42}
    lc = LazyConstructable(node=node, loader=None, defined_vars=dv)
    clone = deepcopy(lc)
    assert clone._defined_vars is dv


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# _is_constructable_type_tag unit tests
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_is_constructable_type_tag():
    from dracon.instructions import _is_constructable_type_tag
    from dracon.nodes import DraconScalarNode
    from dracon.composer import DraconMappingNode

    loader = DraconLoader(context=CTX)

    # scalar node -> never constructable
    assert _is_constructable_type_tag(
        DraconScalarNode(tag='!SimpleModel', value='42'), loader) is False

    # mapping with known type -> constructable
    assert _is_constructable_type_tag(
        DraconMappingNode(tag='!SimpleModel', value=[]), loader) is True

    # mapping with instruction tag -> not constructable
    assert _is_constructable_type_tag(
        DraconMappingNode(tag='!define', value=[]), loader) is False

    # mapping with unknown *identifier* tag -> constructable (deferred so
    # vocabularies merge-included later can still resolve it)
    assert _is_constructable_type_tag(
        DraconMappingNode(tag='!CompletelyFakeType', value=[]), loader) is True

    # compound tag (contains ':' or '.') falls through to eager path
    assert _is_constructable_type_tag(
        DraconMappingNode(tag='!fn:unknown_name', value=[]), loader) is False
    assert _is_constructable_type_tag(
        DraconMappingNode(tag='!unknown.Class', value=[]), loader) is False

    # mapping with builtin yaml tag -> not constructable
    assert _is_constructable_type_tag(
        DraconMappingNode(tag='tag:yaml.org,2002:map', value=[]), loader) is False

    # mapping with deferred tag -> not constructable
    assert _is_constructable_type_tag(
        DraconMappingNode(tag='!deferred:Foo', value=[]), loader) is False

    # no tag -> not constructable
    assert _is_constructable_type_tag(
        DraconMappingNode(tag='', value=[]), loader) is False


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# e2e: file-based loading
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_define_unknown_tag_surfaces_at_use_time():
    """Deferred unknown tags give a clear error when ${g} is evaluated,
    not silently hidden. Truly-unused !define is allowed (lazy)."""
    loader = DraconLoader()
    cfg = loader.loads("""
!define g: !TotallyUnknownSym
  key: value
result: ${g}
""")
    with pytest.raises(Exception) as exc_info:
        cfg.resolve_all_lazy()
    assert "TotallyUnknownSym" in str(exc_info.value) or "TotallyUnknownSym" in repr(exc_info.value)


def test_define_unused_unknown_tag_is_silently_deferred():
    """Unused !define with unknown identifier tag must not error at load time."""
    loader = DraconLoader()
    cfg = loader.loads("""
!define g: !TotallyUnknownSym
  key: value
result: 42
""")
    assert cfg['result'] == 42


def test_e2e_file_load(tmp_path):
    """lazy define works when loading from a file"""
    (tmp_path / "config.yaml").write_text("""
!define model: !SimpleModel
  field: 77
result: ${model.double_field()}
""")
    config = DraconLoader(context=CTX).load(str(tmp_path / "config.yaml"))
    config.resolve_all_lazy()
    assert config['result'] == 154


def test_e2e_file_forward_ref(tmp_path):
    """forward references work from files"""
    (tmp_path / "config.yaml").write_text("""
!define model: !SimpleModel
  field: ${val}
!define val: ${10}
result: ${model.field}
""")
    config = DraconLoader(context=CTX).load(str(tmp_path / "config.yaml"))
    config.resolve_all_lazy()
    assert config['result'] == 10


def test_e2e_multi_file(tmp_path):
    """lazy define works across multi-file composition"""
    (tmp_path / "base.yaml").write_text("!define base_val: ${100}\n")
    (tmp_path / "main.yaml").write_text("""
<<: !include file:$DIR/base.yaml
!define model: !SimpleModel
  field: ${base_val}
result: ${model.field}
""")
    config = DraconLoader(context=CTX).load(str(tmp_path / "main.yaml"))
    config.resolve_all_lazy()
    assert config['result'] == 100


def test_e2e_include_defines_var_for_lazy(tmp_path):
    """variable defined in included file is available to lazy construction"""
    (tmp_path / "vars.yaml").write_text("!define multiplier: ${3}\n")
    (tmp_path / "main.yaml").write_text("""
<<: !include file:$DIR/vars.yaml
!define model: !SimpleModel
  field: ${multiplier}
result: ${model.double_field()}
""")
    config = DraconLoader(context=CTX).load(str(tmp_path / "main.yaml"))
    config.resolve_all_lazy()
    assert config['result'] == 6


def test_e2e_lazy_with_template_anchor(tmp_path):
    """lazy define works with __dracon__ template anchors"""
    (tmp_path / "config.yaml").write_text("""
__dracon__: &tpl
  !set_default base_field: 1

item:
  !define base_field: ${50}
  <<: *tpl
  !define model: !SimpleModel
    field: ${base_field}
  result: ${model.double_field()}
""")
    config = DraconLoader(context=CTX).load(str(tmp_path / "config.yaml"))
    config.resolve_all_lazy()
    assert config['item']['result'] == 100


def test_e2e_pipeline_across_files(tmp_path):
    """full pipeline with lazy defines, included file provides a stage"""
    (tmp_path / "stage1.yaml").write_text("""
!define stage1: !SimpleModel
  field: 7
""")
    (tmp_path / "main.yaml").write_text("""
<<: !include file:$DIR/stage1.yaml
!define stage2: !DependentModel
  values: ${[stage1.field, stage1.double_field()]}
  label: pipeline
values: ${stage2.values}
label: ${stage2.label}
""")
    config = DraconLoader(context={
        'SimpleModel': SimpleModel,
        'DependentModel': DependentModel,
    }).load(str(tmp_path / "main.yaml"))
    config.resolve_all_lazy()
    assert config['values'] == [7, 14]
    assert config['label'] == 'pipeline'
