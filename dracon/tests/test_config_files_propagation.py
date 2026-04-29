# Copyright (c) 2025 Jean Disset
# MIT License - see LICENSE file for details.

"""!define'd symbols in auto-loaded ConfigFile must be visible to subsequent +layers.

Bug: see ``bugs/cli-config-files-symbols-not-visible-to-layers.md``. A
``ConfigFile`` declared on ``@dracon_program`` is supposed to be the
project-wide vocabulary layer that user recipes compose against. But
its top-level ``!define`` symbols don't propagate into the loader scope
for subsequent ``+recipe.yaml`` files, so a recipe using ``!Greeter`` (a
template defined in the auto-loaded vocabulary) errors out with
"name 'Greeter' is not defined".

The user's mental model: a ``ConfigFile`` is a leading ``<<(<):`` layer.
Defines should propagate through, just like they do between two files
linked by an explicit ``<<(<): !include other.yaml`` chain.
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Annotated

import pytest
from pydantic import BaseModel

from dracon import ConfigFile, dracon_program


def _write(tmp: Path, name: str, body: str) -> Path:
    p = tmp / name
    p.write_text(textwrap.dedent(body).lstrip())
    return p


# ── auto-loaded ConfigFile delivers a vocabulary ────────────────────────


class TestConfigFileVocabularyPropagation:
    """A vocabulary file declared via ``ConfigFile`` propagates its
    ``!define`` symbols into the scope of subsequent ``+recipe`` layers."""

    def test_define_template_is_visible_to_recipe(self, tmp_path: Path):
        vocab = _write(tmp_path, "vocab.yaml", """
            !define Greeter: !fn
              !require name: "who to greet"
              !fn :
                msg: "hello ${name}"
        """)
        recipe = _write(tmp_path, "recipe.yaml", """
            result: !Greeter
              name: world
        """)

        @dracon_program(name="prog", config_files=[ConfigFile(str(vocab))])
        class CLI(BaseModel):
            result: dict = {}

        cfg = CLI.cli([f"+file:{recipe}"])
        assert cfg.result == {"msg": "hello world"}

    def test_define_constant_is_visible_to_recipe(self, tmp_path: Path):
        """A plain ``!define`` value (not a template) must also propagate."""
        vocab = _write(tmp_path, "vocab.yaml", """
            !define DEFAULT_PORT: 8080
            !define DEFAULT_HOST: "api.internal"
        """)
        recipe = _write(tmp_path, "recipe.yaml", """
            host: ${DEFAULT_HOST}
            port: ${DEFAULT_PORT}
        """)

        @dracon_program(name="p2", config_files=[ConfigFile(str(vocab))])
        class CLI(BaseModel):
            host: str = ""
            port: int = 0

        cfg = CLI.cli([f"+file:{recipe}"])
        assert cfg.host == "api.internal"
        assert cfg.port == 8080

    def test_chained_includes_match_explicit_pattern(self, tmp_path: Path):
        """The auto-loaded path must match the user's mental model: a
        ConfigFile should behave like a leading ``<<(<):`` include in the
        recipe. The two patterns must yield the same result."""
        vocab = _write(tmp_path, "vocab.yaml", """
            !define Wrap: !fn
              !require x: "the x"
              wrapped: ${x * 2}
        """)
        recipe_explicit = _write(tmp_path, "recipe_explicit.yaml", f"""
            <<(<): !include file:{vocab}
            v: !Wrap
              x: 21
        """)
        recipe_auto = _write(tmp_path, "recipe_auto.yaml", """
            v: !Wrap
              x: 21
        """)

        # explicit pattern: no ConfigFile, recipe inlines the include
        @dracon_program(name="explicit")
        class ExplicitCLI(BaseModel):
            v: dict = {}

        cfg_explicit = ExplicitCLI.cli([f"+file:{recipe_explicit}"])

        # auto pattern: ConfigFile delivers vocab, recipe assumes it
        @dracon_program(name="auto", config_files=[ConfigFile(str(vocab))])
        class AutoCLI(BaseModel):
            v: dict = {}

        cfg_auto = AutoCLI.cli([f"+file:{recipe_auto}"])

        assert cfg_explicit.v == cfg_auto.v == {"wrapped": 42}


# ── recipe-defined values still win over vocab defaults ───────────────────


class TestVocabularyDoesNotOverrideRecipe:
    """Vocabulary defaults must be overridable by the recipe (the recipe
    is layered ON TOP of the vocab, not under it)."""

    def test_recipe_define_visible_to_recipe_interpolations(self, tmp_path: Path):
        """Vocab provides a default; recipe overrides with !define and uses
        ${tier} in its own scope. The recipe's ${tier} sees the recipe's
        hard-set value, not the vocab's set_default."""
        vocab = _write(tmp_path, "vocab.yaml", """
            !set_default tier: "bronze"
        """)
        recipe = _write(tmp_path, "recipe.yaml", """
            !define tier: "gold"
            tier_value: ${tier}
        """)

        @dracon_program(name="p3", config_files=[ConfigFile(str(vocab))])
        class CLI(BaseModel):
            tier_value: str = ""

        cfg = CLI.cli([f"+file:{recipe}"])
        assert cfg.tier_value == "gold"


# ── multiple +layer files share the vocabulary ───────────────────────────


class TestMultipleRecipesShareVocabulary:
    def test_two_recipes_both_see_vocab_symbols(self, tmp_path: Path):
        vocab = _write(tmp_path, "vocab.yaml", """
            !define Mul: !fn
              !require n: "factor"
              !fn :
                out: ${n * 10}
        """)
        r1 = _write(tmp_path, "r1.yaml", """
            a: !Mul { n: 2 }
        """)
        r2 = _write(tmp_path, "r2.yaml", """
            b: !Mul { n: 3 }
        """)

        @dracon_program(name="p4", config_files=[ConfigFile(str(vocab))])
        class CLI(BaseModel):
            a: dict = {}
            b: dict = {}

        cfg = CLI.cli([f"+file:{r1}", f"+file:{r2}"])
        assert cfg.a == {"out": 20}
        assert cfg.b == {"out": 30}


# ── ConfigFile path accepts scheme URIs (file:, pkg:, ...) ──────────────


class TestConfigFileSchemeUris:
    """ConfigFile path is a dracon include URI, not a bare filesystem path.

    The same scheme grammar that ``!include`` and ``+file:foo.yaml`` accept must
    work as a ConfigFile target (``file:`` is the obvious one; ``pkg:`` is
    equally valid for projects shipping a package-resource vocabulary). The
    discovery step used to silently drop anything with a ``:`` because it
    delegated to ``Path.exists()`` -- which fails on scheme prefixes.
    """

    def test_file_scheme_path_is_accepted(self, tmp_path: Path):
        vocab = _write(tmp_path, "vocab.yaml", """
            !define Greeter: !fn
              !require name: "who to greet"
              !fn :
                msg: "hello ${name}"
        """)
        recipe = _write(tmp_path, "recipe.yaml", """
            result: !Greeter
              name: world
        """)

        @dracon_program(name="prog", config_files=[ConfigFile(f"file:{vocab}")])
        class CLI(BaseModel):
            result: dict = {}

        cfg = CLI.cli([f"+file:{recipe}"])
        assert cfg.result == {"msg": "hello world"}

    def test_pkg_scheme_path_is_accepted(self, tmp_path: Path, monkeypatch):
        """A ``pkg:`` URI should compose just like an explicit ``!include
        pkg:...`` would. We synthesize a tiny throwaway package on sys.path."""
        import sys, importlib

        pkg_root = tmp_path / "myvocab_pkg"
        pkg_root.mkdir()
        (pkg_root / "__init__.py").write_text("")
        (pkg_root / "base.yaml").write_text(textwrap.dedent("""
            !define Echo: !fn
              !require x: "value"
              !fn :
                echoed: ${x}
        """).lstrip())
        recipe = _write(tmp_path, "recipe.yaml", """
            r: !Echo { x: "from-pkg-vocab" }
        """)

        monkeypatch.syspath_prepend(str(tmp_path))
        # ensure a stale import doesn't shadow the freshly-written tree
        sys.modules.pop("myvocab_pkg", None)
        importlib.invalidate_caches()

        @dracon_program(
            name="pkg-prog",
            config_files=[ConfigFile("pkg:myvocab_pkg:base.yaml")],
        )
        class CLI(BaseModel):
            r: dict = {}

        cfg = CLI.cli([f"+file:{recipe}"])
        assert cfg.r == {"echoed": "from-pkg-vocab"}

    def test_required_scheme_uri_missing_raises(self, tmp_path: Path):
        """``required=True`` on a scheme URI that won't resolve must surface
        clearly, not silently drop the file."""
        from dracon import ConfigFile, dracon_program

        @dracon_program(
            name="required-missing",
            config_files=[ConfigFile("pkg:no_such_pkg_xyz:absent.yaml", required=True)],
        )
        class CLI(BaseModel):
            x: int = 0

        with pytest.raises((FileNotFoundError, ModuleNotFoundError, ImportError)):
            CLI.cli([])

    def test_optional_scheme_uri_missing_silently_skips(self, tmp_path: Path):
        """``required=False`` (default) on a scheme URI that won't resolve
        must behave like a missing optional bare path: silent skip."""

        @dracon_program(
            name="optional-missing",
            config_files=[ConfigFile("pkg:no_such_pkg_xyz:absent.yaml")],
        )
        class CLI(BaseModel):
            x: int = 7

        cfg = CLI.cli([])
        assert cfg.x == 7
