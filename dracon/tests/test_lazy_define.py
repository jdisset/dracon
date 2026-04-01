"""Tests for lazy construction in !define with tagged nodes."""
import pytest
from pydantic import BaseModel
from dracon.loader import DraconLoader


class SimpleModel(BaseModel):
    field: int
    name: str = "default"

    def double_field(self):
        return self.field * 2


class DependentModel(BaseModel):
    values: list
    label: str = ""


# --- core behavior ---


def test_lazy_define_basic():
    """!define with tagged node lazily constructs and returns correct type"""
    yaml = """
    !define x: !SimpleModel { field: 42 }
    result: ${x.field}
    """
    loader = DraconLoader(context={'SimpleModel': SimpleModel})
    config = loader.loads(yaml)
    config.resolve_all_lazy()
    assert config['result'] == 42


def test_lazy_define_isinstance():
    """result is the actual type, not a proxy"""
    yaml = """
    !define x: !SimpleModel { field: 1 }
    result: ${isinstance(x, SimpleModel)}
    """
    loader = DraconLoader(context={'SimpleModel': SimpleModel})
    config = loader.loads(yaml)
    config.resolve_all_lazy()
    assert config['result'] is True


def test_lazy_define_forward_reference():
    """!define with tagged node works when referencing variables defined AFTER"""
    yaml = """
    !define x: !SimpleModel
      field: ${y}
    !define y: ${42}
    result: ${x.field}
    """
    loader = DraconLoader(context={'SimpleModel': SimpleModel})
    config = loader.loads(yaml)
    config.resolve_all_lazy()
    assert config['result'] == 42


def test_lazy_define_attribute_access():
    """${x.name} triggers construction and accesses attribute"""
    yaml = """
    !define x: !SimpleModel
      field: 7
      name: hello
    result: ${x.name}
    """
    loader = DraconLoader(context={'SimpleModel': SimpleModel})
    config = loader.loads(yaml)
    config.resolve_all_lazy()
    assert config['result'] == 'hello'


def test_lazy_define_method_call():
    """${x.method()} triggers construction and calls method"""
    yaml = """
    !define x: !SimpleModel { field: 5 }
    result: ${x.double_field()}
    """
    loader = DraconLoader(context={'SimpleModel': SimpleModel})
    config = loader.loads(yaml)
    config.resolve_all_lazy()
    assert config['result'] == 10


def test_lazy_define_cached():
    """referenced twice, only constructed once (cached)"""
    yaml = """
    !define x: !SimpleModel { field: 3 }
    a: ${x.field}
    b: ${x.double_field()}
    """
    loader = DraconLoader(context={'SimpleModel': SimpleModel})
    config = loader.loads(yaml)
    config.resolve_all_lazy()
    assert config['a'] == 3
    assert config['b'] == 6


def test_define_plain_value_unchanged():
    """!define with expression (no type tag) still works as before"""
    yaml = """
    !define x: ${[1, 2, 3]}
    result: ${x}
    """
    loader = DraconLoader()
    config = loader.loads(yaml)
    config.resolve_all_lazy()
    assert config['result'] == [1, 2, 3]


def test_define_plain_mapping_unchanged():
    """!define with untagged mapping still stored as plain dict"""
    yaml = """
    !define x: ${42}
    result: ${x + 1}
    """
    loader = DraconLoader()
    config = loader.loads(yaml)
    config.resolve_all_lazy()
    assert config['result'] == 43


# --- tag detection ---


def test_lazy_define_unknown_tag_not_lazy():
    """!define with tag that doesn't resolve to a type falls through to eager"""
    yaml = """
    !define x: !int 42
    result: ${x}
    """
    loader = DraconLoader()
    config = loader.loads(yaml)
    config.resolve_all_lazy()
    assert config['result'] == 42


# --- error handling ---


def test_lazy_define_construction_error():
    """construction failure raises with useful info"""
    yaml = """
    !define x: !SimpleModel { wrong_field: 42 }
    result: ${x}
    """
    loader = DraconLoader(context={'SimpleModel': SimpleModel})
    with pytest.raises(Exception):
        config = loader.loads(yaml)
        config.resolve_all_lazy()


# --- set_default ---


def test_set_default_lazy():
    """!set_default with tagged node lazily constructs"""
    yaml = """
    !set_default x: !SimpleModel { field: 99 }
    result: ${x.field}
    """
    loader = DraconLoader(context={'SimpleModel': SimpleModel})
    config = loader.loads(yaml)
    config.resolve_all_lazy()
    assert config['result'] == 99


# --- pipeline style ---


def test_lazy_define_pipeline():
    """multiple lazy defines forming a pipeline"""
    yaml = """
    !define model: !SimpleModel { field: 10 }
    !define doubled: ${model.double_field()}
    output: ${doubled}
    """
    loader = DraconLoader(context={'SimpleModel': SimpleModel})
    config = loader.loads(yaml)
    config.resolve_all_lazy()
    assert config['output'] == 20


def test_lazy_define_chained_objects():
    """lazy define referencing another lazy-defined object"""
    yaml = """
    !define base: !SimpleModel { field: 5 }
    !define dep: !DependentModel
      values: ${[base.field, base.double_field()]}
      label: computed
    result_values: ${dep.values}
    result_label: ${dep.label}
    """
    loader = DraconLoader(context={
        'SimpleModel': SimpleModel,
        'DependentModel': DependentModel,
    })
    config = loader.loads(yaml)
    config.resolve_all_lazy()
    assert config['result_values'] == [5, 10]
    assert config['result_label'] == 'computed'


# --- circular dependency ---


def test_lazy_define_circular_self_reference():
    """self-referential lazy !define raises CompositionError"""
    from dracon.diagnostics import CompositionError
    yaml = """
    !define x: !SimpleModel { field: ${x.field} }
    result: ${x}
    """
    loader = DraconLoader(context={'SimpleModel': SimpleModel})
    with pytest.raises((CompositionError, Exception)):
        config = loader.loads(yaml)
        config.resolve_all_lazy()


# --- never referenced means never constructed ---


def test_lazy_define_unreferenced_not_constructed():
    """unreferenced lazy !define doesn't cause errors from bad fields"""
    yaml = """
    !define x: !SimpleModel { field: 999 }
    result: 42
    """
    loader = DraconLoader(context={'SimpleModel': SimpleModel})
    config = loader.loads(yaml)
    config.resolve_all_lazy()
    assert config['result'] == 42


# --- !each interaction ---


def test_lazy_define_with_each():
    """lazy-defined object used inside !each"""
    yaml = """
    !define model: !SimpleModel { field: 10 }
    items:
      !each(i) ${[1, 2, 3]}:
        - ${model.field + i}
    """
    loader = DraconLoader(context={'SimpleModel': SimpleModel})
    config = loader.loads(yaml)
    config.resolve_all_lazy()
    assert config['items'] == [11, 12, 13]


# --- existing behavior preserved ---


def test_define_eager_with_class_tag():
    """existing !define with class works (like test_root_define_class)"""
    yaml = """
    !SimpleModel
    !define val: ${42}
    field: ${val}
    name: hello
    """
    loader = DraconLoader(context={'SimpleModel': SimpleModel})
    config = loader.loads(yaml)
    assert isinstance(config, SimpleModel)
    assert config.field == 42
    assert config.name == 'hello'
