# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Jean Disset
"""Tests for the `!import` directive.

`!import` bulk-binds names from a Python module (or YAML vocab) into the
current document scope. Functionally equivalent to N `!define`s collapsed
to one line.
"""
import os
import tempfile
import pytest

from dracon.loader import DraconLoader


HELPER = 'dracon.tests.test_py_scheme_helper'


def _loads(yaml_str, **ctx):
    loader = DraconLoader(context=ctx, enable_interpolation=True)
    return loader.loads(yaml_str)


class TestWildcardImport:
    def test_imports_all_public_names(self):
        cfg = _loads(f"""
!import {HELPER}:
sum: ${{add(a=2, b=3)}}
greeting: ${{greet(name='alice')}}
pi: ${{PI_APPROX}}
""")
        assert cfg['sum'] == 5
        assert cfg['greeting'] == 'hello alice'
        assert cfg['pi'] == 3.14

    def test_imported_class_resolves_as_tag(self):
        cfg = _loads(f"""
!import {HELPER}:
h: !Helper {{ n: 7, label: foo }}
""")
        assert cfg['h'].n == 7
        assert cfg['h'].label == 'foo'

    def test_respects_dunder_all(self):
        """Helper module sets __all__; the private `_private_thing` must not leak."""
        loader = DraconLoader(enable_interpolation=True)
        cfg = loader.loads(f"""
!import {HELPER}:
names: ${{[n for n in __scope__.names() if not n.startswith('_')]}}
""")
        assert '_private_thing' not in cfg['names']
        assert 'Helper' in cfg['names']


class TestSelectiveImport:
    def test_named_imports(self):
        cfg = _loads(f"""
!import {HELPER}: [Helper, add]
h: !Helper {{ n: 1, label: x }}
s: ${{add(a=4, b=5)}}
""")
        assert cfg['h'].n == 1
        assert cfg['s'] == 9

    def test_missing_name_raises(self):
        with pytest.raises(Exception) as exc:
            _loads(f"""
!import {HELPER}: [Helper, DoesNotExist]
result: 1
""")
        msg = str(exc.value)
        assert "'DoesNotExist'" in msg
        assert 'Available' in msg


class TestAliasImport:
    def test_rename(self):
        cfg = _loads(f"""
!import {HELPER}:
  Helper: H
  add: plus
h: !H {{ n: 2, label: y }}
s: ${{plus(a=10, b=20)}}
""")
        assert cfg['h'].n == 2
        assert cfg['s'] == 30


class TestSchemes:
    def test_explicit_py_scheme(self):
        cfg = _loads(f"""
!import py:{HELPER}: [add]
s: ${{add(a=1, b=2)}}
""")
        assert cfg['s'] == 3

    def test_single_symbol_path(self):
        """py:dotted.path that resolves to a non-module symbol binds it under its last segment."""
        cfg = _loads(f"""
!import py:{HELPER}.add:
s: ${{add(a=1, b=2)}}
""")
        assert cfg['s'] == 3

    def test_unknown_module_raises(self):
        with pytest.raises(Exception) as exc:
            _loads("""
!import nonexistent.module.xyz:
v: 1
""")
        assert 'nonexistent' in str(exc.value)


class TestCollisionRule:
    def test_existing_define_wins(self):
        cfg = _loads(f"""
!define add: 999
!import {HELPER}:
val: ${{add}}
""")
        assert cfg['val'] == 999

    def test_later_define_overrides_import(self):
        """!import is purely additive; subsequent !define is a real binding and wins."""
        cfg = _loads(f"""
!import {HELPER}:
!define add: 42
val: ${{add}}
""")
        assert cfg['val'] == 42


class TestPropagationThroughInclude:
    def test_import_in_vocab_file_flows_through_propagating_merge(self):
        with tempfile.TemporaryDirectory() as d:
            vocab = os.path.join(d, 'vocab.yaml')
            with open(vocab, 'w') as f:
                f.write(f'!import {HELPER}: [Helper, add]\n')
            main_yaml = f"""
<<(<): !include file:{vocab}
h: !Helper {{ n: 5, label: vocab }}
s: ${{add(a=1, b=1)}}
"""
            cfg = _loads(main_yaml)
            assert cfg['h'].n == 5
            assert cfg['s'] == 2


class TestYamlVocabImport:
    def test_import_yaml_pulls_defined_names(self):
        with tempfile.TemporaryDirectory() as d:
            vocab = os.path.join(d, 'vocab.yaml')
            with open(vocab, 'w') as f:
                f.write(f'!define Greeting: hello\n!import {HELPER}: [Helper]\n')
            cfg = _loads(f"""
!import file:{vocab}:
g: ${{Greeting}}
h: !Helper {{ n: 3, label: yaml }}
""")
            assert cfg['g'] == 'hello'
            assert cfg['h'].n == 3


class TestErrorReporting:
    def test_invalid_body_shape(self):
        with pytest.raises(Exception) as exc:
            _loads(f"""
!import {HELPER}: 42
v: 1
""")
        assert 'null' in str(exc.value) or 'name list' in str(exc.value)

    def test_empty_path(self):
        with pytest.raises(Exception):
            _loads("""
!import "":
v: 1
""")
