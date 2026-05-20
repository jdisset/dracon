# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Jean Disset
"""Locks in four declarative composition patterns documented in SKILL.md:

- shared singletons via lazy `!define`
- slot-based abstract configs (typed dependency injection)
- reactive defaults (`!set_default` with `${...}` over other vars)
- vocabulary-as-schema via `__scope__`
"""
import pytest
from pydantic import BaseModel

from dracon import load, loads, resolve_all_lazy
from dracon.diagnostics import CompositionError


def build(src, **ctx):
    cfg = loads(src, context=ctx)
    resolve_all_lazy(cfg)
    return cfg


class Service(BaseModel):
    name: str


class Dataset(BaseModel):
    name: str
    channels: int


class Model(BaseModel):
    kind: str
    layers: int


class Opt(BaseModel):
    kind: str
    lr: float


ABSTRACT = """
!require:Dataset dataset: "..."
!require:Model   model:   "..."
!require:Opt     opt:     "..."

training:
  data: ${dataset}
  net: ${model}
  optimizer: ${opt}
eval:
  data: ${dataset}
  net: ${model}
"""

SLOT_CTX = {"Dataset": Dataset, "Model": Model, "Opt": Opt}


# ── shared singletons via lazy !define ────────────────────────────────────────

def test_singleton_across_nested_references():
    cfg = build("""
        !define shared: !Service { name: main }
        a:
          use: ${shared}
        b:
          use: ${shared}
        c:
          deep:
            nested:
              use: ${shared}
    """, Service=Service)
    a, b, c = cfg["a"]["use"], cfg["b"]["use"], cfg["c"]["deep"]["nested"]["use"]
    assert a is b is c


def test_singleton_inside_list_and_each():
    cfg = build("""
        !define hub: !Service { name: hub }
        consumers:
          - use: ${hub}
          - use: ${hub}
        generated:
          !each(k) ${['x', 'y', 'z']}:
            - id: ${k}
              hub: ${hub}
    """, Service=Service)
    a, b = (item["use"] for item in cfg["consumers"])
    gens = list(cfg["generated"])
    assert a is b is gens[0]["hub"] is gens[1]["hub"] is gens[2]["hub"]


def test_distinct_defines_do_not_alias():
    cfg = build("""
        !define a: !Service { name: a }
        !define b: !Service { name: b }
        first:  ${a}
        second: ${b}
        third:  ${a}
    """, Service=Service)
    assert cfg["first"] is not cfg["second"]
    assert cfg["first"] is cfg["third"]


# ── slot-based abstract configs ───────────────────────────────────────────────

def test_abstract_alone_fails_with_unfilled_slots():
    with pytest.raises(CompositionError):
        loads(ABSTRACT, context=SLOT_CTX)


@pytest.fixture
def slots_layout(tmp_path):
    (tmp_path / "abstract.yaml").write_text(ABSTRACT)

    def make_impl(name, ds, model_kind, opt_kind="adam", lr=0.001):
        path = tmp_path / name
        path.write_text(f"""
            !define dataset: !Dataset {{ name: {ds}, channels: 3 }}
            !define model:   !Model   {{ kind: {model_kind}, layers: 12 }}
            !define opt:     !Opt     {{ kind: {opt_kind}, lr: {lr} }}
            <<: !include file:$DIR/abstract.yaml
        """)
        return path

    return make_impl


def test_impl_fills_every_slot(slots_layout):
    cfg = load(str(slots_layout("impl.yaml", "fashion-mnist", "resnet")),
               context=SLOT_CTX)
    resolve_all_lazy(cfg)
    t = cfg["training"]
    assert isinstance(t["data"], Dataset) and t["data"].name == "fashion-mnist"
    assert isinstance(t["net"], Model) and t["net"].kind == "resnet"
    assert isinstance(t["optimizer"], Opt)


def test_slot_referenced_twice_is_same_instance(slots_layout):
    cfg = load(str(slots_layout("impl.yaml", "imagenet", "vit")), context=SLOT_CTX)
    resolve_all_lazy(cfg)
    assert cfg["training"]["data"] is cfg["eval"]["data"]
    assert cfg["training"]["net"] is cfg["eval"]["net"]


def test_swappable_impls_share_abstract(slots_layout):
    a_path = slots_layout("a.yaml", "fashion-mnist", "resnet")
    b_path = slots_layout("b.yaml", "imagenet", "vit", "sgd", 0.1)
    a = load(str(a_path), context=SLOT_CTX); resolve_all_lazy(a)
    b = load(str(b_path), context=SLOT_CTX); resolve_all_lazy(b)
    assert (a["training"]["data"].name, a["training"]["net"].kind) == ("fashion-mnist", "resnet")
    assert (b["training"]["data"].name, b["training"]["net"].kind) == ("imagenet", "vit")
    assert b["training"]["optimizer"].lr == 0.1


# ── reactive defaults ─────────────────────────────────────────────────────────

REACTIVE = """
!set_default hidden_dim: 256
!set_default num_layers: ${max(1, hidden_dim // 64)}
!set_default batch_size: ${max(8, 64 * 256 // hidden_dim)}
!set_default warmup:     ${batch_size * num_layers * 10}

config:
  hidden_dim: ${hidden_dim}
  num_layers: ${num_layers}
  batch_size: ${batch_size}
  warmup:     ${warmup}
"""


@pytest.mark.parametrize("ctx,expected", [
    ({},                                       {"hidden_dim": 256,  "num_layers": 4,  "batch_size": 64, "warmup": 2560}),
    ({"hidden_dim": 1024},                     {"hidden_dim": 1024, "num_layers": 16, "batch_size": 16, "warmup": 2560}),
    ({"hidden_dim": 1024, "batch_size": 32},   {"hidden_dim": 1024, "num_layers": 16, "batch_size": 32, "warmup": 5120}),
    ({"hidden_dim": 512, "warmup": 0},         {"hidden_dim": 512,  "num_layers": 8,  "batch_size": 32, "warmup": 0}),
])
def test_reactive_defaults_propagate_and_pin(ctx, expected):
    assert dict(build(REACTIVE, **ctx)["config"]) == expected


def test_hard_define_beats_reactive_default():
    cfg = build("""
        !set_default x: 10
        !define x: 99
        !set_default y: ${x * 2}
        out:
          x: ${x}
          y: ${y}
    """)
    assert dict(cfg["out"]) == {"x": 99, "y": 198}


# ── vocabulary as schema via __scope__ ────────────────────────────────────────

VOCAB = """
!define Http: !fn
  !require:str  port:  "TCP port to bind"
  !set_default:bool tls: true
  !returns:HttpSpec _:
  kind: http
  port: ${port}
  tls: ${tls}

!define Grpc: !fn
  !require:str  port:  "GRPC port to bind"
  !set_default:int max_msg_mb: 4
  !returns:GrpcSpec _:
  kind: grpc
  port: ${port}
  max_msg_mb: ${max_msg_mb}

_schema:
  templates: ${__scope__.names(kind='template')}
  catalog:   ${__scope__.to_json()}

service:
  in:  !Http { port: '8080' }
  out: !Grpc { port: '9090', max_msg_mb: 16 }
"""


@pytest.fixture(scope="module")
def vocab():
    return build(VOCAB)


def test_scope_lists_user_templates(vocab):
    assert set(vocab["_schema"]["templates"]) == {"Http", "Grpc"}


def test_catalog_records_typed_params(vocab):
    http = dict(vocab["_schema"]["catalog"])["Http"]
    params = {p["name"]: p for p in http["params"]}
    assert params["port"]["required"] is True
    assert params["port"]["annotation"] == "str"
    assert params["port"]["docs"] == "TCP port to bind"
    assert params["tls"]["required"] is False
    assert params["tls"]["annotation"] == "bool"


def test_catalog_records_return_and_source(vocab):
    catalog = dict(vocab["_schema"]["catalog"])
    assert catalog["Http"]["returns"] == "HttpSpec"
    assert catalog["Grpc"]["returns"] == "GrpcSpec"
    src = catalog["Http"]["source"]
    assert "file" in src and isinstance(src.get("line"), int) and src["line"] > 0


def test_vocab_still_usable_alongside_introspection(vocab):
    assert dict(vocab["service"]["in"])  == {"kind": "http", "port": "8080", "tls": True}
    assert dict(vocab["service"]["out"]) == {"kind": "grpc", "port": "9090", "max_msg_mb": 16}
