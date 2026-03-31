# tests for the extensible instruction registry (refactor 06)
# and node copy/mixin correctness (refactor 05)
import pytest
from dracon.instructions import (
    Instruction,
    INSTRUCTION_REGISTRY,
    register_instruction,
    match_instruct,
    unpack_mapping_key,
    Define,
    SetDefault,
    Each,
    If,
    Require,
    Assert,
)
from dracon.nodes import IncludeNode, SourceContextMixin
from dracon.loader import DraconLoader
import dracon


class TestInstructionRegistry:
    """Registry dict replaces the old AVAILABLE_INSTRUCTIONS list."""

    def test_registry_is_dict(self):
        assert isinstance(INSTRUCTION_REGISTRY, dict)

    def test_builtin_tags_present(self):
        for tag in ('!define', '!define?', '!set_default', '!each', '!if', '!require', '!assert'):
            assert tag in INSTRUCTION_REGISTRY, f"{tag} missing from registry"

    def test_define_question_maps_to_set_default(self):
        assert INSTRUCTION_REGISTRY['!define?'] is SetDefault

    def test_set_default_still_maps(self):
        assert INSTRUCTION_REGISTRY['!set_default'] is SetDefault


class TestRegisterInstruction:
    """register_instruction() adds custom instruction classes."""

    def test_register_custom_instruction(self):
        class MyInst(Instruction):
            @staticmethod
            def match(value):
                return MyInst() if value == '!my_inst' else None

            def process(self, comp_res, path, loader):
                return comp_res

        register_instruction('!my_inst', MyInst)
        assert INSTRUCTION_REGISTRY['!my_inst'] is MyInst
        del INSTRUCTION_REGISTRY['!my_inst']

    def test_register_auto_prefixes_bang(self):
        class Tmp(Instruction):
            @staticmethod
            def match(value):
                return Tmp() if value == '!tmp' else None

            def process(self, comp_res, path, loader):
                return comp_res

        register_instruction('tmp', Tmp)
        assert '!tmp' in INSTRUCTION_REGISTRY
        del INSTRUCTION_REGISTRY['!tmp']


class TestMatchInstruct:
    """match_instruct uses fast dict lookup then fallback loop."""

    def test_exact_match_define(self):
        inst = match_instruct('!define')
        assert isinstance(inst, Define)

    def test_exact_match_set_default(self):
        inst = match_instruct('!set_default')
        assert isinstance(inst, SetDefault)

    def test_exact_match_define_question(self):
        inst = match_instruct('!define?')
        assert isinstance(inst, SetDefault)

    def test_parametric_each(self):
        inst = match_instruct('!each(x)')
        assert isinstance(inst, Each)
        assert inst.var_name == 'x'

    def test_no_match(self):
        assert match_instruct('!nonexistent') is None

    def test_trailing_colon_error(self):
        with pytest.raises(ValueError, match="trailing colon"):
            match_instruct('!define:')


class TestDeferredAttribute:
    """Assert.deferred == True, others default to False."""

    def test_assert_is_deferred(self):
        assert Assert.deferred is True

    def test_define_not_deferred(self):
        assert not getattr(Define, 'deferred', False)

    def test_instruction_base_not_deferred(self):
        assert Instruction.deferred is False


class TestDefineQuestionAlias:
    """!define? works as an alias for !set_default in actual configs."""

    def test_define_question_loads(self):
        loader = DraconLoader(enable_interpolation=True)
        cfg = loader.loads("""
        !define? x: 42
        a: ${x}
        """)
        cfg.resolve_all_lazy()
        assert cfg.a == 42

    def test_define_question_yields_to_define(self):
        loader = DraconLoader(enable_interpolation=True)
        cfg = loader.loads("""
        !define? x: 1
        !define x: 2
        a: ${x}
        """)
        cfg.resolve_all_lazy()
        assert cfg.a == 2


class TestPublicAPI:
    """register_instruction and Instruction are exported from dracon."""

    def test_register_instruction_exported(self):
        assert hasattr(dracon, 'register_instruction')

    def test_instruction_exported(self):
        assert hasattr(dracon, 'Instruction')

    def test_unpack_mapping_key_exported(self):
        assert hasattr(dracon, 'unpack_mapping_key')


class TestIncludeNodeCopy:
    """IncludeNode.copy() preserves source_context and optional flag."""

    def test_copy_preserves_source_context(self):
        node = IncludeNode(
            value='file:test.yaml',
            context={'FILE_NAME': 'test.yaml'},
            optional=True,
            source_context='fake_ctx',
        )
        copied = node.copy()
        assert copied._source_context == 'fake_ctx'
        assert copied.optional is True
        assert copied.value == 'file:test.yaml'
        assert copied.context is not node.context  # separate dict

    def test_copy_without_source_context(self):
        node = IncludeNode(value='file:a.yaml', context={})
        copied = node.copy()
        assert copied._source_context is None
        assert copied.optional is False


class TestSourceContextMixin:
    """SourceContextMixin provides lazy source_context on all node types."""

    def test_mixin_in_mro(self):
        from dracon.nodes import DraconScalarNode, DraconMappingNode, DraconSequenceNode
        for cls in (DraconScalarNode, DraconMappingNode, DraconSequenceNode):
            assert issubclass(cls, SourceContextMixin)
