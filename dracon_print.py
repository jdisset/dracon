"""Deprecated: use `dracon show` instead. This module redirects to dracon.cli."""
# backward compat shim — all logic lives in dracon.cli now
from dracon.cli import DraconPrint, parse_argv, main, HELP_TEXT  # noqa: F401

if __name__ == "__main__":
    main()
