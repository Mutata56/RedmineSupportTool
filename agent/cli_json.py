# -*- coding: utf-8 -*-


import json


def _first_json_object(s):


    depth, start = 0, None
    in_str = esc = False
    for i, c in enumerate(s or ""):
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "{":
            if depth == 0:
                start = i
            depth += 1
        elif c == "}" and depth > 0:
            depth -= 1
            if depth == 0 and start is not None:
                try:
                    d = json.loads(s[start:i + 1])
                except json.JSONDecodeError:
                    start = None
                    continue
                return d if isinstance(d, dict) else None
    return None


def parse_envelope(out):


    out = (out or "").strip()
    if not out:
        return None
    try:
        d = json.loads(out)
        if isinstance(d, dict):
            return d
    except json.JSONDecodeError:
        pass
    return _first_json_object(out)


def extract_inner_json(text):


    return _first_json_object(text)
