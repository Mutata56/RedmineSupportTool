# -*- coding: utf-8 -*-


import json
import logging
import os
import re
import threading
import time


def normalize_subject(s):

    s = re.sub(r"(?i)^(?:(re|fwd|fw)\s*(\[\d+\])?\s*:\s*)+", "", s or "")
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s


class Journal:
    def __init__(self, path, count_dry=True):
        self.path = path
        self.log = logging.getLogger("agent.journal")


        self.count_dry = count_dry
        self._seen = set()
        self._created_ts = []


        self._lock = threading.Lock()
        self._repair_tail(path)
        try:
            if os.path.exists(path):


                with open(path, encoding="utf-8", errors="replace") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            rec = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if not isinstance(rec, dict):
                            continue
                        mid = rec.get("message_id")


                        if mid and not rec.get("interim"):


                            self._seen.add(mid)
                        if rec.get("verdict") in ("created", "dry_run_create"):
                            self._created_ts.append(
                                (rec.get("ts", 0), rec.get("verdict") == "dry_run_create"))
        except OSError as e:


            self.log.error("журнал %s не читается (%s) - стартую с пустой памятью дедупа, "
                           "страховка только дедупом по дашборду", path, e)

    @staticmethod
    def _repair_tail(path):


        try:
            if not os.path.exists(path) or os.path.getsize(path) == 0:
                return
            with open(path, "rb") as f:
                f.seek(-1, os.SEEK_END)
                if f.read(1) == b"\n":
                    return
            with open(path, "ab") as f:
                f.write(b"\n")
            logging.getLogger("agent.journal").warning(
                "журнал: последняя строка была оборвана (kill -9?) - закрыл переводом, "
                "следующая запись не склеится")
        except OSError:
            pass

    def seen(self, message_id):
        return message_id in self._seen

    def record(self, message_id, verdict, rule=None, subject="", issue_id=None,
               note="", project_id=None, detail=None, interim=False):


        rec = {
            "ts": int(time.time()),
            "at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "message_id": message_id,
            "verdict": verdict,
            "rule": rule,
            "subject": subject,
            "issue_id": issue_id,
            "project_id": project_id,
            "note": note,
        }
        if interim:
            rec["interim"] = True
        if detail:
            rec["detail"] = str(detail)
        line = json.dumps(rec, ensure_ascii=False) + "\n"
        with self._lock:
            try:
                os.makedirs(os.path.dirname(self.path), exist_ok=True)
                with open(self.path, "a", encoding="utf-8") as f:
                    f.write(line)
            except OSError as e:


                self.log.error("журнал %s не пишется (%s) - вердикт '%s' (%s) остался только "
                               "в памяти процесса", self.path, e, verdict, message_id)
            if not interim:
                self._seen.add(message_id)

            if verdict in ("created", "dry_run_create"):
                self._created_ts.append((rec["ts"], verdict == "dry_run_create"))

    def created_last_hour(self):
        cutoff = time.time() - 3600
        with self._lock:
            self._created_ts = [(t, d) for t, d in self._created_ts if t >= cutoff]
            return sum(1 for _t, is_dry in self._created_ts if self.count_dry or not is_dry)
