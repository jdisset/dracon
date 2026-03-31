"""Tests for soft context priority: !set_default values yield to !define across merge boundaries."""

import tempfile
import os
from dracon import loads


# ── inline template pattern (anchor + merge) ────────────────────────────────


def test_set_default_yields_to_define_across_merge():
    """!set_default in a template yields to caller's !define after merge."""
    config = loads("""
__dracon__: &tpl
  !set_default x: 10
  val: ${x}

a:
  !define x: 100
  <<: *tpl
""")
    assert config['a']['val'] == 100


def test_set_default_kept_when_no_define():
    """!set_default value is kept when no !define overrides it."""
    config = loads("""
__dracon__: &tpl
  !set_default x: 10
  val: ${x}

a:
  <<: *tpl
""")
    assert config['a']['val'] == 10


def test_template_reuse_different_params():
    """Multiple instantiations of the same template with different params."""
    config = loads("""
__dracon__: &svc
  !set_default replicas: 1
  image: myapp/${name}:latest
  port: ${port}
  deploy:
    replicas: ${replicas}

services:
  auth:
    !define name: auth
    !define port: 8001
    !define replicas: 3
    <<: *svc

  api:
    !define name: api
    !define port: 8002
    <<: *svc

  worker:
    !define name: worker
    !define port: 8003
    !define replicas: 5
    <<: *svc
""")
    assert config['services']['auth']['image'] == 'myapp/auth:latest'
    assert config['services']['auth']['port'] == 8001
    assert config['services']['auth']['deploy']['replicas'] == 3

    assert config['services']['api']['image'] == 'myapp/api:latest'
    assert config['services']['api']['port'] == 8002
    assert config['services']['api']['deploy']['replicas'] == 1  # default

    assert config['services']['worker']['image'] == 'myapp/worker:latest'
    assert config['services']['worker']['port'] == 8003
    assert config['services']['worker']['deploy']['replicas'] == 5


def test_template_with_require_and_set_default():
    """Template using !require for mandatory params and !set_default for optional."""
    config = loads("""
__dracon__: &svc
  !require name: "service name required"
  !require port: "port required"
  !set_default replicas: 1
  !set_default protocol: http
  image: myapp/${name}:latest
  port: ${port}
  replicas: ${replicas}
  protocol: ${protocol}

a:
  !define name: auth
  !define port: 8001
  !define protocol: https
  <<: *svc
""")
    assert config['a']['image'] == 'myapp/auth:latest'
    assert config['a']['replicas'] == 1  # default kept
    assert config['a']['protocol'] == 'https'  # overridden


# ── file-based template pattern (still works) ───────────────────────────────


def test_file_template_set_default_yields_to_define():
    """File-based template: caller's !define overrides template's !set_default."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        f.write("!set_default x: 10\nval: ${x}\n")
        f.flush()
        try:
            config = loads(f"""
a:
  !define x: 100
  <<: !include file:{f.name}
""")
            assert config['a']['val'] == 100
        finally:
            os.unlink(f.name)


# ── define always overrides set_default (regardless of scope order) ──────────


def test_define_overrides_set_default_same_scope():
    """!define overrides !set_default in the same scope."""
    config = loads("""
!set_default x: 10
!define x: 100
val: ${x}
""")
    assert config['val'] == 100


def test_set_default_does_not_override_define():
    """!set_default does NOT override a previous !define."""
    config = loads("""
!define x: 100
!set_default x: 10
val: ${x}
""")
    assert config['val'] == 100


def test_nested_define_overrides_outer_set_default():
    """Inner !define overrides outer !set_default."""
    config = loads("""
!set_default x: 10

outer:
  !define x: 100
  val: ${x}
""")
    assert config['outer']['val'] == 100
