import pytest
from pathlib import Path
from typing import Annotated, List, Optional
from pydantic import BaseModel

from dracon import (
    Arg,
    DeferredNode,
    DraconLoader,
    construct,
    make_callable,
    dracon_program,
    make_program,
)


class InnerModel(BaseModel):
    value: int
    name: str = "default"


class OuterModel(BaseModel):
    inner: InnerModel
    count: int = 1


@pytest.fixture(scope="module")
def config_dir(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("callable_configs")

    (tmp / "simple.yaml").write_text("""
value: 42
name: "simple_test"
""")

    (tmp / "with_interp.yaml").write_text("""
value: ${BASE_VALUE}
name: "interpolated_${suffix}"
""")

    (tmp / "nested.yaml").write_text("""
inner:
    value: ${inner_val}
    name: nested_inner
count: ${count_val}
""")

    (tmp / "outer_simple.yaml").write_text("""
inner:
    value: 10
    name: outer_inner
count: 5
""")

    (tmp / "program_config.yaml").write_text("""
items:
    - name: item1
      value: 100
    - name: item2
      value: 200
prefix: "test_"
""")

    (tmp / "deferred_items.yaml").write_text("""
items:
    - !deferred
      name: "${item_prefix}1"
      value: ${base + 0}
    - !deferred
      name: "${item_prefix}2"
      value: ${base + 100}
prefix: "loaded_"
""")

    yield tmp


class TestMakeCallable:
    def test_simple_load(self, config_dir):
        cfg_path = config_dir / "simple.yaml"
        fn = make_callable(str(cfg_path))
        result = fn()
        assert result['value'] == 42
        assert result['name'] == "simple_test"

    def test_with_interpolation(self, config_dir):
        cfg_path = config_dir / "with_interp.yaml"
        fn = make_callable(str(cfg_path))
        result = fn(BASE_VALUE=99, suffix="custom")
        assert result['value'] == 99
        assert result['name'] == "interpolated_custom"

    def test_with_context_types(self, config_dir):
        cfg_path = config_dir / "simple.yaml"
        fn = make_callable(str(cfg_path), context_types=[InnerModel])
        result = fn()
        assert result['value'] == 42

    def test_with_explicit_context(self, config_dir):
        cfg_path = config_dir / "with_interp.yaml"
        fn = make_callable(str(cfg_path), context={'BASE_VALUE': 50})
        result = fn(suffix="override")
        assert result['value'] == 50
        assert result['name'] == "interpolated_override"

    def test_nested_model(self, config_dir):
        cfg_path = config_dir / "nested.yaml"
        fn = make_callable(str(cfg_path))
        result = fn(inner_val=77, count_val=3)
        assert result['inner']['value'] == 77
        assert result['inner']['name'] == "nested_inner"
        assert result['count'] == 3

    def test_from_deferred_node(self, config_dir):
        cfg_path = config_dir / "with_interp.yaml"
        loader = DraconLoader(deferred_paths=['/'])
        node = loader.load(str(cfg_path))
        assert isinstance(node, DeferredNode)
        fn = make_callable(node)
        result = fn(BASE_VALUE=123, suffix="from_node")
        assert result['value'] == 123
        assert result['name'] == "interpolated_from_node"

    def test_callable_reuse(self, config_dir):
        cfg_path = config_dir / "with_interp.yaml"
        fn = make_callable(str(cfg_path))
        r1 = fn(BASE_VALUE=1, suffix="a")
        r2 = fn(BASE_VALUE=2, suffix="b")
        assert r1['value'] == 1
        assert r1['name'] == "interpolated_a"
        assert r2['value'] == 2
        assert r2['name'] == "interpolated_b"

    def test_invalid_input_type(self):
        with pytest.raises(TypeError, match="Expected path or DeferredNode"):
            make_callable(12345)

    def test_auto_context(self, config_dir):
        class LocalType(BaseModel):
            x: int

        cfg_path = config_dir / "simple.yaml"
        fn = make_callable(str(cfg_path), auto_context=True)
        result = fn()
        assert result['value'] == 42


class ItemModel(BaseModel):
    name: str
    value: int


class ProgramConfig(BaseModel):
    items: List[ItemModel]
    prefix: str = ""

    def run(self):
        return [f"{self.prefix}{item.name}:{item.value}" for item in self.items]


class DeferredProgramConfig(BaseModel):
    items: Annotated[List[DeferredNode[ItemModel]], Arg(help="Deferred items")]
    prefix: str = ""

    def run(self):
        constructed = [item.construct() for item in self.items]
        return [f"{self.prefix}{c.name}:{c.value}" for c in constructed]


class TestDraconProgram:
    def test_decorator_basic(self, config_dir):
        @dracon_program(
            name="test-prog",
            context_types=[ItemModel],
        )
        class TestConfig(BaseModel):
            items: List[ItemModel]
            prefix: str = ""

            def run(self):
                return len(self.items)

        cfg_path = config_dir / "program_config.yaml"
        result = TestConfig.invoke(str(cfg_path))
        assert result == 2

    def test_cli_method(self, config_dir):
        @dracon_program(
            name="cli-test",
            context_types=[ItemModel],
        )
        class CliConfig(BaseModel):
            items: List[ItemModel]
            prefix: str = ""

            def run(self):
                return self.prefix + str(len(self.items))

        cfg_path = config_dir / "program_config.yaml"
        result = CliConfig.cli([f"+{cfg_path}"])
        assert result == "test_2"

    def test_from_config_method(self, config_dir):
        @dracon_program(
            name="from-config-test",
            context_types=[ItemModel],
        )
        class FromConfigTest(BaseModel):
            items: List[ItemModel]
            prefix: str = ""

        cfg_path = config_dir / "program_config.yaml"
        instance = FromConfigTest.from_config(str(cfg_path))
        assert isinstance(instance, FromConfigTest)
        assert len(instance.items) == 2
        assert instance.prefix == "test_"

    def test_load_method(self, config_dir):
        @dracon_program(
            name="load-test",
            context_types=[ItemModel],
        )
        class LoadTest(BaseModel):
            items: List[ItemModel]
            prefix: str = ""

        cfg_path = config_dir / "program_config.yaml"
        instance = LoadTest.load(str(cfg_path))
        assert isinstance(instance, LoadTest)
        assert len(instance.items) == 2

    def test_invoke_with_context(self, config_dir):
        @dracon_program(
            name="ctx-invoke",
            context_types=[ItemModel],
        )
        class CtxInvoke(BaseModel):
            items: List[ItemModel]
            computed_count: int = 0

            def run(self):
                return self.computed_count

        cfg_content = """
items:
    - name: x
      value: 1
computed_count: ${base_count + len(extra_items)}
"""
        cfg_path = config_dir / "ctx_invoke.yaml"
        cfg_path.write_text(cfg_content)

        result = CtxInvoke.invoke(str(cfg_path), base_count=10, extra_items=[1, 2, 3])
        assert result == 13

    def test_deferred_paths(self, config_dir):
        @dracon_program(
            name="deferred-test",
            deferred_paths=["/items.*"],
            context_types=[ItemModel],
        )
        class DeferredTest(BaseModel):
            items: List[DeferredNode[ItemModel]]
            prefix: str = ""
            item_prefix: str = "p"
            base: int = 50

            def run(self):
                results = []
                ctx = {'item_prefix': self.item_prefix, 'base': self.base}
                for item in self.items:
                    c = item.construct(context=ctx)
                    results.append(f"{self.prefix}{c['name']}:{c['value']}")
                return results

        cfg_content = """
items:
    - !deferred
      name: "${item_prefix}1"
      value: ${base + 0}
    - !deferred
      name: "${item_prefix}2"
      value: ${base + 100}
prefix: "loaded_"
item_prefix: "p"
base: 50
"""
        cfg_path = config_dir / "deferred_items_test.yaml"
        cfg_path.write_text(cfg_content)

        result = DeferredTest.invoke(str(cfg_path))
        assert result == ["loaded_p1:50", "loaded_p2:150"]

    def test_without_run_method(self, config_dir):
        @dracon_program(
            name="no-run",
            context_types=[ItemModel],
        )
        class NoRunConfig(BaseModel):
            items: List[ItemModel]
            prefix: str = ""

        cfg_path = config_dir / "program_config.yaml"
        result = NoRunConfig.invoke(str(cfg_path))
        assert isinstance(result, NoRunConfig)
        assert len(result.items) == 2

    def test_class_defaults(self, config_dir):
        @dracon_program()
        class DefaultsTest(BaseModel):
            """This is the docstring"""
            value: int = 10

        assert DefaultsTest._dracon_program_config['name'] == 'DefaultsTest'
        assert DefaultsTest._dracon_program_config['description'] == "This is the docstring"

    def test_custom_context(self, config_dir):
        def custom_func(x):
            return x * 2

        @dracon_program(
            name="custom-ctx",
            context={'double': custom_func, 'BASE': 100},
        )
        class CustomCtxTest(BaseModel):
            result: int = 0

        cfg_content = "result: ${double(BASE) + 5}"
        cfg_path = config_dir / "custom_ctx.yaml"
        cfg_path.write_text(cfg_content)

        instance = CustomCtxTest.from_config(str(cfg_path))
        assert instance.result == 205
        assert 'double' in CustomCtxTest._dracon_program_config['context']

    def test_multiple_config_files(self, config_dir):
        @dracon_program(
            name="multi-config",
            context_types=[ItemModel],
        )
        class MultiConfig(BaseModel):
            items: List[ItemModel] = []
            prefix: str = ""
            extra: str = ""

        base_path = config_dir / "multi_base.yaml"
        base_path.write_text("""
items:
    - name: base_item
      value: 1
prefix: base_
""")

        override_path = config_dir / "multi_override.yaml"
        override_path.write_text("""
extra: overridden
prefix: override_
""")

        instance = MultiConfig.from_config(str(base_path), str(override_path))
        assert instance.prefix == "override_"
        assert instance.extra == "overridden"
        assert len(instance.items) == 1

    def test_auto_context_in_decorator(self, config_dir):
        class LocalModel(BaseModel):
            x: int

        @dracon_program(auto_context=True)
        class AutoCtxDecoratorTest(BaseModel):
            value: int = 1

        assert 'LocalModel' in AutoCtxDecoratorTest._dracon_program_config['context']


class TestInterpolation:
    def test_basic_interpolation(self, config_dir):
        @dracon_program(name="interp-basic", context_types=[ItemModel])
        class InterpBasic(BaseModel):
            value: int = 0

        cfg_content = "value: ${x + y}"
        cfg_path = config_dir / "interp_basic.yaml"
        cfg_path.write_text(cfg_content)

        instance = InterpBasic.from_config(str(cfg_path), x=10, y=32)
        assert instance.value == 42

    def test_nested_interpolation(self, config_dir):
        @dracon_program(name="interp-nested", context_types=[ItemModel])
        class InterpNested(BaseModel):
            inner: InnerModel

        cfg_content = """
inner:
    value: ${base * multiplier}
    name: "computed_${base}"
"""
        cfg_path = config_dir / "interp_nested.yaml"
        cfg_path.write_text(cfg_content)

        instance = InterpNested.from_config(str(cfg_path), base=7, multiplier=6)
        assert instance.inner.value == 42
        assert instance.inner.name == "computed_7"

    def test_list_interpolation(self, config_dir):
        @dracon_program(name="interp-list", context_types=[ItemModel])
        class InterpList(BaseModel):
            items: List[ItemModel]
            total: int = 0

        cfg_content = """
items:
    - name: "item_${i}"
      value: ${i * 10}
    - name: "item_${i + 1}"
      value: ${(i + 1) * 10}
total: ${i * 10 + (i + 1) * 10}
"""
        cfg_path = config_dir / "interp_list.yaml"
        cfg_path.write_text(cfg_content)

        instance = InterpList.from_config(str(cfg_path), i=5)
        assert instance.items[0].name == "item_5"
        assert instance.items[0].value == 50
        assert instance.items[1].name == "item_6"
        assert instance.items[1].value == 60
        assert instance.total == 110

    def test_function_interpolation(self, config_dir):
        def compute_hash(s):
            return hash(s) % 1000

        def format_name(prefix, num):
            return f"{prefix}_{num:03d}"

        @dracon_program(
            name="interp-func",
            context={'compute_hash': compute_hash, 'format_name': format_name},
        )
        class InterpFunc(BaseModel):
            hash_val: int = 0
            formatted: str = ""

        cfg_content = """
hash_val: ${compute_hash("test_string")}
formatted: ${format_name("item", 42)}
"""
        cfg_path = config_dir / "interp_func.yaml"
        cfg_path.write_text(cfg_content)

        instance = InterpFunc.from_config(str(cfg_path))
        assert instance.hash_val == compute_hash("test_string")
        assert instance.formatted == "item_042"

    def test_complex_expression_interpolation(self, config_dir):
        def sum_squares(n):
            return sum(x**2 for x in range(n))

        def sum_range(n):
            return sum(range(n))

        @dracon_program(
            name="interp-complex",
            context_types=[ItemModel],
            context={'sum_squares': sum_squares, 'sum_range': sum_range},
        )
        class InterpComplex(BaseModel):
            result: int = 0
            items: List[ItemModel] = []

        cfg_content = """
result: ${sum_squares(n) + offset}
items:
    - name: "sum"
      value: ${sum_range(n)}
"""
        cfg_path = config_dir / "interp_complex.yaml"
        cfg_path.write_text(cfg_content)

        instance = InterpComplex.from_config(str(cfg_path), n=5, offset=100)
        assert instance.result == sum(x**2 for x in range(5)) + 100  # 0+1+4+9+16+100 = 130
        assert instance.items[0].value == sum(range(5))  # 0+1+2+3+4 = 10

    def test_deferred_with_interpolation(self, config_dir):
        @dracon_program(
            name="interp-deferred",
            deferred_paths=["/deferred_item"],
            context_types=[ItemModel],
        )
        class InterpDeferred(BaseModel):
            deferred_item: DeferredNode[ItemModel]
            multiplier: int = 1
            prefix: str = "test"
            base_val: int = 21

        cfg_content = """
deferred_item: !deferred
    name: "deferred_${prefix}"
    value: ${base_val * 2}
multiplier: ${@/base_val}
prefix: "test"
base_val: 21
"""
        cfg_path = config_dir / "interp_deferred.yaml"
        cfg_path.write_text(cfg_content)

        instance = InterpDeferred.from_config(str(cfg_path))
        assert instance.multiplier == 21
        ctx = {'prefix': instance.prefix, 'base_val': instance.base_val}
        constructed = instance.deferred_item.construct(context=ctx)
        assert constructed['name'] == "deferred_test"
        assert constructed['value'] == 42


class TestIntegration:
    def test_make_callable_with_typed_result(self, config_dir):
        cfg_path = config_dir / "simple.yaml"
        fn = make_callable(str(cfg_path), context_types=[InnerModel])
        result = fn()
        model = InnerModel.model_validate(result)
        assert model.value == 42
        assert model.name == "simple_test"

    def test_program_and_callable_together(self, config_dir):
        @dracon_program(
            name="combo",
            context_types=[ItemModel],
        )
        class ComboConfig(BaseModel):
            items: List[ItemModel]
            prefix: str = ""

            def run(self):
                return sum(item.value for item in self.items)

        cfg_path = config_dir / "program_config.yaml"
        program_result = ComboConfig.invoke(str(cfg_path))
        assert program_result == 300

        callable_fn = make_callable(str(cfg_path))
        callable_result = callable_fn()
        assert callable_result['items'][0]['value'] == 100
