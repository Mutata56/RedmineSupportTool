# -*- coding: utf-8 -*-


import argparse
import json
import logging
import os
import signal
import sys
import time
from logging.handlers import RotatingFileHandler

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from agent import trace as tr
from agent.orchestrator import Agent

LOG_MAX_BYTES = 10 * 1024 * 1024
LOG_BACKUPS = 5
CONTROL_FILE = os.path.join(ROOT, "state", "control.json")
LOCK_FILE = os.path.join(ROOT, "state", "agent.lock")

_lock_handle = None


def _acquire_singleton():


    global _lock_handle
    try:
        import fcntl
    except ImportError:
        return True
    try:
        os.makedirs(os.path.dirname(LOCK_FILE), exist_ok=True)
        _lock_handle = open(LOCK_FILE, "w")
        fcntl.flock(_lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _lock_handle.write(str(os.getpid()))
        _lock_handle.flush()
        return True
    except OSError:
        return False


def _install_sigterm():


    def _handler(signum, frame):
        raise KeyboardInterrupt
    try:
        signal.signal(signal.SIGTERM, _handler)
    except (ValueError, OSError):
        pass


def _read_paused():


    try:
        with open(CONTROL_FILE, encoding="utf-8") as f:
            d = json.load(f)
        return bool(isinstance(d, dict) and d.get("paused"))
    except Exception:
        return False


class _JsonlFormatter(logging.Formatter):


    def format(self, record):
        rec = {
            "ts": round(record.created, 3),
            "at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            rec["exc"] = self.formatException(record.exc_info)
        return json.dumps(rec, ensure_ascii=False)


def setup_logging():


    os.makedirs(os.path.join(ROOT, "logs"), exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
    log = logging.getLogger()
    log.setLevel(logging.INFO)
    fh = RotatingFileHandler(os.path.join(ROOT, "logs", "agent.log"),
                             maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUPS, encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    jh = RotatingFileHandler(os.path.join(ROOT, "logs", "agent.jsonl"),
                             maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUPS, encoding="utf-8")
    jh.setFormatter(_JsonlFormatter())
    for h in (fh, sh, jh):
        log.addHandler(h)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

    ap = argparse.ArgumentParser(description="work_agent: почта -> алерты в Redmine")
    group = ap.add_mutually_exclusive_group()
    group.add_argument("--once", action="store_true", help="один проход и выход")
    group.add_argument("--loop", action="store_true", help="опрос каждые poll_seconds (основной режим)")
    ap.add_argument("--live", action="store_true",
                    help="боевой режим: реально создавать заявки (иначе dry-run)")
    args = ap.parse_args()

    setup_logging()
    log = logging.getLogger("agent")

    if not _acquire_singleton():
        log.error("work_agent уже запущен (замок %s занят) - второй экземпляр не стартую", LOCK_FILE)
        sys.exit(1)
    _install_sigterm()
    tr.init(ROOT)
    tr.status("агент запускается (PID %d)", os.getpid())
    _stop = ("taskkill /PID %d /F" if os.name == "nt" else "kill %d") % os.getpid()
    log.info("work_agent запущен, PID %d (остановить: %s)", os.getpid(), _stop)
    dry_override = False if args.live else None


    _eff_dry = True
    if dry_override is not None:
        _eff_dry = dry_override
    else:
        try:
            with open(os.path.join(ROOT, "config", "config.json"), encoding="utf-8") as _f:
                _eff_dry = bool(json.load(_f).get("dry_run", True))
        except (OSError, ValueError):
            _eff_dry = True
    if not _eff_dry:
        log.warning("=== БОЕВОЙ РЕЖИМ: заявки будут создаваться в Redmine ===%s",
                    "" if args.live else " (из config.dry_run=false, без --live)")
    else:
        log.info("режим DRY-RUN: в Redmine НИЧЕГО не создаётся, только записи 'СОЗДАЛ БЫ'")

    if args.once:
        agent = Agent(ROOT, dry_run_override=dry_override)
        tr.set_mode(agent.dry_run)
        agent.poll()
        agent.close()
        tr.status("одиночный проход завершён, агент остановлен")
        return


    agent = None
    poll_seconds = 30
    while True:
        try:
            if agent is None:
                tr.status("инициализирую агента (конфиг, журнал, курсоры)")
                agent = Agent(ROOT, dry_run_override=dry_override)
                tr.set_mode(agent.dry_run)
                poll_seconds = agent.cfg.get("poll_seconds", 30)
                log.info("опрос каждые %d сек, остановка Ctrl+C", poll_seconds)


            if agent.reload_config():
                poll_seconds = agent.cfg.get("poll_seconds", 30)
            if _read_paused():


                tr.status("на паузе — новые заявки/письма не берёт (возобновить в GUI)")
                time.sleep(min(poll_seconds, 10))
                continue
            agent.poll()
            tr.status("сплю %d сек до следующего прохода", poll_seconds)
            time.sleep(poll_seconds)
        except KeyboardInterrupt:
            log.info("остановлен вручную")
            tr.status("остановлен вручную (Ctrl+C)")
            break
        except Exception as e:
            delay = min(poll_seconds, 60)
            if agent is None:
                log.exception("агент не запустился (IMAP/диск?) - повтор через %d сек", delay)
                tr.status("агент не запустился (%s) - повтор через %d сек", e, delay)
            else:
                log.exception("проход упал - продолжаю тем же агентом")
                tr.status("проход упал (%s) - восстанавливаюсь, повтор через %d сек", e, delay)
                try:
                    agent.close()
                except Exception:
                    pass
            try:
                time.sleep(delay)
            except KeyboardInterrupt:
                log.info("остановлен вручную")
                tr.status("остановлен вручную (Ctrl+C)")
                break
    if agent is not None:
        agent.close()
    tr.status("агент остановлен")


if __name__ == "__main__":
    main()
