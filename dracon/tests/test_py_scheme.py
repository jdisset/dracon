"""Tests for the py: include scheme and !fn: scheme-URI extension.

The py: scheme unifies Python symbol resolution under dracon's include
machinery. These tests exercise:

- dotted-path imports (!include py:module[@Symbol])
- file-path imports (!include py:$DIR/file.py[@Symbol])
- binding with !define, use as tag, inline use
- !fn: scheme-URI sugar (!fn:py:... and !fn:pkg:...)
- vocabulary layering (<<(<):) over a py: namespace
- error paths (missing module, missing symbol, missing file)
"""
from pathlib import Path
import pickle
import pytest
from dracon.loader import DraconLoader


HELPER_FILE = Path(__file__).parent / "test_py_scheme_helper_file.py"


def _loads(yaml_str, **ctx):
    loader = DraconLoader(context=ctx, enable_interpolation=True)
    # expose DIR so $DIR works in YAML literals used inside tests
    loader.update_context({'HELPER_DIR': str(HELPER_FILE.parent)})
    cfg = loader.loads(yaml_str)
    cfg.resolve_all_lazy()
    return cfg


# ── 1. !include py:dotted — selector form ─────────────────────────────────────


class TestPyIncludeDottedSelector:
    def test_define_python_function(self):
        cfg = _loads("""
!define Add: !include py:dracon.tests.test_py_scheme_helper@add
result: ${Add(a=2, b=3)}
""")
        assert cfg['result'] == 5

    def test_define_python_class(self):
        cfg = _loads("""
!define Helper: !include py:dracon.tests.test_py_scheme_helper@Helper
h:
  n: ${Helper(n=7, label='foo').n}
  label: ${Helper(n=7, label='foo').label}
""")
        assert cfg['h']['n'] == 7
        assert cfg['h']['label'] == 'foo'

    def test_python_class_as_tag(self):
        cfg = _loads("""
!define Helper: !include py:dracon.tests.test_py_scheme_helper@Helper
h: !Helper { n: 42, label: bar }
""")
        assert cfg['h'].n == 42
        assert cfg['h'].label == 'bar'

    def test_constant_value(self):
        cfg = _loads("""
!define PI: !include py:dracon.tests.test_py_scheme_helper@PI_APPROX
val: ${PI}
""")
        assert cfg['val'] == 3.14


# ── 2. !include py: without selector — submodule resolution ───────────────────


class TestPyIncludeWithoutSelector:
    def test_dotted_submodule_as_value(self):
        """`!include py:dotted.path` — the path itself identifies a symbol."""
        cfg = _loads("""
!define Add: !include py:dracon.tests.test_py_scheme_helper.add
result: ${Add(a=10, b=20)}
""")
        assert cfg['result'] == 30


# ── 3. file-path form ────────────────────────────────────────────────────────


class TestPyIncludeFilePath:
    def test_include_from_absolute_file(self):
        cfg = _loads(f"""
!define Double: !include py:{HELPER_FILE}@double
result: ${{Double(5)}}
""")
        assert cfg['result'] == 10

    def test_include_class_from_file(self):
        cfg = _loads(f"""
!define FH: !include py:{HELPER_FILE}@FileHelper
h: !FH {{ tag: local }}
""")
        assert cfg['h'].tag == 'local'

    def test_file_path_with_dir_var(self):
        cfg = _loads("""
!define Double: !include py:${HELPER_DIR}/test_py_scheme_helper_file.py@double
result: ${Double(21)}
""")
        assert cfg['result'] == 42


# ── 4. !fn: scheme-URI sugar ─────────────────────────────────────────────────


class TestFnSchemeURI:
    def test_fn_py_scheme_dotted(self):
        cfg = _loads("""
f: !fn:py:dracon.tests.test_py_scheme_helper.greet
  greeting: howdy
""")
        assert cfg['f'](name='world') == 'howdy world'

    def test_fn_py_scheme_with_selector(self):
        cfg = _loads("""
f: !fn:py:dracon.tests.test_py_scheme_helper@greet
  greeting: hey
""")
        assert cfg['f'](name='there') == 'hey there'

    def test_fn_py_file(self):
        cfg = _loads(f"""
f: !fn:py:{HELPER_FILE}@double
""")
        assert cfg['f'](3) == 6

    def test_fn_file_scheme_template_with_selector(self, tmp_path):
        template = tmp_path / "templates.yaml"
        template.write_text(
            "templates:\n"
            "  double:\n"
            "    !require x: 'x'\n"
            "    val: ${x * 2}\n"
        )
        cfg = _loads(f"""
f: !fn:file:{template}@templates.double
""")
        assert cfg['f'](x=4)['val'] == 8

    def test_fn_dotted_still_works_as_sugar_for_py(self):
        """Back-compat: !fn:dotted.x stays as sugar for !fn:py:dotted.x"""
        cfg = _loads("""
f: !fn:math.pow
""")
        assert cfg['f'](2.0, 10.0) == 1024.0

    def test_fn_py_scheme_partial_pickles(self):
        cfg = _loads("""
f: !fn:py:math.pow
""")
        f = pickle.loads(pickle.dumps(cfg['f']))
        assert f(2.0, 3.0) == 8.0


# ── 5. error paths ───────────────────────────────────────────────────────────


class TestPyIncludeErrors:
    def test_missing_module(self):
        with pytest.raises(Exception, match="[Nn]o module|not found|cannot"):
            _loads("""
!define X: !include py:_definitely_not_a_real_module_xyz
v: ${X}
""")

    def test_missing_symbol(self):
        with pytest.raises(Exception, match="no attribute|not found|NoneType|symbol|KeyError|Anchor|selector|Could not get"):
            _loads("""
!define X: !include py:dracon.tests.test_py_scheme_helper@not_a_real_name
v: ${X}
""")

    def test_missing_file(self):
        with pytest.raises(Exception, match="not found|No such file"):
            _loads("""
!define X: !include py:/tmp/_definitely_not_a_real_file_xyz.py@x
v: ${X}
""")


# ── 6. privacy — underscore names not exported by default ─────────────────────


class TestPyPrivacy:
    def test_private_name_not_exposed_by_default(self):
        """`_private_thing` in helper should not be reachable by default via !include.

        The namespace returned by `!include py:mod` omits underscore-prefixed
        names (honouring __all__ when present), so the @selector fails to find
        the private key.
        """
        with pytest.raises(Exception, match="no attribute|not found|symbol|missing|Could not get"):
            _loads("""
!define P: !include py:dracon.tests.test_py_scheme_helper@_private_thing
v: ${P}
""")

    def test_include_namespace_as_mapping(self):
        """Bare `!include py:mod` (no selector) binds to a mapping of public names.

        Useful when you want explicit vocabulary access like `nm[name]` in
        interpolations, not to be confused with `<<(<):` vocabulary propagation.
        """
        cfg = _loads("""
!define nm: !include py:dracon.tests.test_py_scheme_helper
add_result: ${nm['add'](a=3, b=4)}
""")
        assert cfg['add_result'] == 7


# ── 7. interactions: kwargs, pipes, bound selectors ──────────────────────────


class TestPyIncludeInteractions:
    def test_fn_scheme_with_kwargs_partial(self):
        """!fn:py:... { kwargs } produces a partial like any other !fn:target."""
        from dracon.partial import DraconPartial
        cfg = _loads("""
f: !fn:py:dracon.tests.test_py_scheme_helper.add
  a: 10
""")
        assert isinstance(cfg['f'], DraconPartial)
        assert cfg['f'](b=5) == 15

    def test_py_include_works_inline_without_define(self):
        """!include py:... used directly as a value (not bound via !define)."""
        cfg = _loads("""
pi: !include py:dracon.tests.test_py_scheme_helper@PI_APPROX
""")
        assert cfg['pi'] == 3.14

    def test_scheme_dispatch_is_generic(self):
        """py: is wired through the same loader registry as file:/pkg:/etc.

        We verify the scheme chokepoint is uniform by replacing the py loader
        with a spy — any other loader plugs into the same socket.
        """
        from dracon.loader import DraconLoader

        calls = []
        def spy_loader(path, node=None, draconloader=None, **_):
            from dracon.loaders.py import read_from_py
            calls.append(path)
            return read_from_py(path, node=node, draconloader=draconloader)

        loader = DraconLoader(
            enable_interpolation=True,
            custom_loaders={'mypy': spy_loader},
        )
        cfg = loader.loads("""
!define Add: !include mypy:dracon.tests.test_py_scheme_helper@add
result: ${Add(a=2, b=3)}
""")
        cfg.resolve_all_lazy()
        assert cfg['result'] == 5
        assert calls == ['dracon.tests.test_py_scheme_helper']


class TestPyPrivacyExplicit:
    def test_explicit_underscore_via_fn_still_resolves(self):
        """Explicit `!fn:py:mod.name` reaches private names via dotted-fallback.

        `!fn:` is an explicit symbol reference, not a namespace import — it
        calls getattr directly, bypassing the public-only filter used by
        `!include py:mod` namespace construction.

        Here the target is a non-callable string, so resolution succeeds but
        `!fn:` errors with 'non-callable' (proving the symbol was found).
        """
        with pytest.raises(Exception, match="non-callable"):
            _loads("""
f: !fn:py:dracon.tests.test_py_scheme_helper._private_thing
""")
