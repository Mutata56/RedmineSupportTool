#!/usr/bin/env python3
# -*- coding: utf-8 -*-


import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def _load(name):
    try:
        with open(os.path.join(HERE, "config", name), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _contours(cfg):


    ids = set()
    for v in (cfg.get("routing") or {}).values():
        if isinstance(v, dict) and v.get("project_id"):
            ids.add(int(v["project_id"]))
    return ",".join(str(i) for i in sorted(ids))


from agent.redmine_client import resolve_account

acc = resolve_account(_load("secrets.local.json"))
os.environ["RM_URL"] = acc.get("url") or ""
os.environ["RM_API_KEY"] = acc.get("api_key") or ""
os.environ["RM_DRY"] = "1"
os.environ["RM_READ_ONLY"] = "1"

os.environ.pop("RM_SOURCE_ISSUE", None)
os.environ.pop("RM_DRAFT_FILE", None)
os.environ.setdefault("RM_SEARCH_LIMIT", "20")
os.environ["RM_CONTOUR_PROJECTS"] = _contours(_load("config.json"))


os.execv(sys.executable, [sys.executable, os.path.join(HERE, "agent", "redmine_mcp.py")])
