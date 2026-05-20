# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Jean Disset
import os


def read_from_env(path: str, **_):
    return str(os.getenv(path)), {}
