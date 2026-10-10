#!/usr/bin/env python3
# -*- coding: utf-8 -*-


import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time

from . import trace as tr

log = logging.getLogger("agent.sql")

HOME = os.path.expanduser("~")

_SECRETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "config", "secrets.local.json")


DB_LOGIN = "wmwhse1"
def _cfg_query_timeout(default=15):


    try:
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               "config", "config.json"), encoding="utf-8") as f:
            v = (json.load(f).get("db") or {}).get("query_timeout")
        return max(1, int(v)) if v else default
    except (OSError, ValueError, TypeError):
        return default


QUERY_TIMEOUT = _cfg_query_timeout()
PROBE_SQL = "SELECT TOP 1 * FROM lotxlocxid"


WMWHSE1_PASS_FISH = os.path.join(HOME, ".config/fish/functions/get_wmwhse1_pass.fish")
_PASS_FISH = {
    "wmwhse1": WMWHSE1_PASS_FISH,
    "sa": os.path.join(HOME, ".config/fish/functions/get_sa_pass.fish"),
}


def _pass_from_secrets(login):

    try:
        with open(_SECRETS, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    logins = (data.get("db") or {}).get("logins") or {}
    return logins.get(login) or None


def _pass_from_fish(login):

    path = _PASS_FISH.get(login)
    if not path:
        return None
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            src = f.read()
    except OSError:
        return None
    m = re.search(r"printf\s+'%s'\s+'([^']+)'", src)
    return m.group(1) if m else None


def read_db_pass(login):

    return _pass_from_secrets(login) or _pass_from_fish(login)


def read_wmwhse1_pass():

    return read_db_pass("wmwhse1")


_TDS_CACHE = {}


def detect_tds(host, port):


    if host in _TDS_CACHE:
        return _TDS_CACHE[host]
    pwd = read_db_pass("wmwhse1")
    if not pwd:
        return "7.4"
    for v in ("7.4", "7.0", "7.3", "7.2", "7.1"):
        try:
            p = subprocess.run(
                ["tsql", "-H", host, "-p", str(port), "-U", "wmwhse1", "-P", pwd],
                input="SELECT 1\nGO\nquit\n", capture_output=True, text=True,
                errors="replace", timeout=12, env=dict(os.environ, TDSVER=v))
            low = ((p.stdout or "") + (p.stderr or "")).lower()
            if "unexpected eof" in low or "there was a problem connecting" in low:
                continue
            _TDS_CACHE[host] = v
            log.info("TDS-версия подобрана: %s -> %s", host, v)
            return v
        except subprocess.TimeoutExpired:
            break
        except (subprocess.SubprocessError, OSError):
            continue
    return "7.4"


def _first_marker_line(out, needles):
    for ln in out.splitlines():
        low = ln.lower()
        if any(n in low for n in needles):
            return ln.strip()
    return ""


def run_probe_query(host, port, login=DB_LOGIN):


    pwd = read_db_pass(login)
    if not pwd:
        return "fail", "не нашёл пароль %s в fish-функции" % login


    sql = "%s\nGO\nquit\n" % PROBE_SQL
    env = dict(os.environ, TDSVER=detect_tds(host, port))
    try:
        p = subprocess.run(
            ["tsql", "-H", host, "-p", str(port), "-U", login, "-P", pwd],
            input=sql, capture_output=True, text=True, errors="replace",
            timeout=QUERY_TIMEOUT, env=env)
    except subprocess.TimeoutExpired:
        return "noconnect", "таймаут %d c" % QUERY_TIMEOUT
    except OSError as ex:
        return "fail", "tsql не запустился: %s" % ex
    out = (p.stdout or "") + (p.stderr or "")
    low = out.lower()
    if "unable to connect" in low or "there was a problem connecting" in low:
        return "noconnect", _first_marker_line(out, ("os error", "unable to connect")) or "сервер не отвечает"
    if "login failed" in low:
        return "autherr", _first_marker_line(out, ("login failed",)) or "login failed"
    if re.search(r"\bMsg \d+", out):
        return "sqlerr", _first_marker_line(out, ("msg ",)) or "ошибка SQL"
    return "ok", ""


_SIDE_EFFECT = frozenset((
    "exec", "execute", "grant", "revoke", "deny", "backup", "restore", "shutdown",
    "reconfigure", "dbcc", "openrowset", "openquery", "opendatasource", "openxml",
    "bulk", "waitfor", "kill", "writetext", "updatetext", "setuser", "checkpoint",
    "revert", "disable", "enable", "dump", "load",
    "receive",
))
_WRITE_DDL = frozenset(("insert", "update", "delete", "drop", "create", "truncate"))
_READ_BLACKLIST = _SIDE_EFFECT | _WRITE_DDL | frozenset(("merge", "alter", "into"))


def _is_dangerous(t):
    return t in _SIDE_EFFECT or t.startswith("sp_") or t.startswith("xp_")


def _is_go(ln):

    return re.fullmatch(r"\s*go(\s+\d+)?\s*", ln, re.IGNORECASE) is not None


def _is_temp(name):

    return bool(name) and name.startswith("#") and not name.startswith("##")


def _split_batches(sql):


    batches, cur = [], []
    for ln in str(sql or "").splitlines():
        if _is_go(ln):
            batches.append("\n".join(cur)); cur = []
        else:
            cur.append(ln)
    batches.append("\n".join(cur))
    return [b for b in batches if b.strip()]


def _strip_sql(sql):


    out, i, n = [], 0, len(sql)
    balanced = True
    while i < n:
        c = sql[i]
        nx = sql[i + 1] if i + 1 < n else ""
        if c == "'":
            i += 1
            closed = False
            while i < n:
                if sql[i] == "'":
                    if sql[i + 1:i + 2] == "'":
                        i += 2; continue
                    i += 1; closed = True; break
                i += 1
            if not closed:
                balanced = False
            out.append(" "); continue
        if c == '"':
            i += 1
            closed = False
            while i < n:
                if sql[i] == '"':
                    if sql[i + 1:i + 2] == '"':
                        i += 2; continue
                    i += 1; closed = True; break
                i += 1
            if not closed:
                balanced = False
            out.append(" "); continue
        if c == "[":
            i += 1
            closed = False
            while i < n:
                if sql[i] == "]":
                    if sql[i + 1:i + 2] == "]":
                        i += 2; continue
                    i += 1; closed = True; break
                i += 1
            if not closed:
                balanced = False
            out.append(" "); continue
        if c == "-" and nx == "-":
            i += 2
            while i < n and sql[i] not in "\r\n":
                i += 1
            out.append(" "); continue
        if c == "/" and nx == "*":
            i += 2
            closed = False
            while i < n:
                if sql[i] == "*" and sql[i + 1:i + 2] == "/":
                    i += 2; closed = True; break
                i += 1
            if not closed:
                balanced = False
            out.append(" "); continue
        out.append(c); i += 1
    return "".join(out), balanced


def read_only_guard(sql):

    raw = str(sql or "")


    if len(_split_batches(raw)) > 1 or any(_is_go(ln) for ln in raw.splitlines()):
        return False, "пакетный разделитель GO, можно только одно выражение"
    code, balanced = _strip_sql(raw)
    if not balanced:

        return False, "незакрытая кавычка, скобка или комментарий - запрос неоднозначен"
    stmts = [s for s in code.split(";") if s.strip()]
    if len(stmts) > 1:
        return False, "несколько выражений (через ;), можно только одно"
    body = (stmts[0] if stmts else "").strip()
    if not body:
        return False, "пустой запрос"
    tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", body)
    if not tokens:
        return False, "не вижу SQL"
    if tokens[0].lower() not in ("select", "with"):
        return False, "только SELECT / WITH … SELECT (а тут «%s»)" % tokens[0]
    for t in tokens:
        tl = t.lower()
        if tl in _READ_BLACKLIST or _is_dangerous(tl):
            return False, "запрещённое слово «%s», только чтение" % t


    if re.search(r"\bnext\s+value\s+for\b", body, re.I):
        return False, "NEXT VALUE FOR сдвигает sequence (запись), только чтение"
    return True, ""


def classify_script(sql):


    codes = []
    for batch in _split_batches(sql):
        c, balanced = _strip_sql(batch)
        if not balanced:
            return False, "незакрытая кавычка, скобка или комментарий - скрипт неоднозначен"
        codes.append(c)
    code = "\n".join(codes)
    toks = re.findall(r"#*[A-Za-z_][A-Za-z0-9_]*", code)
    low = [t.lower() for t in toks]
    if not low:
        return False, "пустой скрипт"

    for t in low:
        if t in _SIDE_EFFECT or t.startswith(("sp_", "xp_")):
            return False, "запрещено: «%s»" % t

    for t in ("insert", "update", "delete", "merge", "truncate", "alter"):
        if t in low:
            return False, "запрещено: «%s» (скрипт только на чтение)" % t

    for i, t in enumerate(low):
        if t == "into":
            tgt = low[i + 1] if i + 1 < len(low) else None
            if not _is_temp(tgt):
                return False, "SELECT … INTO не во временную #tmp: «%s»" % tgt
        if t in ("create", "drop") and low[i + 1:i + 2] == ["table"]:
            tgt = low[i + 2] if i + 2 < len(low) else None
            if not _is_temp(tgt):
                return False, "%s TABLE не #tmp: «%s»" % (t.upper(), tgt)
    return True, ""


class SessionDead(Exception):
    pass


class TsqlSession:


    def __init__(self, host, port, login=DB_LOGIN, pwd=None, transport=None):
        self.host, self.port, self.login = host, str(port), login
        self._pwd = pwd
        self._n = 0
        self._proc = None
        if transport is not None:
            self._write, self._readline, self._close = transport
        else:
            self._write = self._readline = self._close = None

    def start(self, sync_timeout=120):
        if self._write is None:
            pwd = self._pwd or read_db_pass(self.login)
            if not pwd:
                raise SessionDead("нет пароля для логина %s" % self.login)


            tdsver = os.environ.get("DBPICK_TDSVER") or detect_tds(self.host, self.port)
            env = dict(os.environ, TDSVER=tdsver)
            cmd = ["tsql", "-H", self.host, "-p", self.port, "-U", self.login, "-P", pwd]
            if shutil.which("stdbuf"):
                cmd = ["stdbuf", "-oL", "-eL"] + cmd
            self._proc = subprocess.Popen(
                cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, errors="replace", bufsize=1, env=env)

            def _proc_write(s):
                try:
                    self._proc.stdin.write(s)
                    self._proc.stdin.flush()
                except (BrokenPipeError, OSError, ValueError) as ex:
                    raise SessionDead("сессия оборвана при записи: %s" % ex)
            self._write = _proc_write
            self._readline = self._proc.stdout.readline
            self._close = self._proc.stdin.close
            log.info("tsql-сессия открыта: %s:%s логин=%s TDSVER=%s",
                     self.host, self.port, self.login, tdsver)
        try:
            self._sync(sync_timeout)
        except Exception:
            self.close()
            raise
        return self

    def _read_until(self, nonce, timeout=120):


        timer = threading.Timer(timeout, self._proc.kill) if self._proc is not None else None
        if timer:
            timer.start()
        try:
            lines = []
            while True:
                line = self._readline()
                if line == "":
                    raise SessionDead("сессия закрылась (таймаут/обрыв)")
                if nonce in line:
                    return lines
                lines.append(line)
        finally:
            if timer:
                timer.cancel()

    def _sync(self, timeout=120):
        self._n += 1
        nonce = "DBPICK_SYNC_%d" % self._n
        self._write("SELECT '%s'\nGO\n" % nonce)
        self._read_until(nonce, timeout)

    def run_batch(self, sql, timeout=120):


        self._n += 1
        nonce = "DBPICK_DONE_%d" % self._n
        t0 = time.time()
        self._write(sql.rstrip() + "\nGO\n")
        self._write("SELECT '%s'\nGO\n" % nonce)
        text = "".join(self._read_until(nonce, timeout))
        low = text.lower()


        ok = not ("unable to connect" in low or "there was a problem connecting" in low
                  or re.search(r"^\s*Msg \d+", text, re.M)
                  or re.search(r"^\s*login failed", text, re.M | re.I))
        cleaned = _clean_tsql(text)


        lines = cleaned.split("\n")
        if lines and re.fullmatch(r"\(\d+\s+rows?\s+affected\)", lines[0].strip()):
            cleaned = "\n".join(lines[1:])

        log.info("SQL %s:%s [%.80s] -> %s (%.1fс)",
                 self.host, self.port, " ".join(sql.split()),
                 "ok" if ok else "ОШИБКА", time.time() - t0)
        tr.trace("SQL %s:%s [%.120s] -> %s (%.1fс)", self.host, self.port,
                 " ".join(sql.split()), "ok" if ok else "ОШИБКА", time.time() - t0)
        return ok, cleaned

    def close(self):
        try:
            if self._close:
                self._close()
            if self._proc:
                self._proc.wait(timeout=3)
        except Exception:
            if self._proc:
                self._proc.kill()


def _clean_tsql(text):

    out = []
    for ln in text.splitlines():
        s = ln.strip()
        if not s:
            continue
        if re.fullmatch(r"(\d+>\s*)+", s):
            continue
        if s.startswith(("locale is", "locale charset", "using default charset",
                         "Setting ", "Default database")):
            continue
        out.append(re.sub(r"^(\d+>\s*)+", "", ln))
    return "\n".join(out).strip()


def _tsql_rows(out):

    lines = [l for l in out.splitlines()
             if l.strip() and not re.fullmatch(r"\(\d+\s+rows?\s+affected\)", l.strip())]
    if not lines:
        return [], []
    header = [h.strip() for h in lines[0].split("\t")]
    rows = [[c.strip() for c in l.split("\t")] for l in lines[1:]]
    return header, rows


def _colidx(header, name):

    nl = name.strip().lower()
    for i, h in enumerate(header or []):
        if str(h).strip().lower() == nl:
            return i
    return None


def _fmt_table(header, rows, max_rows=40):

    if not header:
        return "(нет данных)"
    n = len(header)
    norm = [[(r[i] if i < len(r) else "") for i in range(n)] for r in rows[:max_rows]]
    w = [len(str(header[i])) for i in range(n)]
    for r in norm:
        for i in range(n):
            w[i] = max(w[i], len(str(r[i])))
    def fmt(cells):
        return " | ".join(str(cells[i]).ljust(w[i]) for i in range(n))
    res = [fmt(header), "-+-".join("-" * w[i] for i in range(n))]
    res += [fmt(r) for r in norm] if norm else ["(пусто)"]
    if len(rows) > max_rows:
        res.append("… ещё %d строк" % (len(rows) - max_rows))
    return "\n".join(res)


def _sq(v):

    return "'" + str(v).replace("'", "''") + "'"


def _status_in(statuses):
    return "(" + ", ".join(_sq(s) for s in statuses) + ")"


def _format_run_result(out):


    lines = out.splitlines()
    hdr_i = next((i for i, l in enumerate(lines) if "\t" in l), None)
    if hdr_i is None:
        return out.strip()
    headers = lines[hdr_i].split("\t")
    data = []
    for l in lines[hdr_i + 1:]:
        if re.fullmatch(r"\(\d+\s+rows?\s+affected\)", l.strip()):
            break
        data.append(l)
    vals = "\n".join(data).split("\t")
    if len(vals) != len(headers):
        return out.strip()
    parts = []
    for h, v in zip(headers, vals):
        vlines = v.strip().splitlines() or [""]
        parts.append("%s: %s" % (h.strip(), vlines[0]))
        for ln in vlines[1:]:
            parts.append(" " * (len(h.strip()) + 2) + ln)
        parts.append("")
    return "\n".join(parts).rstrip()


def _format_md_table(out):


    lines = [l for l in out.splitlines()
             if l.strip() and not re.fullmatch(r"\(\d+\s+rows?\s+affected\)", l.strip())]
    if not lines:
        return "(пусто)"
    ncol = len(lines[0].split("\t"))
    res = []
    for l in lines:
        cells = l.split("\t")

        res.append("| " + " | ".join((cells[i].strip().replace("|", "&#124;") if i < len(cells) else "")
                                     for i in range(ncol)) + " |")
    return "\n".join(res)


if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 3 and sys.argv[1] == "probe":
        host = sys.argv[2]
        port = sys.argv[3] if len(sys.argv) > 3 else "1433"
        login = sys.argv[4] if len(sys.argv) > 4 else DB_LOGIN
        verdict, detail = run_probe_query(host, port, login)
        print("%s  %s" % (verdict, detail))
        sys.exit(0 if verdict == "ok" else 1)
    print(__doc__)
