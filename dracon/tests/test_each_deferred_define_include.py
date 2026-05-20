# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Jean Disset
import pytest
from dracon.loader import DraconLoader
from dracon.composer import is_post_process_context_independent


@pytest.fixture
def fragment_define(tmp_path):
    p = tmp_path / "fragment.yaml"
    p.write_text("!define _val: ${probe(it)}\nout: ${_val}\n")
    return p


@pytest.fixture
def fragment_set_default(tmp_path):
    p = tmp_path / "frag_sd.yaml"
    p.write_text("!set_default _val: ${probe(it)}\nout: ${_val}\n")
    return p


def _make_probe():
    calls = []
    def probe(x):
        calls.append(x)
        return f"v={x}"
    return probe, calls


def test_define_eager_inside_deferred_under_each_include(fragment_define):
    probe, calls = _make_probe()
    yaml_str = f"""
!define items: ${{[1, 2, 3]}}

things:
  !each(it) ${{items}}:
    - !deferred
      <<: !include file:{fragment_define}
"""
    loader = DraconLoader(context={"probe": probe})
    result = loader.loads(yaml_str)
    constructed = [t.construct() for t in result["things"]]
    assert calls == [1, 2, 3]
    assert [c["out"] for c in constructed] == ["v=1", "v=2", "v=3"]


def test_define_eager_inline_inside_deferred_under_each():
    probe, calls = _make_probe()
    yaml_str = """
!define items: ${[1, 2, 3]}

things:
  !each(it) ${items}:
    - !deferred
      !define _val: ${probe(it)}
      out: ${_val}
"""
    loader = DraconLoader(context={"probe": probe})
    result = loader.loads(yaml_str)
    constructed = [t.construct() for t in result["things"]]
    assert calls == [1, 2, 3]
    assert [c["out"] for c in constructed] == ["v=1", "v=2", "v=3"]


def test_set_default_eager_inside_deferred_under_each_include(fragment_set_default):
    probe, calls = _make_probe()
    yaml_str = f"""
!define items: ${{[1, 2, 3]}}

things:
  !each(it) ${{items}}:
    - !deferred
      <<: !include file:{fragment_set_default}
"""
    loader = DraconLoader(context={"probe": probe})
    result = loader.loads(yaml_str)
    constructed = [t.construct() for t in result["things"]]
    assert calls == [1, 2, 3]
    assert [c["out"] for c in constructed] == ["v=1", "v=2", "v=3"]


def test_define_in_included_file_called_from_two_scopes(tmp_path):
    frag = tmp_path / "frag.yaml"
    frag.write_text("!define _v: ${probe(it)}\nout: ${_v}\n")
    probe, calls = _make_probe()
    yaml_str = f"""
!define it_one: 10
!define it_two: 20

a: !deferred
  !define it: ${{it_one}}
  <<: !include file:{frag}

b: !deferred
  !define it: ${{it_two}}
  <<: !include file:{frag}
"""
    loader = DraconLoader(context={"probe": probe})
    result = loader.loads(yaml_str)
    a = result["a"].construct()
    b = result["b"].construct()
    assert calls == [10, 20]
    assert a["out"] == "v=10"
    assert b["out"] == "v=20"


def test_define_eager_in_parallel_deferred_siblings(tmp_path):
    frag = tmp_path / "frag.yaml"
    frag.write_text("!define _v: ${tag(scope_id)}\nname: ${_v}\n")
    seen = []
    def tag(s):
        seen.append(s)
        return f"tag-{s}"
    yaml_str = f"""
left: !deferred
  !define scope_id: A
  <<: !include file:{frag}

right: !deferred
  !define scope_id: B
  <<: !include file:{frag}
"""
    loader = DraconLoader(context={"tag": tag})
    result = loader.loads(yaml_str)
    l = result["left"].construct()
    r = result["right"].construct()
    assert sorted(seen) == ["A", "B"]
    assert l["name"] == "tag-A"
    assert r["name"] == "tag-B"


def test_define_with_static_value_in_include_works(tmp_path):
    frag = tmp_path / "static_frag.yaml"
    frag.write_text("!define _v: 42\nout: ${_v}\n")
    yaml_str = f"""
things:
  !each(i) ${{[1, 2, 3]}}:
    - !deferred
      <<: !include file:{frag}
"""
    loader = DraconLoader()
    result = loader.loads(yaml_str)
    outs = [t.construct()["out"] for t in result["things"]]
    assert outs == [42, 42, 42]


@pytest.mark.parametrize("src", [
    "!define x: ${y}\nout: ${x}\n",
    "!define? x: ${y}\nout: ${x}\n",
    "!set_default x: ${y}\nout: ${x}\n",
    "!define:int x: 42\nout: ${x}\n",
])
def test_pp_ctx_independence_rejects_define_family(src):
    loader = DraconLoader()
    loader.yaml.compose(src)
    root = loader.yaml.composer.get_result().root
    assert not is_post_process_context_independent(root)


def test_pp_ctx_independence_accepts_pure_static():
    loader = DraconLoader()
    loader.yaml.compose("a: 1\nb: ${a}\nnested: { c: 2 }\n")
    root = loader.yaml.composer.get_result().root
    assert is_post_process_context_independent(root)
