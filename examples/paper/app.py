#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Jean Disset
#
# The minimal example from the JOSS paper (paper/paper.md). Run it with:
#
#   python app.py +app.yaml --env prod --workers 8
#
# `host` resolves at load time once `env` is known; `credentials` stays a
# deferred subtree that is constructed later with a runtime `vault` object.
from pydantic import BaseModel
from dracon import dracon_program, DeferredNode


class Database(BaseModel):
    host: str
    credentials: DeferredNode[dict]


@dracon_program()
class App(BaseModel):
    workers: int = 1
    database: Database


if __name__ == "__main__":
    App.cli()
