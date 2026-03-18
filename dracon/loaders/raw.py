"""Raw text loaders — return file content as a plain string scalar.

These loaders bypass YAML parsing, so files containing YAML-breaking characters
(colons, hashes, pipes, dashes) load correctly as strings.

Usage in YAML:
    focus: !include raw:/absolute/path/to/prompt.md
    focus: !include raw:$DIR/../prompts/my-focus.md
    focus: !include rawpkg:alfred:recipes/prompts/dev-focus.md
"""

from pathlib import Path

from dracon.composer import CompositionResult
from dracon.nodes import DraconScalarNode


def read_raw(path: str, **_) -> tuple[CompositionResult, dict]:
    """Read a file as plain text — content becomes a string scalar, not parsed YAML."""
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise FileNotFoundError(f"raw: file not found: {path}")
    text = p.read_text()
    node = DraconScalarNode(tag="tag:yaml.org,2002:str", value=text)
    context = {"DIR": str(p.parent), "FILE": str(p)}
    return CompositionResult(root=node), context


def read_rawpkg(path: str, **_) -> tuple[CompositionResult, dict]:
    """Read a package resource as plain text — no YAML parsing.

    Path format: ``package_name:path/to/file.md``
    """
    if ":" not in path:
        raise ValueError(f"rawpkg: expected 'pkg_name:path/to/file', got {path!r}")
    pkg, resource_path = path.split(":", 1)
    from importlib.resources import as_file, files

    with as_file(files(pkg) / resource_path) as p:
        text = Path(p).read_text()
    node = DraconScalarNode(tag="tag:yaml.org,2002:str", value=text)
    return CompositionResult(root=node), {}
