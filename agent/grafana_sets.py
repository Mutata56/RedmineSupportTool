# -*- coding: utf-8 -*-


import re


SITES = [
    ("CLB_SITE01",      "client_b", "example-dashboard-01", "Площадка B1"),
    ("CLB_SITE02",       "client_b", "example-dashboard-02", "Площадка B2"),
    ("CLB_SITE03",       "client_b", "example-dashboard-03", "Площадка B3"),
    ("CLB_SITE04",        "client_b", "example-dashboard-04", "Площадка B4"),
    ("CLB_SITE05",      "client_b", "example-dashboard-05", "Площадка B5"),
    ("CLD_SITE01",    "cld",   "example-dashboard-06", "Площадка D1"),
    ("CLD_SITE02", "cld",   "example-dashboard-08", "Площадка D3"),
    ("CLD_SITE03", "cld",   "example-dashboard-08", "Площадка D3"),
    ("CLD_SITE04",   "cld",   "example-dashboard-09", "Площадка D4"),
    ("CLD_SITE05",     "cld",   "example-dashboard-10", "Площадка D5"),
    ("CLD_SITE06",    "cld",   "example-dashboard-11", "Площадка D6"),
    ("CLD_SITE07",      "cld",   "example-dashboard-12", "Площадка D7"),
    ("CLD_SITE08",   "cld",   "", "Площадка D8"),
    ("CLD_SITE09",    "cld",   "example-dashboard-14", "Площадка D9"),
    ("CLC_SITE01",      "clc",   "example-dashboard-15", "Площадка C1"),
    ("CLC_SITE02",        "clc",   "example-dashboard-16", "Площадка C2"),
    ("CLC_SITE03",        "clc",   "example-dashboard-17", "Площадка C3"),
    ("CLC_SITE04",       "clc",   "example-dashboard-18", "Площадка C4"),
    ("CLC_SITE05",       "clc",   "example-dashboard-19", "Площадка C5"),
    ("CLC_SITE06",       "clc",   "example-dashboard-20", "Площадка C6"),
    ("CLE",          "cle",  "example-dashboard-21", ""),
]
_SITES_SORTED = sorted(SITES, key=lambda x: -len(x[0]))


def site_from_subject(subj):


    s = (subj or "").upper()
    for code, net, uid, wh in _SITES_SORTED:
        if re.search(r"(?<![A-Z0-9])%s(?![A-Z0-9])" % re.escape(code), s):
            return {"code": code, "network": net, "uid": uid, "warehouse": wh}
    return None


def role_cat(label):

    s = (label or "").lower()
    if "jmx" in s:
        return "JMX"
    if "mark" in s:
        return "MARK"
    if "integ" in s or "intb" in s or "wmsint" in s:
        return "INTEG"
    if "app" in s:
        return "APP"
    if "db" in s or "бд" in s or "bd" in s:
        return "DB"
    return ""


def load_sets(path):
    import yaml
    with open(path, encoding="utf-8") as f:
        d = yaml.safe_load(f) or {}
    return [s for s in (d.get("sets") or []) if s.get("panels")]


def match_set(text, sets):
    t = (text or "").lower()
    for s in sets:
        if any(str(m).lower() in t for m in (s.get("match") or [])):
            return s
    return None


def resolve_panels(setdef, subj):

    s = subj or ""
    out = []
    for p in setdef.get("panels", []):
        if not isinstance(p, dict):
            out.append(p)
            continue
        q = None
        if p.get("uptime_from_subject"):
            m = re.search(r"(\S+)\s+Uptime", s, re.I)
            if m:
                q = {"match": "%s Uptime" % m.group(1), "exact": True}
        elif p.get("heap_from_subject"):
            m = re.search(r"HeapMemory ?\S+", s, re.I)
            if m:
                q = {"match": m.group(0)}
        elif p.get("table_from_subject"):
            m = re.search(r"([A-Za-z0-9_]+)\s+alert", s, re.I)
            if m:
                q = {"match": m.group(1), "word": True}
            else:
                sl = s.lower()
                for kw in sorted(setdef.get("match", []), key=lambda k: -len(str(k))):
                    if str(kw).lower() in sl:
                        q = {"match": str(kw), "word": True}
                        break
        elif p.get("freespace_from_subject"):
            m = re.search(r"(\S+)_FREESPACE", s, re.I)
            if m:
                q = {"match": "Св. место", "role": role_cat(m.group(1))}
        elif p.get("jbosspool_from_subject"):


            m = re.search(r"(APP[_ ]?\d|APP)_JBOSS", s, re.I)
            if m:
                prefix = m.group(1).upper().replace(" ", "")
                if re.match(r"APP\d$", prefix):
                    prefix = "APP_" + prefix[3:]
                q = {"match": "%s JBOSS Connection Pool" % prefix}
            else:
                q = {"match": "Jboss Connection Pool", "exact": True}
        else:
            out.append(p)
            continue
        if q is None:
            continue
        base = {k: v for k, v in p.items() if not k.endswith("_from_subject")}
        base.update(q)
        out.append(base)
    return out


def filter_set(items, specs):

    norm = []
    for s in specs:
        if isinstance(s, dict):
            norm.append((str(s.get("match", "")).lower(), s.get("why", ""), bool(s.get("always")),
                         (s.get("role") or "").lower(), bool(s.get("exact")), bool(s.get("word"))))
        else:
            norm.append((str(s).lower(), "", False, "", False, False))
    picked, seen = [], set()
    for pat, why, always, role, exact, word in norm:
        if not pat:
            continue
        for it in items:
            t = it["title"].lower()
            if exact:
                hit = (t == pat)
            elif word:
                hit = re.search(r"(?<![a-z0-9_])" + re.escape(pat) + r"(?![a-z0-9_])", t) is not None
            else:
                hit = pat in t
            if hit and role and it.get("rolecat", "") != role.upper():
                hit = False
            if hit and it["id"] not in seen:
                seen.add(it["id"])
                j = dict(it)
                j["why"] = why
                j["always"] = always
                picked.append(j)
    return picked


_TABLE_NAMES = ["LOTXLOCXID", "PICKDETAIL", "TASKDETAIL", "ITRN", "SKUXLOC", "LOT", "WAVEINPROCESS"]


def table_from_subject(subj):


    s = (subj or "").upper()
    for t in sorted(_TABLE_NAMES, key=len, reverse=True):
        if re.search(r"(?<![A-Z0-9_])" + t + r"(?![A-Z0-9_])", s):
            return t
    return None


def analysis_for(subj, analysis_base):


    site = site_from_subject(subj)
    table = table_from_subject(subj)
    if not site or not table:
        return None
    rec = (analysis_base.get(site["code"], {}).get("tables", {}) or {}).get(table)
    if not rec:
        return None
    return site["code"], table, rec


def format_analysis_note(code, table, rec):

    lines = ["Годовой профиль %s / %s (Opus-анализ InfluxDB за год):" % (table, code)]
    for fl, label in [("pattern", "Характер"), ("cut", "Обрезка"), ("baseline", "Baseline"),
                      ("peak", "Пик"), ("alert_meaning", "Смысл алерта"), ("action", "Реакция")]:
        if rec.get(fl):
            lines.append("- %s: %s" % (label, rec[fl]))
    return "\n".join(lines)


def _flat_panels(dash):
    out = []
    for p in (dash.get("dashboard", {}) or {}).get("panels", []) or []:
        if p.get("type") == "row":
            out += p.get("panels", []) or []
        else:
            out.append(p)
    return out


def tablecounts_target(dash, table):


    tu = (table or "").upper()
    for p in _flat_panels(dash):
        for tg in p.get("targets", []) or []:
            if tg.get("measurement") != "tableCounts":
                continue
            field = None
            for grp in tg.get("select", []) or []:
                for it in grp:
                    if it.get("type") == "field" and it.get("params"):
                        field = it["params"][0]
            if not field or field.upper() != tu:
                continue
            tags = {}
            for t in tg.get("tags", []) or []:
                if t.get("key") and t.get("value") and t.get("operator", "=") == "=":
                    tags[t["key"]] = t["value"]
            return {"measurement": tg.get("measurement"), "field": field,
                    "tags": tags, "policy": tg.get("policy")}
    return None


def recent_points_query(target, window="24h", every="10m", limit=150):


    tags = target.get("tags") or {}
    conds = ['"%s" = \'%s\'' % (k, str(v).replace("'", "")) for k, v in sorted(tags.items())]
    conds.append("time > now()-%s" % window)
    meas = '"%s"' % target["measurement"]
    pol = target.get("policy")
    if pol and pol not in ("default", None):
        meas = '"%s".%s' % (pol, meas)
    return ('SELECT mean("%s") FROM %s WHERE %s GROUP BY time(%s) fill(none) '
            'ORDER BY time DESC LIMIT %d'
            % (target["field"], meas, " AND ".join(conds), every, int(limit)))


_SERVICE_PANEL_TITLES = {
    "locks": ["блокировки"],
    "freespace": ["св. место"],
    "log_size": ["log_size", "log size"],
    "archive_backup": ["архивация", "бэкап"],
    "tempdb": ["tempdb"],


    "jboss": ["jboss", "connection pool"],
    "apache": ["apache", "busyworkers", "busy workers"],
    "uptime": ["uptime", "аптайм"],
}


def _target_of(panel):


    tg = (panel.get("targets") or [{}])[0]
    field = agg = None
    for grp in tg.get("select", []) or []:
        for it in grp:
            if it.get("type") == "field" and it.get("params"):
                field = it["params"][0]
            elif it.get("type") in ("max", "min", "mean", "last", "sum"):
                agg = it["type"]
    if not tg.get("measurement") or not field:
        return None
    tags = {t["key"]: t["value"] for t in (tg.get("tags") or [])
            if t.get("key") and t.get("value") and t.get("operator", "=") == "="}
    return {"measurement": tg["measurement"], "field": field, "agg": agg or "mean",
            "tags": tags, "policy": tg.get("policy")}


def service_series_targets(dash, alert_type, subject="", limit_panels=3):


    titles = list(_SERVICE_PANEL_TITLES.get(alert_type, []))
    if alert_type == "archive_backup":
        s = (subject or "").lower()
        if ("бэкап" in s or "backup" in s) and "архив" not in s:
            titles = ["бэкап"]
        elif "архив" in s and "бэкап" not in s and "backup" not in s:
            titles = ["архивация"]
    out, seen = [], set()
    for p in _flat_panels(dash):
        title = (p.get("title") or "").strip()
        tl = title.lower()
        if not any(sub in tl for sub in titles):
            continue
        tgt = _target_of(p)
        if not tgt:
            continue
        sig = (tgt["measurement"], tgt["field"], tuple(sorted(tgt["tags"].items())))
        if sig in seen:
            continue
        seen.add(sig)
        out.append((title, tgt))
        if len(out) >= limit_panels:
            break
    return out


def influx_series_query(target, window="30h", every="10m", limit=200):


    tags = target.get("tags") or {}
    conds = ['"%s" = \'%s\'' % (k, str(v).replace("'", "")) for k, v in sorted(tags.items())]
    conds.append("time > now()-%s" % window)
    meas = '"%s"' % target["measurement"]
    pol = target.get("policy")
    if pol and pol not in ("default", None):
        meas = '"%s".%s' % (pol, meas)
    return ('SELECT %s("%s") FROM %s WHERE %s GROUP BY time(%s) fill(none) '
            'ORDER BY time DESC LIMIT %d'
            % (target.get("agg", "mean"), target["field"], meas,
               " AND ".join(conds), every, int(limit)))


def format_series(label, values, msk_offset=3):


    from datetime import datetime, timedelta
    pts = [(iso, v) for iso, v in (values or []) if v is not None]
    if not pts:
        return None

    def msk(iso):
        return datetime.fromisoformat(iso.replace("Z", "+00:00")) + timedelta(hours=msk_offset)

    def num(v):
        return int(round(v)) if abs(v) >= 100 else round(v, 2)

    def ago(n):
        return pts[n][1] if len(pts) > n else None

    def trend(d):
        return "растёт" if d > 0 else ("снижается" if d < 0 else "без изменений")

    now_v = pts[0][1]
    nums = [p[1] for p in pts]
    newest, oldest = msk(pts[0][0]), msk(pts[-1][0])
    lines = ["Метрика «%s» из InfluxDB (та же, что на графике Grafana; шаг 10 мин, MSK):" % label,
             "- сейчас (%s): %s" % (newest.strftime("%d.%m %H:%M"), num(now_v)),
             "- за ~%dч: минимум %s, максимум %s"
             % (round((newest - oldest).total_seconds() / 3600), num(min(nums)), num(max(nums)))]
    if ago(6) is not None:
        d = now_v - ago(6)
        lines.append("- за последний час: %+g (%s)" % (num(d), trend(d)))
    if ago(36) is not None:
        d = now_v - ago(36)
        lines.append("- за ~6 часов: %+g (%s)" % (num(d), trend(d)))
    series = " ".join("%s=%s" % (msk(iso).strftime("%H:%M"), num(v)) for iso, v in reversed(pts))
    lines.append("Ряд (старые->новые, %s -> %s): %s"
                 % (oldest.strftime("%d.%m %H:%M"), newest.strftime("%H:%M"), series))
    return "\n".join(lines)


def format_recent_points(values, msk_offset=3):


    from datetime import datetime, timedelta
    pts = [(iso, v) for iso, v in (values or []) if v is not None]
    if not pts:
        return None

    def msk(iso):
        return datetime.fromisoformat(iso.replace("Z", "+00:00")) + timedelta(hours=msk_offset)

    def sep(n):
        return format(int(round(n)), ",").replace(",", " ")

    def ago(n):
        return round(pts[n][1]) if len(pts) > n else None

    def trend(d):
        return "растёт" if d > 0 else ("снижается" if d < 0 else "без изменений")

    now_v = round(pts[0][1])
    nums = [p[1] for p in pts]
    vmin, vmax = round(min(nums)), round(max(nums))
    d1 = (now_v - ago(6)) if ago(6) is not None else None
    d6 = (now_v - ago(36)) if ago(36) is not None else None
    newest, oldest = msk(pts[0][0]), msk(pts[-1][0])
    lines = [
        "Свежие значения размера таблицы из InfluxDB (та же метрика, что на графике Grafana; "
        "шаг 10 мин, время MSK):",
        "- сейчас (%s): %s строк" % (newest.strftime("%d.%m %H:%M"), sep(now_v)),
        "- за последние ~%dч: минимум %s, максимум %s"
        % (round((newest - oldest).total_seconds() / 3600), sep(vmin), sep(vmax)),
    ]
    if d1 is not None:
        lines.append("- динамика за последний час: %+d (%s)" % (d1, trend(d1)))
    if d6 is not None:
        lines.append("- динамика за ~6 часов: %+d (%s)" % (d6, trend(d6)))
    series = " ".join("%s=%d" % (msk(iso).strftime("%H:%M"), round(v))
                      for iso, v in reversed(pts))
    lines.append("Ряд точек (старые->новые, %s -> %s): %s"
                 % (oldest.strftime("%d.%m %H:%M"), newest.strftime("%H:%M"), series))
    return "\n".join(lines)


def panels_catalog(dash):


    panels = dash["dashboard"].get("panels", [])
    flat = []
    for p in panels:
        if p.get("type") == "row":
            for sub in p.get("panels", []) or []:
                flat.append(sub)
        else:
            flat.append(p)
    labels = []
    for p in flat:
        gp = p.get("gridPos") or {}
        if p.get("type") == "text" and gp.get("x", 99) == 0:
            txt = re.sub(r"<[^>]+>", " ", ((p.get("options") or {}).get("content") or ""))
            txt = " ".join(txt.split())
            if txt and len(txt) <= 16:
                labels.append((gp.get("y", 0), txt))
    labels.sort()

    def role_for(gp):
        y = gp.get("y", -1)
        r = ""
        for ly, lt in labels:
            if ly <= y:
                r = lt
            else:
                break
        return r

    items = []
    for p in flat:
        if p.get("type") in ("row", "text"):
            continue
        gp = p.get("gridPos") or {}
        items.append({
            "id": str(p.get("id")),
            "title": p.get("title") or ("#" + str(p.get("id"))),
            "rolecat": role_cat(role_for(gp)),
            "w": gp.get("w", 0),
            "h": gp.get("h", 0),
        })
    return items
