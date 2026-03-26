#!/usr/bin/env python3
"""Benchmark Dracon composition across realistic config scenarios.

Run: python -m dracon.tests.bench_composition
"""
import os
import sys
import time
import tempfile
import statistics
from pathlib import Path

from dracon import DraconLoader
from dracon.include import compose_from_include_str

TESTS_DIR = Path(__file__).parent
CONFIGS_DIR = TESTS_DIR / "configs"

N_RUNS = 30
WARMUP = 5


def bench(name, fn, n_runs=N_RUNS, warmup=WARMUP):
    """Run fn repeatedly, return (median_ms, stdev_ms)."""
    for _ in range(warmup):
        fn()
    times = []
    for _ in range(n_runs):
        t0 = time.perf_counter()
        fn()
        times.append((time.perf_counter() - t0) * 1000)
    med = statistics.median(times)
    std = statistics.stdev(times) if len(times) > 1 else 0
    return med, std


# ── scenario definitions ─────────────────────────────────────────────────────

def scenario_simple_single():
    """single flat file, no features"""
    loader = DraconLoader(trace=False)
    compose_from_include_str(loader, f"pkg:dracon:tests/configs/simple")


def scenario_simple_single_traced():
    loader = DraconLoader(trace=True)
    compose_from_include_str(loader, f"pkg:dracon:tests/configs/simple")


def scenario_includes_and_merges():
    """main.yaml: anchors, pkg includes, merge keys, 4-level nesting"""
    os.environ['TESTVAR1'] = 'testval'
    loader = DraconLoader(trace=False)
    compose_from_include_str(loader, "pkg:dracon:tests/configs/main")


def scenario_includes_and_merges_traced():
    os.environ['TESTVAR1'] = 'testval'
    loader = DraconLoader(trace=True)
    compose_from_include_str(loader, "pkg:dracon:tests/configs/main")


def scenario_interpolation():
    """interpolation.yaml: ${2+2}, nested ${${...}}, tag interp, merge+interp"""
    loader = DraconLoader(trace=False)
    compose_from_include_str(loader, "pkg:dracon:tests/configs/interpolation")


def scenario_interpolation_traced():
    loader = DraconLoader(trace=True)
    compose_from_include_str(loader, "pkg:dracon:tests/configs/interpolation")


def scenario_edge_cases():
    """edge_cases.yaml: !define, !each with dotted keys, nested dict interp"""
    loader = DraconLoader(trace=False)
    compose_from_include_str(loader, "pkg:dracon:tests/configs/edge_cases")


def scenario_edge_cases_traced():
    loader = DraconLoader(trace=True)
    compose_from_include_str(loader, "pkg:dracon:tests/configs/edge_cases")


def scenario_override_merges():
    """override.yaml: <<{<+}[<+]:, <<@path:, <<[+>]{>+}@path:, scalar merge"""
    loader = DraconLoader(trace=False)
    compose_from_include_str(loader, "pkg:dracon:tests/configs/override")


def scenario_override_merges_traced():
    loader = DraconLoader(trace=True)
    compose_from_include_str(loader, "pkg:dracon:tests/configs/override")


def scenario_context_includes():
    """incl_contexts.yaml: $FILE_STEM, !define, multi-level includes with context"""
    loader = DraconLoader(trace=False)
    compose_from_include_str(loader, "pkg:dracon:tests/configs/incl_contexts")


def scenario_context_includes_traced():
    loader = DraconLoader(trace=True)
    compose_from_include_str(loader, "pkg:dracon:tests/configs/incl_contexts")


def scenario_instructions():
    """sub/instructions.yaml: !set_default, !each + !deferred + !define + !include"""
    loader = DraconLoader(trace=False)
    compose_from_include_str(loader, "pkg:dracon:tests/configs/sub/instructions")


def scenario_instructions_traced():
    loader = DraconLoader(trace=True)
    compose_from_include_str(loader, "pkg:dracon:tests/configs/sub/instructions")


def scenario_file_layering():
    """3-layer file merge (base + override + append) via DraconLoader.compose()"""
    d = tempfile.mkdtemp()
    base = Path(d) / "base.yaml"
    override = Path(d) / "override.yaml"
    append = Path(d) / "append.yaml"
    base.write_text("a: 1\nb:\n  x: 10\n  y: 20\nl: [1, 2]\ncommon: base\n")
    override.write_text("a: 2\nb:\n  x: 99\nl: [3, 4]\ncommon: override\n")
    append.write_text("b:\n  z: 30\nl: [5, 6]\nnew_key: appended\n")

    def run():
        loader = DraconLoader(trace=False)
        loader.compose([str(base), str(override), str(append)])

    def run_traced():
        loader = DraconLoader(trace=True)
        loader.compose([str(base), str(override), str(append)])

    return run, run_traced


def scenario_large_flat():
    """500-key flat config (stress test)"""
    d = tempfile.mkdtemp()
    f = Path(d) / "large.yaml"
    f.write_text('\n'.join(f"key_{i}: value_{i}" for i in range(500)) + '\n')

    def run():
        DraconLoader(trace=False).compose(str(f))

    def run_traced():
        DraconLoader(trace=True).compose(str(f))

    return run, run_traced


def scenario_large_layered():
    """200 keys x 3 layers (stress test)"""
    d = tempfile.mkdtemp()
    files = []
    for layer in range(3):
        lines = []
        for i in range(40):
            lines.append(f"group_{i}:")
            for j in range(5):
                lines.append(f"  key_{j}: value_{layer}_{i}_{j}")
        p = Path(d) / f"layer_{layer}.yaml"
        p.write_text('\n'.join(lines) + '\n')
        files.append(str(p))

    def run():
        DraconLoader(trace=False).compose(files)

    def run_traced():
        DraconLoader(trace=True).compose(files)

    return run, run_traced


# ── runner ───────────────────────────────────────────────────────────────────

SCENARIOS = [
    ("simple (flat, no features)", scenario_simple_single, scenario_simple_single_traced),
    ("main.yaml (anchors, merges, pkg includes)", scenario_includes_and_merges, scenario_includes_and_merges_traced),
    ("interpolation.yaml (${}, nested, tag interp)", scenario_interpolation, scenario_interpolation_traced),
    ("edge_cases.yaml (!define, !each, dotted keys)", scenario_edge_cases, scenario_edge_cases_traced),
    ("override.yaml (<<@path, complex merges)", scenario_override_merges, scenario_override_merges_traced),
    ("incl_contexts.yaml (context, multi-include)", scenario_context_includes, scenario_context_includes_traced),
    ("sub/instructions.yaml (!each+!deferred+!define)", scenario_instructions, scenario_instructions_traced),
    ("file layering (3 files, DraconLoader.compose)", None, None),  # placeholder
    ("large flat (500 keys)", None, None),
    ("large layered (200 keys x 3 layers)", None, None),
]


def main():
    print(f"Dracon composition benchmark ({N_RUNS} runs, {WARMUP} warmup)")
    print("=" * 90)
    print(f"{'Scenario':<48} {'off':>8} {'on':>8} {'overhead':>9} {'±stdev':>7}")
    print("-" * 90)

    # replace placeholder scenarios with generated ones
    layer_off, layer_on = scenario_file_layering()
    SCENARIOS[7] = ("file layering (3 files, compose())", layer_off, layer_on)
    large_off, large_on = scenario_large_flat()
    SCENARIOS[8] = ("large flat (500 keys)", large_off, large_on)
    layered_off, layered_on = scenario_large_layered()
    SCENARIOS[9] = ("large layered (200 keys x 3 layers)", layered_off, layered_on)

    for name, fn_off, fn_on in SCENARIOS:
        med_off, std_off = bench(name, fn_off)
        med_on, std_on = bench(name + " [traced]", fn_on)
        overhead = ((med_on - med_off) / med_off) * 100 if med_off > 0 else 0
        print(f"  {name:<46} {med_off:>7.2f}ms {med_on:>7.2f}ms {overhead:>+8.1f}% {std_on:>6.2f}ms")

    print("-" * 90)
    print("overhead = (traced - untraced) / untraced × 100")


if __name__ == "__main__":
    main()
