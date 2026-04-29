# Copyright (c) 2025 Jean Disset
# MIT License - see LICENSE file for details.

"""Coverage for `!fn:pkg:` (skill claims it works; this pins it).

`_resolve_via_scheme` already routes `!fn:scheme:` through `loader.custom_loaders`,
so `pkg` is wired by construction. The tests below exercise the path end-to-end:
binding a YAML template inside an installed package via `!fn:pkg:`, calling it
with the kwarg, and verifying the @selector lifts a single template out of a
multi-template file.
"""

from __future__ import annotations


def _loads(yaml_str: str):
    from dracon.loader import DraconLoader
    loader = DraconLoader(enable_interpolation=True)
    cfg = loader.loads(yaml_str)
    cfg.resolve_all_lazy()
    return cfg


def test_fn_pkg_template_with_selector():
    cfg = _loads("""
f: !fn:pkg:dracon.tests.configs:fn_templates.yaml@greet
  greeting: hi
""")
    out = cfg["f"](name="world")
    assert out["message"] == "hi, world"


def test_fn_pkg_template_with_selector_alt_template():
    cfg = _loads("""
f: !fn:pkg:dracon.tests.configs:fn_templates.yaml@double
""")
    out = cfg["f"](x=21)
    assert out["val"] == 42


def test_fn_pkg_template_default_arg():
    cfg = _loads("""
f: !fn:pkg:dracon.tests.configs:fn_templates.yaml@greet
""")
    out = cfg["f"](name="world")
    assert out["message"] == "hello, world"
