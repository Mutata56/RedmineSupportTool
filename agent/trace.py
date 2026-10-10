# -*- coding: utf-8 -*-


import json
import os
import threading
import time

MAX_LINES = 50_000
MAX_BYTES = 3 * 1024 * 1024
RETENTION_DAYS = 5

_tracer = None


class Tracer:
    def __init__(self, root, max_lines=MAX_LINES, max_bytes=MAX_BYTES,
                 retention_days=RETENTION_DAYS):
        self.dir = os.path.join(root, "logs", "trace")
        self.status_file = os.path.join(root, "state", "status.json")
        self.path = os.path.join(self.dir, "agent_trace.jsonl")
        self.max_lines = max_lines
        self.max_bytes = max_bytes
        self.retention_days = retention_days
        self._lock = threading.Lock()
        self._fh = None
        self._lines = 0
        self._bytes = 0
        self.mode = None
        self.started_at = time.strftime("%Y-%m-%d %H:%M:%S")
        try:
            os.makedirs(self.dir, exist_ok=True)
            os.makedirs(os.path.dirname(self.status_file), exist_ok=True)
            self._open()
            self._retention()
        except OSError:
            self._fh = None


    def _open(self):

        self._lines = 0
        self._bytes = 0
        if os.path.exists(self.path):
            try:
                with open(self.path, "rb") as f:
                    data = f.read()
                self._bytes = len(data)
                self._lines = data.count(b"\n")
            except OSError:
                pass
        self._fh = open(self.path, "a", encoding="utf-8")

    def _rotate(self):
        try:
            self._fh.close()
        except Exception:
            pass
        stamp = time.strftime("%Y%m%d-%H%M%S")
        dst = os.path.join(self.dir, "agent_trace-%s.jsonl" % stamp)
        i = 1
        while os.path.exists(dst):
            dst = os.path.join(self.dir, "agent_trace-%s.%d.jsonl" % (stamp, i))
            i += 1
        try:
            os.replace(self.path, dst)
        except OSError:
            pass
        try:
            self._open()
        except OSError:
            self._fh = None
        self._retention()

    def _retention(self):

        cutoff = time.time() - self.retention_days * 86400
        try:
            for name in os.listdir(self.dir):
                if name.startswith("agent_trace-") and name.endswith(".jsonl"):
                    p = os.path.join(self.dir, name)
                    try:
                        if os.path.getmtime(p) < cutoff:
                            os.remove(p)
                    except OSError:
                        pass
        except OSError:
            pass


    def _fmt(self, fmt, args):
        try:
            return (fmt % args) if args else str(fmt)
        except Exception:
            return "%s %r" % (fmt, args)

    def _write(self, kind, msg):
        rec = {"ts": round(time.time(), 3),
               "at": time.strftime("%Y-%m-%d %H:%M:%S"),
               "kind": kind, "msg": msg}
        th = threading.current_thread().name
        if th != "MainThread":
            rec["thread"] = th
        line = json.dumps(rec, ensure_ascii=False) + "\n"
        with self._lock:
            if self._fh is None:
                return
            try:
                self._fh.write(line)
                self._fh.flush()
                self._lines += 1
                self._bytes += len(line.encode("utf-8"))
                if self._lines >= self.max_lines or self._bytes >= self.max_bytes:
                    self._rotate()
            except (OSError, ValueError):
                pass

    def set_mode(self, dry_run):


        self.mode = None if dry_run is None else bool(dry_run)

    def trace(self, fmt, *args):
        self._write("trace", self._fmt(fmt, args))

    def status(self, fmt, *args):
        msg = self._fmt(fmt, args)
        self._write("status", msg)
        try:
            payload = {"status": msg, "ts": round(time.time(), 3),
                       "at": time.strftime("%Y-%m-%d %H:%M:%S"),
                       "pid": os.getpid(), "started_at": self.started_at}
            if self.mode is not None:
                payload["dry_run"] = self.mode
            tmp = self.status_file + ".tmp"


            with self._lock:
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(payload, f, ensure_ascii=False)
                os.replace(tmp, self.status_file)
        except OSError:
            pass

    def close(self):
        with self._lock:
            try:
                if self._fh:
                    self._fh.close()
            except Exception:
                pass
            self._fh = None


def init(root, **kw):
    global _tracer
    _tracer = Tracer(root, **kw)
    return _tracer


def trace(fmt, *args):
    if _tracer is not None:
        _tracer.trace(fmt, *args)


def status(fmt, *args):
    if _tracer is not None:
        _tracer.status(fmt, *args)


def set_mode(dry_run):
    if _tracer is not None:
        _tracer.set_mode(dry_run)
