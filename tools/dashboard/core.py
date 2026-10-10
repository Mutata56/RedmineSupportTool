# -*- coding: utf-8 -*-


import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
import urllib.parse


ROOT = os.environ.get("WA_CC_ROOT") or \
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from agent import approvals
from agent import redmine_client as rmc
from tools import control_center as cc

build_feed = cc.build_feed
read_logs = cc.read_logs
_read_jsonl = cc._read_jsonl

DASH_DIR = os.path.dirname(os.path.abspath(__file__))
STATUS_FILE = os.path.join(ROOT, "state", "status.json")
CONTROL_FILE = os.path.join(ROOT, "state", "control.json")
CONFIG_FILE = os.path.join(ROOT, "config", "config.json")
SECRETS_FILE = os.path.join(ROOT, "config", "secrets.local.json")
LOG_FILE = os.path.join(ROOT, "logs", "agent.jsonl")
TRACE_DIR = os.path.join(ROOT, "logs", "trace")
TRACE_FILE = os.path.join(TRACE_DIR, "agent_trace.jsonl")
JOURNAL_FILE = os.path.join(ROOT, "state", "processed.jsonl")
AGENT_CONSOLE = os.path.join(DASH_DIR, "agent_console.log")

STALE_SECONDS = 90
DAY = 86400


ERR_VERDICTS = {"error", "default_error"}
CREATED_VERDICTS = {"created", "dry_run_create"}
AI_LOGGERS = {"agent.llm", "agent.default"}


_PROC_LOCK = threading.RLock()
_CFG_LOCK = threading.Lock()


def load_config():
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            cfg = json.load(f)
        return cfg if isinstance(cfg, dict) else {}
    except (OSError, ValueError):
        return {}


LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]"}


def allowed_ext_origins():


    try:
        v = load_config().get("dashboard_ext_origins")
        if isinstance(v, list):
            return {str(o).rstrip("/") for o in v if o}
    except Exception:
        pass
    return {"chrome-extension://bhimochfhkgpbmffaenbofkbeogimckj"}


def origin_allowed(origin, ext_origins):


    try:
        parts = urllib.parse.urlsplit(origin)
        base = ("%s://%s" % (parts.scheme, parts.netloc)).rstrip("/")
        return parts.hostname in LOCAL_HOSTS or base in ext_origins
    except ValueError:
        return False


def _pid_state(pid):


    try:
        with open("/proc/%d/stat" % pid) as f:
            data = f.read()
        return data.rsplit(")", 1)[1].split()[0]
    except (OSError, IndexError):
        pass
    try:
        out = subprocess.run(["ps", "-p", str(pid), "-o", "state="],
                             capture_output=True, text=True, timeout=5)
        s = out.stdout.strip()
        return s[0] if s else None
    except (OSError, subprocess.SubprocessError):
        return None


def _pid_alive(pid):
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    except OSError:
        return False


    return _pid_state(pid) != "Z"


def _reap(pid):


    try:
        os.waitpid(pid, os.WNOHANG)
    except (ChildProcessError, OSError):
        pass


def _pid_is_agent(pid):


    argv = None
    try:
        with open("/proc/%d/cmdline" % pid, "rb") as f:
            argv = [a.decode("utf-8", "replace") for a in f.read().split(b"\x00") if a]
    except OSError:
        argv = None
    if not argv:
        try:
            out = subprocess.run(["ps", "-p", str(pid), "-o", "args="],
                                 capture_output=True, text=True, timeout=5)
            line = out.stdout.strip()
            argv = line.split() if line else []
        except (OSError, subprocess.SubprocessError):
            argv = []
    if not argv:
        return False
    is_py = "python" in os.path.basename(argv[0]).lower()
    has_script = any(os.path.basename(a) == "run_agent.py" for a in argv)
    return is_py and has_script


def _wait_pid_death(pid, seconds):


    deadline = time.time() + seconds
    while time.time() < deadline:
        _reap(pid)
        if not _pid_alive(pid):
            return True
        time.sleep(0.3)
    _reap(pid)
    return not _pid_alive(pid)


def is_paused():


    try:
        with open(CONTROL_FILE, encoding="utf-8") as f:
            d = json.load(f)
        return bool(isinstance(d, dict) and d.get("paused"))
    except Exception:
        return False


def set_paused(paused):


    paused = bool(paused)
    with _CFG_LOCK:
        d = {}
        try:
            with open(CONTROL_FILE, encoding="utf-8") as f:
                cur = json.load(f)
            if isinstance(cur, dict):
                d = cur
        except (OSError, ValueError):
            d = {}
        d["paused"] = paused
        try:
            os.makedirs(os.path.dirname(CONTROL_FILE), exist_ok=True)
            tmp = CONTROL_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False)
            os.replace(tmp, CONTROL_FILE)
        except OSError as e:
            return False, "не смог записать control.json: %s" % e
    return True, ("на паузе" if paused else "пауза снята")


def agent_status():


    dry = bool(load_config().get("dry_run", True))
    out = {"state": "stopped", "status_line": None, "uptime_seconds": None,
           "started_at": None, "pid": None, "at": None, "ts": None, "dry_run": dry,
           "paused": False}
    try:
        with open(STATUS_FILE, encoding="utf-8") as f:
            st = json.load(f)
    except (OSError, ValueError):
        return out
    if not isinstance(st, dict):
        return out
    ts, pid = st.get("ts"), st.get("pid")
    out.update({"status_line": st.get("status"), "started_at": st.get("started_at"),
                "pid": pid, "at": st.get("at"), "ts": ts})


    fresh = isinstance(ts, (int, float)) and (time.time() - ts) < STALE_SECONDS
    out["stale"] = bool(not fresh)
    if _pid_alive(pid) and _pid_is_agent(pid):


        st_dry = st.get("dry_run")
        if isinstance(st_dry, bool):
            dry = st_dry
        out["dry_run"] = dry
        out["state"] = "dry-run" if dry else "running"
        out["paused"] = is_paused()
        try:
            t0 = time.mktime(time.strptime(st.get("started_at", ""), "%Y-%m-%d %H:%M:%S"))
            out["uptime_seconds"] = max(0, int(time.time() - t0))
        except (ValueError, TypeError, OverflowError):
            pass
    if out["state"] == "stopped":


        out["pid"] = out["started_at"] = out["status_line"] = None
    return out


def start_agent(live=None):


    with _PROC_LOCK:
        st = agent_status()
        if st["state"] != "stopped":
            return False, "агент уже работает (pid %s)" % st["pid"]
        dry = (not live) if live is not None else bool(load_config().get("dry_run", True))
        cmd = ["python3", "run_agent.py", "--loop"] + ([] if dry else ["--live"])
        try:
            console = open(AGENT_CONSOLE, "ab")
        except OSError as e:
            console = subprocess.DEVNULL
            e = None
        try:
            proc = subprocess.Popen(
                cmd, cwd=ROOT, stdin=subprocess.DEVNULL,
                stdout=console, stderr=subprocess.STDOUT,
                start_new_session=True)
        except OSError as e:
            return False, "не запустился: %s" % e
        finally:
            if console is not subprocess.DEVNULL:
                console.close()
        set_paused(False)
        return True, "запущен (%s), pid %d" % ("dry-run" if dry else "БОЕВОЙ/LIVE", proc.pid)


def _live_agent_pid():


    st = agent_status()
    if st["state"] == "stopped":
        return None, "агент не запущен (статус устарел или процесс не жив)"
    pid = st.get("pid")
    if not isinstance(pid, int) or pid <= 0:
        return None, "в status.json нет корректного pid"
    if not _pid_is_agent(pid):
        return None, "pid %d не похож на run_agent - не трогаю чужой процесс" % pid
    return pid, None


def stop_agent():


    with _PROC_LOCK:
        pid, err = _live_agent_pid()
        if pid is None:
            return False, err
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError as e:
            return False, "SIGTERM не ушёл: %s" % e
        set_paused(False)
        return True, "SIGTERM отправлен pid %d" % pid


def restart_agent(wait_seconds=25):


    with _PROC_LOCK:
        cur = agent_status()
        live = None if cur["state"] == "stopped" else (not cur["dry_run"])
        pid, _ = _live_agent_pid()
        if pid is not None:
            ok, msg = stop_agent()
            if not ok:
                return False, msg
            if not _wait_pid_death(pid, wait_seconds):
                try:
                    os.kill(pid, signal.SIGKILL)
                except OSError:
                    pass
                if not _wait_pid_death(pid, 5):
                    return False, "процесс %d не удалось остановить (даже SIGKILL)" % pid
        return start_agent(live=live)


def set_run_mode(dry_run):


    dry_run = bool(dry_run)
    with _PROC_LOCK:

        with _CFG_LOCK:
            try:
                with open(CONFIG_FILE, encoding="utf-8") as f:
                    cfg = json.load(f)
                if not isinstance(cfg, dict):
                    return False, "config.json не объект - не трогаю"
            except (OSError, ValueError) as e:
                return False, "не смог прочитать config.json: %s" % e
            cfg["dry_run"] = dry_run
            try:
                tmp = CONFIG_FILE + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(cfg, f, ensure_ascii=False, indent=2)
                os.replace(tmp, CONFIG_FILE)
            except OSError as e:
                return False, "не смог записать config: %s" % e
        mode = "dry-run" if dry_run else "БОЕВОЙ/LIVE"

        st = agent_status()
        if st["state"] == "stopped":
            return True, "режим сохранён: %s (агент остановлен - применится при запуске)" % mode
        pid, err = _live_agent_pid()
        if pid is None:
            return True, "режим сохранён: %s (перезапусти агента вручную: %s)" % (mode, err)
        ok, msg = stop_agent()
        if not ok:
            return False, "config обновлён на %s, но не остановил агента: %s" % (mode, msg)
        if not _wait_pid_death(pid, 15):
            return False, "config обновлён на %s, но процесс %d не остановился" % (mode, pid)
        ok, smsg = start_agent(live=not dry_run)
        return (ok, "режим применён: %s; %s" % (mode, smsg)) if ok else (ok, smsg)


_CFG_INT_FIELDS = {
    "poll_seconds":         (("poll_seconds",),           5, 3600),
    "max_mail_age_minutes": (("max_mail_age_minutes",),   1, 1440),
    "max_issues_per_hour":  (("max_issues_per_hour",),    0, 1000),
    "query_id":             (("dedup", "query_id"),       1, 10_000_000),
    "max_calls_route":      (("llm", "max_calls_route"),  0, 200),
    "max_calls_intent":     (("llm", "max_calls_intent"), 0, 200),
}


_CFG_BOOL_FIELDS = {"healthscript_cld_off": ("healthscript_cld_off",),
                    "mail_enabled": ("mail_enabled",),

                    "take_chief": ("roles", "auto_take_chief"),
                    "take_engineer": ("roles", "auto_take_engineer")}


_CFG_ROLE_FIELDS = {
    "role_chief_engineer": ("roles", "chief_engineer"),
    "role_engineer":       ("roles", "engineer"),
}

_CFG_STR_FIELDS = {
    "telegram_chat_id": (("messengers", "telegram", "chat_id"), 64),
    "ntfy_topic":       (("messengers", "ntfy", "topic"),       128),
}


_CFG_MESSENGER_TOGGLES = {"messenger_telegram": "telegram", "messenger_ntfy": "ntfy"}


def _read_config_strict():


    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, ValueError) as e:
        return None, "не смог прочитать config.json: %s" % e
    if not isinstance(cfg, dict):
        return None, "config.json не объект - не трогаю"
    return cfg, None


def _write_config_atomic(cfg):

    try:
        tmp = CONFIG_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        os.replace(tmp, CONFIG_FILE)
    except OSError as e:
        return False, "не смог записать config: %s" % e
    return True, ""


def _set_nested(cfg, path, value):


    d = cfg
    for k in path[:-1]:
        if not isinstance(d.get(k), dict):
            d[k] = {}
        d = d[k]
    d[path[-1]] = value


def _mask_anthropic_key():


    try:
        with open(SECRETS_FILE, encoding="utf-8") as f:
            sec = json.load(f)
        key = (sec.get("anthropic_api_key") or "").strip() if isinstance(sec, dict) else ""
    except (OSError, ValueError):
        key = ""
    return ("sk-ant-••••" + key[-4:]) if key else ""


def _telegram_token_set():


    try:
        with open(SECRETS_FILE, encoding="utf-8") as f:
            sec = json.load(f)
        return bool(isinstance(sec, dict) and (sec.get("telegram_bot_token") or "").strip())
    except (OSError, ValueError):
        return False


def _read_secrets():

    ok, sec, _err = _read_secrets_strict()
    return sec if ok else {}


def _read_secrets_strict():


    if not os.path.exists(SECRETS_FILE):
        return True, {}, ""
    try:
        with open(SECRETS_FILE, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError) as e:
        return False, {}, ("secrets.local.json не прочитан (%s) — отказываюсь перезаписывать, "
                           "иначе потеряются остальные секреты" % e)
    if not isinstance(d, dict):
        return False, {}, "secrets.local.json не JSON-объект — отказываюсь перезаписывать"
    return True, d, ""


def _write_secrets_atomic(sec):

    try:
        tmp = SECRETS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(sec, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, SECRETS_FILE)
    except OSError as e:
        return False, "не смог записать secrets: %s" % e
    return True, ""


def redmine_accounts():

    return rmc.list_accounts(_read_secrets())


def set_redmine_active(name):


    name = (name or "").strip()
    if not name:
        return False, "не задано имя аккаунта"
    with _CFG_LOCK:
        rok, sec, rerr = _read_secrets_strict()
        if not rok:
            return False, rerr
        accs = sec.get("redmine_accounts")
        if not isinstance(accs, dict) or name not in accs:
            return False, "аккаунт «%s» не найден (есть: %s)" % (
                name, ", ".join(sorted(accs)) if isinstance(accs, dict) and accs else "нет ни одного")
        sec["redmine_active"] = name
        ok, err = _write_secrets_atomic(sec)
    if not ok:
        return False, err
    return True, ("активный аккаунт Redmine: «%s». Дашборд уже на нём; агент подхватит при "
                  "следующем запуске." % name)


def save_redmine_account(name, api_key=None, url=None, label=None, make_active=False):


    name = (name or "").strip()
    if not name:
        return False, "не задано имя аккаунта"
    api_key = (api_key or "").strip()


    rok, sec0, rerr = _read_secrets_strict()
    if not rok:
        return False, rerr
    accs0 = sec0.get("redmine_accounts")
    cur0 = accs0.get(name) if isinstance(accs0, dict) and isinstance(accs0.get(name), dict) else {}
    eff_url = (url or cur0.get("url") or sec0.get("redmine_url") or "").rstrip("/")
    eff_key = api_key or (cur0.get("api_key") or "")
    if not eff_url or not eff_key:
        return False, "нужны и url, и api_key (url можно взять из текущего redmine_url)"
    who = None
    if api_key:
        try:
            who = rmc.RedmineClient(eff_url, eff_key).current_user()
        except Exception as e:
            return False, "токен не принят Redmine (%s): проверь ключ и url" % e
        if not who.get("id"):
            return False, "Redmine не вернул пользователя по этому токену"

    with _CFG_LOCK:
        rok, sec, rerr = _read_secrets_strict()
        if not rok:
            return False, rerr
        accs = sec.get("redmine_accounts")
        if not isinstance(accs, dict):
            accs = {}
        cur = accs.get(name) if isinstance(accs.get(name), dict) else {}
        entry = dict(cur)
        entry["url"], entry["api_key"] = eff_url, eff_key
        if label:
            entry["label"] = label
        if who:
            entry["user_id"] = who["id"]
            entry.setdefault("label", who.get("name") or name)
            if not label and who.get("name"):
                entry["label"] = who["name"]
        accs[name] = entry
        sec["redmine_accounts"] = accs
        if make_active or not sec.get("redmine_active"):
            sec["redmine_active"] = name
        ok, err = _write_secrets_atomic(sec)
    if not ok:
        return False, err
    return True, "аккаунт «%s» сохранён (user_id=%s)%s" % (
        name, accs[name].get("user_id"), ", он активен" if sec.get("redmine_active") == name else "")


def delete_redmine_account(name):

    name = (name or "").strip()
    with _CFG_LOCK:
        rok, sec, rerr = _read_secrets_strict()
        if not rok:
            return False, rerr
        accs = sec.get("redmine_accounts")
        if not isinstance(accs, dict) or name not in accs:
            return False, "аккаунт «%s» не найден" % name
        if len(accs) <= 1:
            return False, "это последний аккаунт — удалять нельзя"
        accs.pop(name)
        sec["redmine_accounts"] = accs
        if sec.get("redmine_active") == name:
            sec["redmine_active"] = sorted(accs)[0]
        ok, err = _write_secrets_atomic(sec)
    if not ok:
        return False, err
    return True, "аккаунт «%s» удалён (активный: «%s»)" % (name, sec.get("redmine_active"))


def read_agent_config():


    cfg = load_config()
    llm = cfg.get("llm") if isinstance(cfg.get("llm"), dict) else {}
    dedup = cfg.get("dedup") if isinstance(cfg.get("dedup"), dict) else {}
    routing = cfg.get("routing") if isinstance(cfg.get("routing"), dict) else {}
    roles = cfg.get("roles") if isinstance(cfg.get("roles"), dict) else {}
    known = cfg.get("known_people") if isinstance(cfg.get("known_people"), dict) else {}
    msgr = cfg.get("messengers") if isinstance(cfg.get("messengers"), dict) else {}
    tg = msgr.get("telegram") if isinstance(msgr.get("telegram"), dict) else {}
    ntfy = msgr.get("ntfy") if isinstance(msgr.get("ntfy"), dict) else {}
    enabled = msgr.get("enabled") if isinstance(msgr.get("enabled"), list) else []
    return {
        "poll_seconds": cfg.get("poll_seconds"),
        "max_mail_age_minutes": cfg.get("max_mail_age_minutes"),
        "max_issues_per_hour": cfg.get("max_issues_per_hour"),
        "query_id": dedup.get("query_id"),
        "max_calls_route": llm.get("max_calls_route"),
        "max_calls_intent": llm.get("max_calls_intent"),
        "anthropic_api_key": _mask_anthropic_key(),
        "routing": routing,

        "role_chief_engineer": roles.get("chief_engineer"),
        "role_engineer": roles.get("engineer"),
        "known_people": known,

        "messenger_telegram": "telegram" in enabled,
        "messenger_ntfy": "ntfy" in enabled,
        "telegram_chat_id": tg.get("chat_id"),
        "ntfy_url": ntfy.get("url"),
        "ntfy_topic": ntfy.get("topic"),
        "telegram_token_set": _telegram_token_set(),

        "healthscript_cld_off": bool(cfg.get("healthscript_cld_off")),

        "mail_enabled": bool(cfg.get("mail_enabled", True)),
        "take_chief": bool((cfg.get("roles") or {}).get("auto_take_chief", True)),
        "take_engineer": bool((cfg.get("roles") or {}).get("auto_take_engineer", True)),

        "dry_run": agent_status().get("dry_run"),
    }


def set_agent_config(fields):


    if not isinstance(fields, dict) or not fields:
        return False, "нет полей для обновления"

    for k, v in fields.items():
        if k in _CFG_INT_FIELDS:
            _, lo, hi = _CFG_INT_FIELDS[k]
            if isinstance(v, bool) or not isinstance(v, int):
                return False, "поле «%s» должно быть целым числом" % k
            if not (lo <= v <= hi):
                return False, "поле «%s» вне диапазона %d..%d" % (k, lo, hi)
        elif k in _CFG_ROLE_FIELDS:
            if isinstance(v, bool) or not isinstance(v, int):
                return False, "поле «%s» должно быть целым числом (0 = сбросить)" % k
            if not (0 <= v <= 10_000_000):
                return False, "поле «%s» вне диапазона 0..10000000" % k
        elif k in _CFG_STR_FIELDS:
            _, cap = _CFG_STR_FIELDS[k]
            if not isinstance(v, str):
                return False, "поле «%s» должно быть строкой" % k
            if len(v) > cap:
                return False, "поле «%s» длиннее %d символов" % (k, cap)
        elif k in _CFG_MESSENGER_TOGGLES or k in _CFG_BOOL_FIELDS:
            if not isinstance(v, bool):
                return False, "поле «%s» должно быть true/false" % k
        else:
            return False, "неизвестное поле: «%s»" % k


    with _CFG_LOCK:
        cfg, err = _read_config_strict()
        if cfg is None:
            return False, err

        for k, v in fields.items():
            if k in _CFG_INT_FIELDS:
                _set_nested(cfg, _CFG_INT_FIELDS[k][0], v)
            elif k in _CFG_ROLE_FIELDS:
                _set_nested(cfg, _CFG_ROLE_FIELDS[k], v or None)
            elif k in _CFG_STR_FIELDS:
                path, _ = _CFG_STR_FIELDS[k]
                val = v.strip()

                _set_nested(cfg, path, (val or None) if k == "telegram_chat_id" else val)
            elif k in _CFG_MESSENGER_TOGGLES:
                name = _CFG_MESSENGER_TOGGLES[k]
                m = cfg.get("messengers")
                if not isinstance(m, dict):
                    m = cfg["messengers"] = {}
                cur = [x for x in (m.get("enabled") or []) if isinstance(x, str)]
                cur = [x for x in cur if x != name] + ([name] if v else [])

                m["enabled"] = [n for n in ("telegram", "ntfy") if n in cur] + \
                               [x for x in cur if x not in ("telegram", "ntfy")]
            else:
                _set_nested(cfg, _CFG_BOOL_FIELDS[k], v)
        ok, werr = _write_config_atomic(cfg)
    if not ok:
        return False, werr


    msg = "сохранено настроек: %d (применится за один проход)" % len(fields)
    if any(k in _CFG_MESSENGER_TOGGLES or k in _CFG_STR_FIELDS for k in fields):
        msg += "; настройки мессенджеров подхватятся после перезапуска агента"
    return True, msg


def edit_routing(action, key, project_id=None, client=None):


    if action not in ("add", "delete"):
        return False, "action должен быть add|delete"
    if not isinstance(key, str) or not key.strip():
        return False, "ключ (имя сервера) не должен быть пустым"
    key = key.strip().upper()
    if action == "add" and (isinstance(project_id, bool) or not isinstance(project_id, int)):
        return False, "project_id должен быть целым числом"
    with _CFG_LOCK:
        cfg, err = _read_config_strict()
        if cfg is None:
            return False, err
        routing = cfg.get("routing")
        if not isinstance(routing, dict):
            routing = cfg["routing"] = {}
        if action == "add":
            routing[key] = {"project_id": project_id, "client": client or ""}
            msg = "маршрут %s -> проект %d сохранён" % (key, project_id)
        else:
            if key not in routing:
                return False, "маршрут %s не найден" % key
            del routing[key]
            msg = "маршрут %s удалён" % key
        ok, werr = _write_config_atomic(cfg)
    return (True, msg) if ok else (False, werr)


def read_trace(q="", n=400):


    try:
        n = max(1, min(int(n), 5000))
    except (TypeError, ValueError):
        n = 400
    recs = _read_jsonl(TRACE_FILE)
    if len(recs) < n:
        try:
            rotated = sorted(
                (f for f in os.listdir(TRACE_DIR)
                 if f.startswith("agent_trace-") and f.endswith(".jsonl")),
                reverse=True)
        except OSError:
            rotated = []
        for name in rotated:
            recs = _read_jsonl(os.path.join(TRACE_DIR, name)) + recs
            if len(recs) >= n:
                break
    if q:
        ql = q.lower()
        recs = [r for r in recs if ql in str(r.get("msg", "")).lower()]
    return recs[-n:]


def ai_calls_24h():

    day = time.time() - DAY
    return sum(1 for r in _read_jsonl(LOG_FILE)
               if r.get("logger") in AI_LOGGERS and (r.get("ts") or 0) > day)


def stats24(feed):
    day = time.time() - DAY
    fresh = [r for e in feed["mails"] + feed["tickets"] for r in e["records"]
             if r["ts"] > day]
    return {
        "mails_24h": sum(1 for e in feed["mails"] if e["last_ts"] > day),
        "tickets_24h": sum(1 for e in feed["tickets"] if e["last_ts"] > day),


        "pending": sum(1 for a in feed["approvals"] if a.get("stage") != "reviewing"),
        "created_24h": sum(1 for r in fresh if r["verdict"] in CREATED_VERDICTS),
        "errors_24h": sum(1 for r in fresh if r["verdict"] in ERR_VERDICTS),
        "ai_calls_24h": ai_calls_24h(),
    }


_SESSION_RE = re.compile(r"session=([0-9a-fA-F-]{8,})")


def find_session_id(entity):

    sid = None
    for r in entity.get("records", ()):
        m = _SESSION_RE.search(str(r.get("note") or ""))
        if m:
            sid = m.group(1)
    return sid


def recent_events(feed, limit=30):

    rows = []
    for e in feed["mails"] + feed["tickets"]:
        for r in e["records"]:
            rows.append({"ts": r["ts"], "at": r["at"], "kind": e["kind"],
                         "pipe": e["pipe"], "verdict": r["verdict"], "note": r["note"],
                         "subject": e["subject"], "issue_id": r["issue_id"] or e["issue_id"],
                         "key": e["key"], "interim": r["interim"]})
    rows.sort(key=lambda x: -x["ts"])
    return rows[:limit]
