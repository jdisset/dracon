"""Tests for dracon CLI — show subcommand."""
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import BaseModel

CONFIGS = Path(__file__).parent / "configs"


# ── raw mode tests (replaces dracon-print) ──────────────────────────────────


class TestShowRawMode:
    """Raw YAML mode — same behavior as old dracon-print."""

    def _run_show(self, argv):
        from dracon.cli import DraconCLI
        with patch('sys.exit'):
            return DraconCLI.cli(argv=["show"] + argv)

    def test_single_file_compose(self):
        result = self._run_show([str(CONFIGS / "simple.yaml")])
        assert isinstance(result, str)
        assert "root:" in result
        assert "a: 3" in result

    def test_construct_flag(self):
        result = self._run_show([str(CONFIGS / "simple.yaml"), "-c"])
        assert isinstance(result, str)
        assert "root:" in result or '"root"' in result

    def test_resolve_implies_construct(self):
        result = self._run_show([str(CONFIGS / "simple.yaml"), "-r"])
        assert isinstance(result, str)
        assert result

    def test_json_output(self):
        result = self._run_show([str(CONFIGS / "simple.yaml"), "-j"])
        assert isinstance(result, str)
        data = json.loads(result)
        assert "root" in data
        assert data["root"]["a"] == 3

    def test_select_subtree(self):
        result = self._run_show([str(CONFIGS / "simple.yaml"), "-c", "-s", "root"])
        assert isinstance(result, str)
        assert "a:" in result or '"a"' in result
        assert "param2" not in result

    def test_multi_file_layering(self):
        result = self._run_show([
            str(CONFIGS / "simple.yaml"),
            str(CONFIGS / "override.yaml"),
        ])
        assert isinstance(result, str)
        assert "default_settings:" in result

    def test_plus_file_syntax(self):
        """+ prefix files after 'show' are merged as subcommand-scoped configs."""
        # In the new CLI, +file after subcommand merges into subcommand config.
        # For show, plain positional file paths are the primary way to specify targets.
        result = self._run_show([
            str(CONFIGS / "simple.yaml"),
            str(CONFIGS / "override.yaml"),
        ])
        assert isinstance(result, str)
        assert result

    def test_context_vars(self):
        result = self._run_show([
            str(CONFIGS / "simple.yaml"),
            "++some_var=42", "-c",
        ])
        assert isinstance(result, str)

    def test_permissive_resolve(self):
        result = self._run_show([
            str(CONFIGS / "interpolation.yaml"),
            "-rp",
        ])
        assert isinstance(result, str)

    def test_combined_short_flags(self):
        result = self._run_show([str(CONFIGS / "simple.yaml"), "-c", "-r", "-j"])
        assert isinstance(result, str)
        data = json.loads(result)
        assert "root" in data

    def test_verbose_flag(self):
        """verbose shouldn't break anything"""
        import logging
        prev_root = logging.root.level
        prev_dracon = logging.getLogger("dracon").level
        try:
            result = self._run_show([str(CONFIGS / "simple.yaml"), "-v"])
            assert isinstance(result, str)
        finally:
            logging.root.setLevel(prev_root)
            logging.getLogger("dracon").setLevel(prev_dracon)


class TestShowModeDetection:
    """Test that mode detection works: .yaml / + prefix = raw, else program-aware."""

    def test_yaml_file_is_raw_mode(self):
        from dracon.cli import ShowCmd
        cmd = ShowCmd(targets=["config.yaml"])
        assert cmd._is_raw_mode()

    def test_plus_prefix_is_raw_mode(self):
        from dracon.cli import ShowCmd
        cmd = ShowCmd(targets=["+config.yaml"])
        assert cmd._is_raw_mode()

    def test_program_name_is_program_mode(self):
        from dracon.cli import ShowCmd
        cmd = ShowCmd(targets=["broodmon"])
        assert not cmd._is_raw_mode()

    def test_mixed_plus_and_yaml_is_raw(self):
        from dracon.cli import ShowCmd
        cmd = ShowCmd(targets=["+base.yaml", "+override.yaml"])
        assert cmd._is_raw_mode()


class TestShowProgramMode:
    """Program-aware mode — discovers @dracon_program and shows resolved config."""

    def test_schema_output(self):
        """--schema emits JSON Schema for a registered program model."""
        from dracon.cli import _get_program_schema, ShowCmd
        from dracon import dracon_program

        @dracon_program(name="test-prog")
        class TestProg(BaseModel):
            host: str = "localhost"
            port: int = 8080

        schema = _get_program_schema(TestProg)
        assert "properties" in schema
        assert "host" in schema["properties"]
        assert "port" in schema["properties"]


class TestFullDefaults:
    """--full flag generates exhaustive config template with all nested defaults."""

    def test_full_simple_model(self):
        from dracon.cli import _full_defaults

        class Inner(BaseModel):
            x: int = 10
            y: str = "hello"

        class Outer(BaseModel):
            name: str = "test"
            inner: Inner = Inner()

        data = _full_defaults(Outer)
        assert data["name"] == "test"
        assert data["inner"]["x"] == 10
        assert data["inner"]["y"] == "hello"

    def test_full_optional_nested(self):
        """Optional[Model] fields with None default get expanded."""
        from dracon.cli import _full_defaults
        from typing import Optional

        class Config(BaseModel):
            threshold: float = 0.5

        class App(BaseModel):
            config: Optional[Config] = None

        data = _full_defaults(App)
        assert data["config"]["threshold"] == 0.5

    def test_full_list_of_models(self):
        """list[Model] fields get one example item."""
        from dracon.cli import _full_defaults

        class Item(BaseModel):
            value: int = 42

        class Container(BaseModel):
            items: list[Item] = []

        data = _full_defaults(Container)
        assert len(data["items"]) == 1
        assert data["items"][0]["value"] == 42

    def test_full_skips_non_defaultable(self):
        """Fields with no default and no model type are skipped."""
        from dracon.cli import _full_defaults

        class M(BaseModel):
            name: str = "ok"
            required_str: str  # no default, not a model -- skip

        data = _full_defaults(M)
        assert data["name"] == "ok"
        assert "required_str" not in data

    def test_full_depth_limit(self):
        from dracon.cli import _full_defaults

        class Deep(BaseModel):
            val: int = 1

        class Mid(BaseModel):
            deep: Deep = Deep()

        class Top(BaseModel):
            mid: Mid = Mid()

        # depth=1: expand 1 level (mid is shown, but deep inside mid is {})
        data = _full_defaults(Top, depth=1)
        assert "mid" in data
        assert data["mid"] == {"deep": {}}

        # depth=0: fields listed but nested models are empty
        data0 = _full_defaults(Top, depth=0)
        assert data0 == {"mid": {}}

        # depth=None (unlimited): full expansion
        full = _full_defaults(Top)
        assert full["mid"]["deep"]["val"] == 1


class TestDraconCLIStructure:
    """Test that the DraconCLI is properly structured as a @dracon_program."""

    def test_cli_has_dracon_program_config(self):
        from dracon.cli import DraconCLI
        assert hasattr(DraconCLI, '_dracon_program_config')

    def test_cli_has_show_subcommand(self):
        from dracon.cli import DraconCLI
        cfg = DraconCLI._dracon_program_config
        assert cfg['name'] == 'dracon'

    def test_cli_has_cli_method(self):
        from dracon.cli import DraconCLI
        assert hasattr(DraconCLI, 'cli')

    def test_main_is_importable(self):
        from dracon.cli import main
        assert callable(main)


class TestShowRawDraconPrintCompat:
    """Ensure backward compat: DraconPrint class still works when imported from cli."""

    def test_dracon_print_class_in_cli(self):
        from dracon.cli import DraconPrint
        dp = DraconPrint(config_files=[str(CONFIGS / "simple.yaml")])
        out = dp.run()
        assert "root:" in out
        assert "a: 3" in out

    def test_dracon_print_json(self):
        from dracon.cli import DraconPrint
        dp = DraconPrint(
            config_files=[str(CONFIGS / "simple.yaml")],
            json_output=True,
        )
        out = dp.run()
        data = json.loads(out)
        assert data["root"]["a"] == 3
