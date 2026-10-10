# -*- coding: utf-8 -*-


import json
from datetime import datetime, time, timedelta, timezone

MSK = timezone(timedelta(hours=3))


def _parse_hhmm(s, default=(9, 0)):

    try:
        hh, mm = str(s).split(":", 1)
        return time(int(hh), int(mm))
    except (ValueError, AttributeError):
        return time(*default)


def _parse_int(v, default):

    try:
        n = int(v)
    except (TypeError, ValueError):
        return default
    return n if n >= 0 else default


class Schedule:
    def __init__(self, data):
        d = data if isinstance(data, dict) else {}


        self.workdays = d.get("workdays") or {}
        self.shift_start = _parse_hhmm(d.get("shift_start", "09:00"))


        self.window_minutes = _parse_int(d.get("handoff_window_minutes", 20), 20)

    @classmethod
    def load(cls, path):

        try:
            with open(path, encoding="utf-8") as f:
                return cls(json.load(f))
        except (OSError, ValueError):
            return None

    @staticmethod
    def now():

        return datetime.now(MSK)

    def is_my_workday(self, d):

        return d.isoformat() in self.workdays

    def handoff_state(self, now, last_done_date):


        if not self.is_my_workday(now.date()):
            return "off"
        done = last_done_date == now.date().isoformat()
        cur = now.hour * 60 + now.minute
        start = self.shift_start.hour * 60 + self.shift_start.minute
        if cur < start - self.window_minutes:
            return "early"
        if cur > start + self.window_minutes:
            return "done" if done else "late"
        return "done" if done else "go"

    def should_handoff(self, now, last_done_date):


        return self.handoff_state(now, last_done_date) == "go"
