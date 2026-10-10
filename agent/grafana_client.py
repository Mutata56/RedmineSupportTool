# -*- coding: utf-8 -*-


import json
import urllib.request


class GrafanaClient:
    def __init__(self, base, user, password):
        self.base = base.rstrip("/")
        self.user = user
        self.password = password
        self.cookie = None
        self.opener = urllib.request.build_opener()

    def login(self):

        body = json.dumps({"user": self.user, "password": self.password}).encode()
        req = urllib.request.Request(self.base + "/login", data=body,
                                     headers={"Content-Type": "application/json"})
        with self.opener.open(req, timeout=15) as r:
            set_cookies = r.headers.get_all("Set-Cookie") or []
        for c in set_cookies:
            if c.startswith("grafana_session="):
                self.cookie = c.split(";", 1)[0].split("=", 1)[1]
        if not self.cookie:
            raise RuntimeError("Grafana не отдала сессию (VPN включён? пароль клиент B?)")
        return self.cookie

    def _get(self, path):
        req = urllib.request.Request(self.base + path,
                                     headers={"Cookie": "grafana_session=" + self.cookie})
        with self.opener.open(req, timeout=20) as r:
            return json.loads(r.read().decode())

    def dashboard(self, uid):
        return self._get("/api/dashboards/uid/" + uid)

    def influx(self, q, ds_id=3, db="telegraf"):

        import urllib.parse
        qs = urllib.parse.urlencode({"db": db, "q": q})
        return self._get("/api/datasources/proxy/%s/query?%s" % (ds_id, qs))

    def alerts(self):

        return self._get("/api/alerts")

    def alert_state(self, dashboard_uid, name_substr):


        import re
        try:
            sub = (name_substr or "").lower().strip()
            if not sub:
                return None
            rx = re.compile(r"(?<![a-zа-я0-9_])" + re.escape(sub) + r"(?![a-zа-я0-9_])")
            best = None
            for a in self.alerts():
                if a.get("dashboardUid") != dashboard_uid:
                    continue
                if rx.search((a.get("name") or "").lower()):
                    st = a.get("state")
                    if st in ("alerting", "pending"):
                        return st
                    best = best or st
            return best
        except Exception:
            return None
