#!/usr/bin/env python3
# -*- coding: utf-8 -*-


import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def _load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


cfg = _load(os.path.join(HERE, "config", "config.json"))
sec = _load(os.path.join(HERE, "config", "secrets.local.json"))
gf = cfg.get("grafana") if isinstance(cfg.get("grafana"), dict) else {}

os.environ.setdefault("WA_GF_BASE", gf.get("base") or "http://service.example.invalid")
os.environ.setdefault("WA_GF_USER", sec.get("grafana_user") or gf.get("user") or "")
os.environ["WA_GF_PASSWORD"] = sec.get("grafana_password") or ""
os.environ.setdefault("WA_GF_DS_ID", str(gf.get("influx_ds_id", 3)))
os.environ.setdefault("WA_GF_DB", gf.get("influx_db") or "telegraf")

server = os.path.join(HERE, "agent", "influx_mcp.py")
os.execv(sys.executable, [sys.executable, server])
