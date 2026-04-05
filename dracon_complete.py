"""Ultra-fast completion handler for dracon programs.

This module deliberately avoids importing dracon or any heavy dependencies.
It handles +file and --flag completions purely via filesystem operations and
regex source scanning, achieving sub-100ms response times.
"""
import glob as globmod
import os
import re
import sys


def _find_module_source(dotted: str):
    """Locate a module's source file without importing it."""
    parts = dotted.split('.')
    for base in sys.path:
        if not base or not os.path.isdir(base):
            continue
        rel = os.path.join(*parts)
        for candidate in [f"{rel}.py", os.path.join(rel, "__init__.py")]:
            full = os.path.join(base, candidate)
            if os.path.isfile(full):
                return full
    return None


def _extract_flags(program_name: str):
    """Extract --flag names from a program's source without importing it."""
    from importlib.metadata import entry_points
    try:
        eps = entry_points(group='console_scripts', name=program_name)
        for ep in eps:
            mod_path = ep.value.split(':')[0]
            src_path = _find_module_source(mod_path)
            if not src_path:
                continue
            with open(src_path) as f:
                source = f.read()

            dp_match = re.search(r'@dracon_program[\s\S]*?\nclass\s+\w+[^:]*:', source)
            if not dp_match:
                continue
            class_start = dp_match.end()

            flags = set()
            skip = {'model_config', 'action', 'command'}
            for line in source[class_start:].split('\n'):
                if line and not line[0].isspace():
                    break
                m = re.match(r'^\s{4}(\w+)\s*:', line)
                if m:
                    name = m.group(1)
                    if name.startswith('_') or name in skip:
                        continue
                    flags.add('--' + name.replace('_', '-'))
            flags.update(['--trace', '--trace-all'])
            return sorted(flags)
    except Exception:
        pass
    return None


def _extract_subcommands(program_name: str):
    """Extract subcommand names from source by finding @subcommand decorators."""
    from importlib.metadata import entry_points
    try:
        eps = entry_points(group='console_scripts', name=program_name)
        for ep in eps:
            mod_path = ep.value.split(':')[0]
            src_path = _find_module_source(mod_path)
            if not src_path:
                continue
            with open(src_path) as f:
                source = f.read()
            # find @subcommand("name") decorators
            return re.findall(r'@subcommand\(["\'](\w+)["\']\)', source) or None
    except Exception:
        pass
    return None


def main():
    """Handle 'dracon _complete <program>' without importing dracon."""
    argv = sys.argv[1:]
    if len(argv) < 2 or argv[0] != '_complete':
        # not a completion request -- fall through to full CLI
        from dracon.cli import main as cli_main
        cli_main()
        return

    program_name = argv[1]
    line = os.environ.get("COMP_LINE", "")
    point = int(os.environ.get("COMP_POINT", str(len(line))))
    tokens = line[:point].split()
    prefix = tokens[-1] if len(tokens) > 1 else ""
    if line[:point].endswith(" "):
        prefix = ""

    # +file completion
    if prefix.startswith("+") and not prefix.startswith("++"):
        partial = prefix[1:]
        matches = globmod.glob(partial + "*.yaml") + globmod.glob(partial + "*.yml")
        dirs = globmod.glob(partial + "*/")
        for c in ["+" + m for m in matches] + ["+" + d for d in dirs]:
            print(c)
        return

    # --flag completion via source scan
    if prefix.startswith("-"):
        flags = _extract_flags(program_name)
        if flags is not None:
            for f in flags:
                if f.startswith(prefix):
                    print(f)
            return

    # subcommand completion via source scan -- no import needed
    subcmds = _extract_subcommands(program_name)
    if subcmds:
        for s in subcmds:
            if s.startswith(prefix):
                print(s)
    # if no subcommands found, just return nothing (shell falls back to default)


if __name__ == "__main__":
    main()
