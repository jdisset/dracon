# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Jean Disset
"""Deprecated: use `dracon show` instead. This module redirects to dracon.cli."""
from dracon.cli import DraconPrint, main  # noqa: F401

if __name__ == "__main__":
    main()
