# -*- coding: utf-8 -*-


import base64
import glob
import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import time

from fastapi import APIRouter

from .. import core, drafts
from ..models import ChatSendRequest
from agent import cli_json
from agent import redmine_client as rmc
from agent import default_flow as dfl

router = APIRouter(prefix="/api/chats")

TIMEOUT = 3600


_AUTODRAFT_MIN_CHARS = 400


CHATS_DIR = os.path.join(core.ROOT, "state", "chats")
CHAT_CWD = os.path.join(CHATS_DIR, ".cwd")
CLAUDE_PROJECTS = os.path.expanduser("~/.claude/projects")
MAX_MESSAGES = 400


AI_TEXT_VERDICTS = {"llm_analysis", "llm_low_confidence", "opus_draft_ready", "clc_review_ready",
                    "default_done", "default_low_confidence", "draft_ready"}

_locks_guard = threading.Lock()
_locks = {}

_active_guard = threading.Lock()
_active = set()


def _is_active(issue_id):
    with _active_guard:
        return issue_id in _active


def _lock(issue_id):
    with _locks_guard:
        return _locks.setdefault(issue_id, threading.Lock())


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _claude_bin():
    return (os.environ.get("DASH_CLAUDE_BIN")
            or (core.load_config().get("llm") or {}).get("claude_bin")
            or "claude")


def _secrets():
    try:
        with open(os.path.join(core.ROOT, "config", "secrets.local.json"),
                  encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _chat_path(issue_id):
    return os.path.join(CHATS_DIR, "%d.json" % issue_id)


def _load_chat(issue_id):
    try:
        with open(_chat_path(issue_id), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def _save_chat(issue_id, data):
    os.makedirs(CHATS_DIR, exist_ok=True)
    if len(data.get("messages", ())) > MAX_MESSAGES:
        data["messages"] = data["messages"][-MAX_MESSAGES:]
    tmp = _chat_path(issue_id) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, _chat_path(issue_id))


def _all_chat_files():
    out = {}
    try:
        names = os.listdir(CHATS_DIR)
    except OSError:
        return out
    for n in names:
        if n.endswith(".json"):
            try:
                iid = int(n[:-5])
            except ValueError:
                continue
            c = _load_chat(iid)
            if c:
                out[iid] = c
    return out


def _deleted_path():
    return os.path.join(CHATS_DIR, "_deleted.json")


def _load_deleted():
    try:
        with open(_deleted_path(), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_deleted(d):
    os.makedirs(CHATS_DIR, exist_ok=True)
    tmp = _deleted_path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False)
    os.replace(tmp, _deleted_path())


def _ticket_entities(feed, issue_id):

    return [e for e in feed["tickets"] if e.get("issue_id") == issue_id]


def _clean_agent_text(text):


    if not text:
        return text
    for marker in ("=== аудит тул-вызовов", "\n=== аудит", "=== аудит"):
        i = text.find(marker)
        if i != -1:
            text = text[:i]
            break
    return text.strip()


def _agent_messages(entities):

    out = []
    for e in entities:
        for r in e.get("records", ()):
            if r.get("verdict") in AI_TEXT_VERDICTS and r.get("detail"):
                txt = _clean_agent_text(r["detail"])
                if not txt:
                    continue
                out.append({"role": "agent", "text": txt,
                            "at": r.get("at") or "", "ts": r.get("ts") or 0,
                            "verdict": r["verdict"]})
    return out


def _session_from_entities(entities):

    recs = [r for e in entities for r in e.get("records", ())]
    recs.sort(key=lambda r: r.get("ts") or 0)
    return core.find_session_id({"records": recs})


def _session_cwd(session_id):


    for path in glob.glob(os.path.join(CLAUDE_PROJECTS, "*", session_id + ".jsonl")):
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(rec, dict) and rec.get("cwd"):
                        return rec["cwd"], True
        except OSError:
            continue
    return None, False


PLAYBOOK_DIR = os.path.join(core.ROOT, "documentation", "playbook")

SYSTEM_PROMPT = (
    "Ты ИИ-ассистент инженера техподдержки WMS (Infor SCE) в GUI-чате по конкретной заявке "
    "Redmine. У тебя ПОЛНЫЕ права, как в обычной CLI-сессии: читать и писать локальные файлы, "
    "запускать команды (Bash), ходить в интернет, искать по графу кода клиента (codebase-memory), "
    "смотреть заявку (get_issue). Если по заявке подключены wa-influx (influx_query — метрики "
    "Grafana) и wa-sql (run_select — ОДИН read-only SELECT по БД площадки, безопаснее сырого tsql), "
    "предпочитай их сырому Bash/curl. Ты на машине инженера, он тобой управляет: делай, что он просит. "
    "БЕЗ его явной команды НЕ пиши в клиентский Redmine и в боевые БД клиентов. Заявка чата дана в "
    "контексте ниже; детали смотри через get_issue. Отвечай по-русски, кратко и по делу, в Markdown "
    "(SQL блоком ```sql, имена таблиц и полей в `бэктиках`)."


    "\n\nget_issue У ТЕБЯ ТОЧНО ЕСТЬ в этой сессии (сервер redmine всегда подключён к заявке чата) - "
    "если первый вызов любого MCP-инструмента (get_issue/run_select/influx_query) отвечает ошибкой "
    "вида «не подключён»/«still connecting»/пустым списком тулов - это гонка подключения сервера при "
    "старте, НЕ отсутствие инструмента: повтори тот же вызов ещё раз (обычно достаточно одного повтора), "
    "и только если он СНОВА падает именно как «инструмент не найден» - сообщай инженеру, что тула нет. "
    "Никогда не пиши «у меня нет инструмента для этого», не попробовав вызвать его минимум дважды."


    "\n\nЕсли wa-sql НЕ подключён (тула run_select нет вообще, а не «ещё подключается») - площадка "
    "заявки не резолвилась автоматически по имени проекта. Сервер БД площадки всё равно можно найти "
    "руками: таблица код площадки/warehouse-имя - в `agent/grafana_sets.py` (SITES), а код площадки -> "
    "host/port/логин - в `config/config.json` (`db.servers`). Прочитай оба (Read/Bash), сопоставь "
    "проект/тему заявки с warehouse-именем и дальше подключайся сам (сырой `tsql`), не сообщай "
    "инженеру «не могу найти сервер», не заглянув сначала в эти два файла."

    "\n\nПЕРЕД разбором любой проблемы ОБЯЗАТЕЛЬНО проверь плейбуки: " + PLAYBOOK_DIR + "/*.md "
    "— посмотри список файлов и grep по ключевым словам заявки (поток/событие/текст ошибки/"
    "таблица/проект). Нашёлся подходящий — решай ПО НЕМУ (это выверенные на прошлых заявках "
    "процедуры, они главнее твоих догадок) и явно скажи, каким плейбуком пользуешься. "
    "Не нашёлся — так и скажи одной строкой и разбирай сам.")


_SQL_ENV_CACHE = {}


def _resolve_sql_env(issue_id, url, key, cfg):


    if issue_id in _SQL_ENV_CACHE:
        return _SQL_ENV_CACHE[issue_id]

    def _work():
        sql_env = None
        try:
            import urllib.request
            req = urllib.request.Request(
                url.rstrip("/") + "/issues/%d.json" % int(issue_id),
                headers={"X-Redmine-API-Key": key, "User-Agent": "work-agent-chat/0.1"})
            with urllib.request.urlopen(req, timeout=4) as r:
                data = json.loads(r.read() or b"{}")
            proj = (((data or {}).get("issue") or {}).get("project") or {}).get("name") or ""
            from agent.alert_agent import site_from_project
            site = site_from_project(proj)
            srv = (((cfg.get("db", {}).get("servers") or {}).get(site["code"]) or {}) if site else {})
            if srv.get("host"):
                sql_env = {"WA_DB_HOST": str(srv["host"]),
                           "WA_DB_PORT": str(srv.get("port") or 1433),
                           "WA_DB_LOGIN": cfg.get("locks", {}).get("login", "sa") or "sa",
                           "WA_DB_WHSE": "wmwhse2" if site["code"] == "CLE" else "wmwhse1"}
                if srv.get("tdsver"):
                    sql_env["WA_DB_TDSVER"] = str(srv["tdsver"])
        except Exception:
            sql_env = None
        _SQL_ENV_CACHE[issue_id] = sql_env

    t = threading.Thread(target=_work, daemon=True)
    t.start()
    t.join(timeout=1.5)
    return _SQL_ENV_CACHE.get(issue_id)


def _chat_tool_envs(issue_id, url, key):


    cfg = core.load_config()
    sec = _secrets()
    influx_env = None
    gpwd = (sec.get("grafana_password") or "").strip()
    if gpwd:
        gf = cfg.get("grafana", {})
        influx_env = {"WA_GF_BASE": gf.get("base", "http://service.example.invalid"),
                      "WA_GF_USER": (sec.get("grafana_user") or "").strip(),
                      "WA_GF_PASSWORD": gpwd,
                      "WA_GF_DS_ID": str(gf.get("influx_ds_id", 3)),
                      "WA_GF_DB": gf.get("influx_db", "telegraf")}
    return _resolve_sql_env(issue_id, url, key, cfg), influx_env


def standard_prompt(issue_id, subject="", url=None, key=None):


    from agent import alert_agent as aa
    cfg = core.load_config()
    proj, body = "", ""
    if url and key:


        got = {}

        def _fetch():
            try:
                got["d"] = rmc.RedmineClient(url, key).get_issue(int(issue_id), include="")
            except Exception:
                got["d"] = None

        th = threading.Thread(target=_fetch, daemon=True)
        th.start()
        th.join(timeout=4.0)
        data = got.get("d") or {}
        proj = (data.get("project") or {}).get("name") or ""
        body = data.get("description") or ""
        subject = data.get("subject") or subject
    playbooks = dfl.playbook_index()
    site = aa.site_from_project(proj) if proj else None
    srv = (((cfg.get("db", {}).get("servers") or {}).get(site["code"]) or {}) if site else {})
    docs = (cfg.get("default_flow") or {}).get("docs_dirs") or {}
    code_path = next((v for k, v in docs.items() if k and k.lower() in (proj or "").lower()), None)
    graph_project = os.path.basename(str(code_path).rstrip("/")) if code_path else None
    if re.search(r"\[alerting\]", subject or "", re.I):
        return aa.build_alert_prompt(int(issue_id), (proj or "площадка не определена"),
                                     subject or "", body, [], [], hints_block="",
                                     playbooks=playbooks, graph_project=graph_project,
                                     code_path=code_path)
    return aa.build_default_prompt(int(issue_id), proj, subject or "", body,
                                   sql=bool(srv.get("host")), site=site, playbooks=playbooks,
                                   graph_project=graph_project, code_path=code_path)


def _issue_context(issue_id, subject, redmine_url, with_tool):
    link = ("%s/issues/%d" % (redmine_url, issue_id)) if redmine_url else ""
    return ("\n\n---\n[Заявка: #%d%s%s.%s]" % (
        issue_id,
        (" «%s»" % subject) if subject else "",
        (" — %s" % link) if link else "",
        " Содержимое заявки можно посмотреть инструментом get_issue." if with_tool else ""))


_SAFE_NAME_RE = re.compile(r"[^0-9A-Za-zА-Яа-яЁё._-]+")


def _safe_att_name(name, idx):

    base = os.path.basename(str(name or "")).strip()
    base = _SAFE_NAME_RE.sub("_", base)[:80].strip("._") or ("file%d" % idx)
    return base


def _prepare_attachments(attachments):


    disk_files, names, used = [], [], {}
    for i, att in enumerate(attachments or []):
        content_text = att.get("text")
        if content_text is not None:
            data = str(content_text).encode("utf-8", "replace")
        else:
            b64 = att.get("b64")
            if not b64:
                continue
            try:
                data = base64.b64decode(b64)
            except (ValueError, TypeError):
                continue
        fname = _safe_att_name(att.get("name"), i)
        if fname in used:
            used[fname] += 1
            root, ext = os.path.splitext(fname)
            fname = "%s_%d%s" % (root, used[fname], ext)
        else:
            used[fname] = 1
        names.append(fname)
        disk_files.append((fname, data))
    return disk_files, names


def _run_claude(message, issue_id, session_id, cwd, model=None, effort=None, attachments=None,
                draft_pending=False):


    claude_bin = _claude_bin()
    if not shutil.which(claude_bin) and not os.path.isabs(claude_bin):
        return None, "claude CLI не найден (%s)" % claude_bin, None

    disk_files, _names = _prepare_attachments(attachments)

    acc = rmc.resolve_account(_secrets())
    url, key = acc["url"], acc["api_key"]
    mcp_path = None
    draft_tmp = None
    draft_note = None
    attach_dir = None
    out = None


    gdry = bool(core.agent_status().get("dry_run", True))


    if draft_pending:
        mode_note = (
            "\n\nПо этой заявке есть ЧЕРНОВИК разбора, ждущий одобрения инженера. Инструмент "
            "post_private_note работает в режиме ЧЕРНОВИКА: он НЕ публикует в Redmine, а "
            "ПЕРЕЗАПИСЫВАЕТ этот черновик. Если инженер просит переделать/поправить разбор — "
            "вызови post_private_note с ПОЛНЫМ новым текстом (note = разбор + SQL целиком): "
            "черновик обновится, инженер потом опубликует его кнопкой. Сам не публикуешь.")
    else:
        mode_note = (
            "\n\nЧЕРНОВИК: post_private_note НИЧЕГО не публикует — он СОЗДАЁТ черновик разбора, "
            "который инженер увидит карточкой и опубликует кнопкой сам. Поэтому КАЖДЫЙ раз, когда "
            "твой ответ — это разбор заявки (причина, что делать, SQL, вывод), ОБЯЗАТЕЛЬНО вызови "
            "post_private_note с ПОЛНЫМ текстом ответа (note = разбор + SQL целиком), а не просто "
            "напиши его в чат. Если просят «опубликуй» — объясни, что публикует инженер кнопкой, "
            "а ты готовишь черновик. Болтовню и уточняющие вопросы черновиком не оформляй.")
    cmd = [claude_bin, "-p", "--output-format", "json",
           "--permission-mode", "bypassPermissions",
           "--append-system-prompt", SYSTEM_PROMPT + dfl.HUMANIZER_STYLE + mode_note]
    try:
        if url and key:
            sql_env, influx_env = _chat_tool_envs(issue_id, url, key)

            dfd, draft_tmp = tempfile.mkstemp(suffix=".json", prefix="wa_chat_draft_")
            os.close(dfd)
            cfg = dfl.build_mcp_config(url, key, issue_id, [], dry=True, draft_file=draft_tmp,
                                       sql_env=sql_env, influx_env=influx_env)
            fd, mcp_path = tempfile.mkstemp(suffix=".json", prefix="wa_chat_mcp_")
            try:
                os.write(fd, json.dumps(cfg).encode("utf-8"))
            finally:
                os.close(fd)
            os.chmod(mcp_path, 0o600)
            cmd += ["--mcp-config", mcp_path]
        if model:
            cmd += ["--model", model]
        if effort:
            cmd += ["--effort", effort]
        if session_id:
            cmd += ["--resume", session_id]
        env = os.environ.copy()
        env.pop("ANTHROPIC_API_KEY", None)
        env.pop("ANTHROPIC_AUTH_TOKEN", None)

        os.makedirs(cwd, exist_ok=True)
        if disk_files:


            attach_dir = tempfile.mkdtemp(dir=cwd, prefix="_wa_att_")
            for fname, data in disk_files:
                with open(os.path.join(attach_dir, fname), "wb") as f:
                    f.write(data)
            rel = os.path.basename(attach_dir)
            message += ("\n\nК сообщению приложены файлы (посмотри их инструментом Read ЦЕЛИКОМ): "
                        + ", ".join("%s/%s" % (rel, fn) for fn, _ in disk_files))

        try:
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    env=env, cwd=cwd, start_new_session=True, text=True)
        except OSError as e:
            return None, "запуск не удался: %s" % e, draft_note
        try:
            out, err = proc.communicate(input=message, timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except OSError:
                proc.kill()
            proc.communicate()
            return None, "таймаут %d сек" % TIMEOUT, draft_note

        if draft_tmp:
            try:
                with open(draft_tmp, encoding="utf-8") as f:
                    _t = f.read().strip()
                if _t:
                    _d = json.loads(_t)
                    if isinstance(_d, dict) and _d.get("note"):
                        draft_note = _d
            except (OSError, ValueError):
                pass
        if proc.returncode != 0:
            return None, "claude rc=%s (%s)" % (proc.returncode, (err or "").strip()[:200]), draft_note
    except OSError as e:
        return None, "вложения/cwd не записались: %s" % e, draft_note
    finally:
        if mcp_path:
            try:
                os.remove(mcp_path)
            except OSError:
                pass
        if draft_tmp:
            try:
                os.remove(draft_tmp)
            except OSError:
                pass
        if attach_dir:
            shutil.rmtree(attach_dir, ignore_errors=True)
    envelope = cli_json.parse_envelope(out)
    if envelope is None:
        return None, "битый JSON-ответ CLI", draft_note
    if not isinstance(envelope, dict) or envelope.get("is_error"):
        return None, "CLI вернул ошибку: %s" % str(envelope)[:200], draft_note
    return envelope, None, draft_note


@router.get("")
def chats_list():


    feed = core.build_feed(core.ROOT, limit=1000)
    files = _all_chat_files()
    deleted = _load_deleted()
    pend_drafts = drafts.pending_drafts()
    by_id = {}
    for e in feed["tickets"]:
        iid = e.get("issue_id")
        if not iid:
            continue
        ents = by_id.setdefault(iid, {"issue_id": iid, "subject": "", "_ents": []})
        ents["_ents"].append(e)
        if e.get("subject"):
            ents["subject"] = e["subject"]
    items = []
    for iid in set(by_id) | set(files) | set(pend_drafts):
        ents = (by_id.get(iid) or {}).get("_ents", [])
        chat = files.get(iid)
        draft = pend_drafts.get(iid)
        agent_msgs = _agent_messages(ents)
        sid = (chat or {}).get("session_id") or _session_from_entities(ents)
        if not chat and not agent_msgs and not sid and not draft:
            continue
        msgs = agent_msgs + list((chat or {}).get("messages", ()))
        if draft:
            msgs.append(drafts.draft_message(iid, draft))
        msgs.sort(key=lambda m: m.get("ts") or 0)
        last = msgs[-1] if msgs else None
        tomb = deleted.get(str(iid))
        if tomb is not None and ((last or {}).get("ts") or 0) <= tomb:
            continue
        preview = " ".join(((last or {}).get("text") or "").split())[:160]
        items.append({
            "issue_id": iid,
            "subject": (chat or {}).get("subject") or (by_id.get(iid) or {}).get("subject", "")
                       or (draft or {}).get("subject", ""),
            "msgs": len(msgs),
            "preview": preview,
            "last_role": (last or {}).get("role"),
            "ts": (last or {}).get("ts") or 0,
            "at": (last or {}).get("at") or "",
            "has_session": bool(sid),
            "has_draft": bool(draft),
        })
    items.sort(key=lambda x: -(x["ts"] or 0))
    return {"items": items, "redmine_url": feed["redmine_url"]}


@router.get("/{issue_id}")
def chat_history(issue_id: int):

    feed = core.build_feed(core.ROOT, limit=1000)
    ents = _ticket_entities(feed, issue_id)
    chat = _load_chat(issue_id)


    _tail = (chat or {}).get("messages") or []
    if _tail and _tail[-1].get("role") == "user" and _tail[-1].get("pending") \
            and not _is_active(issue_id):
        with _lock(issue_id):
            chat = _load_chat(issue_id) or chat
            _tail = chat.get("messages") or []
            if _tail and _tail[-1].get("role") == "user" and _tail[-1].get("pending") \
                    and not _is_active(issue_id):
                _tail[-1].pop("pending", None)
                _tail.append({"role": "ai", "text": "⚠ ответ прервался (сервер перезапускался). "
                              "Отправь сообщение ещё раз.", "at": _now(),
                              "ts": int(time.time()), "error": True})
                chat["updated_at"] = _now()
                try:
                    _save_chat(issue_id, chat)
                except OSError:
                    pass
    msgs = _agent_messages(ents) + list((chat or {}).get("messages", ()))


    draft = drafts.load_draft(issue_id)
    if draft and draft.get("status") == "pending":
        msgs.append(drafts.draft_message(issue_id, draft))
    else:
        draft = None
    msgs.sort(key=lambda m: m.get("ts") or 0)
    subject = ((chat or {}).get("subject")
               or next((e["subject"] for e in ents if e.get("subject")), "")
               or (draft or {}).get("subject", ""))
    return {"issue_id": issue_id, "subject": subject,
            "session_id": ((chat or {}).get("session_id") or _session_from_entities(ents)
                           or (draft or {}).get("session_id")),
            "messages": msgs, "redmine_url": feed["redmine_url"]}


@router.delete("/{issue_id}")
def chat_delete(issue_id: int):


    removed = {"chat": False, "session": False}
    with _lock(issue_id):
        chat = _load_chat(issue_id)
        sid = (chat or {}).get("session_id")
        if not sid:
            try:
                ents = _ticket_entities(core.build_feed(core.ROOT, limit=1000), issue_id)
                sid = _session_from_entities(ents)
            except Exception:
                sid = None

        if sid:
            for path in glob.glob(os.path.join(CLAUDE_PROJECTS, "*", sid + ".jsonl")):
                try:
                    os.remove(path); removed["session"] = True
                except OSError:
                    pass

        try:
            os.remove(_chat_path(issue_id)); removed["chat"] = True
        except OSError:
            pass

        dele = _load_deleted(); dele[str(issue_id)] = time.time(); _save_deleted(dele)
    return {"ok": True, "removed": removed, "issue_id": issue_id}


def _answer_worker(issue_id, subject, sid, text, redmine_url, model, effort, atts,
                   draft_pending=False):


    try:
        envelope = err = draft_note = None
        run_seconds = 0.0
        try:
            cwd = CHAT_CWD
            if sid:
                cwd, found = _session_cwd(sid)
                if not found:
                    sid, cwd = None, CHAT_CWD
            _acc = rmc.resolve_account(_secrets())
            with_tool = bool(_acc["url"] and _acc["api_key"])
            full = text + _issue_context(issue_id, subject, redmine_url, with_tool)
            _t0 = time.monotonic()
            envelope, err, draft_note = _run_claude(full, issue_id, sid, cwd,
                                                    model=model, effort=effort, attachments=atts,
                                                    draft_pending=draft_pending)
            run_seconds = time.monotonic() - _t0
        except Exception as e:
            envelope, err, draft_note = None, "внутренняя ошибка воркера: %s" % e, None

        with _lock(issue_id):
            chat = _load_chat(issue_id) or {"issue_id": issue_id, "subject": subject,
                                            "session_id": None, "created_at": _now(),
                                            "messages": []}
            ms = chat.setdefault("messages", [])
            if ms and ms[-1].get("role") == "user" and ms[-1].get("pending"):
                ms[-1].pop("pending", None)
            if err:
                ms.append({"role": "ai", "text": "⚠ " + err, "at": _now(),
                           "ts": int(time.time()), "error": True})


                if draft_note and (draft_note.get("note") or "").strip():
                    upd, created = drafts.upsert_draft_from_chat(
                        issue_id, draft_note["note"], subject=subject,
                        analysis_seconds=run_seconds)
                    if upd:
                        ms.append({"role": "ai",
                                   "text": ("✎ Прогон оборвался, но разбор модель успела "
                                            "переписать — черновик %s. Проверь его."
                                            % ("создан" if created else "обновлён")),
                                   "at": _now(), "ts": int(time.time())})
            else:
                answer = (envelope.get("result") or "").strip() or "(пустой ответ)"
                chat["session_id"] = envelope.get("session_id") or chat.get("session_id") or sid
                ms.append({"role": "ai", "text": answer, "at": _now(), "ts": int(time.time())})


                note_txt = (draft_note or {}).get("note") or ""
                from_tool = bool(note_txt.strip())
                if not from_tool and len(answer) >= _AUTODRAFT_MIN_CHARS:
                    cur = drafts.load_draft(issue_id)
                    if not (cur and cur.get("status") == "pending"):
                        note_txt = answer
                if note_txt.strip():
                    upd, created = drafts.upsert_draft_from_chat(
                        issue_id, note_txt, subject=subject,
                        session_id=envelope.get("session_id"), analysis_seconds=run_seconds)
                    if upd:
                        ms.append({"role": "ai",
                                   "text": ("✎ Черновик разбора создан — проверь и нажми "
                                            "«Опубликовать»." if created else
                                            "✎ Черновик разбора обновлён — нажми «Опубликовать», "
                                            "чтобы запостить новую версию."),
                                   "at": _now(), "ts": int(time.time())})
            chat["updated_at"] = _now()
            try:
                _save_chat(issue_id, chat)
            except OSError:
                pass
    finally:
        with _active_guard:
            _active.discard(issue_id)


def _decide_draft(issue_id, subject, text, draft, approve):


    with _lock(issue_id):
        chat = _load_chat(issue_id) or {"issue_id": issue_id, "subject": "",
                                        "session_id": None, "created_at": _now(),
                                        "messages": []}
        subject = chat.get("subject") or subject or draft.get("subject") or ""
        chat.setdefault("messages", []).append(
            {"role": "user", "text": text, "at": _now(), "ts": int(time.time())})
        if approve:
            res = drafts.publish_draft(issue_id)
            reply, ok = res["text"], res["ok"]
            draft = drafts.load_draft(issue_id) or draft
        else:
            draft["status"], draft["decided_at"] = "declined", _now()
            try:
                drafts.save_draft(issue_id, draft)
                drafts.clean_shots(issue_id)
                reply, ok = "Черновик отклонён ✕ — публиковать не буду.", True
            except OSError as e:
                reply, ok = "⚠ не смог пометить черновик отклонённым: %s" % e, False
        amsg = {"role": "ai", "text": reply, "at": _now(), "ts": int(time.time())}
        if not ok:
            amsg["error"] = True
        chat["messages"].append(amsg)
        chat.update(subject=subject, updated_at=_now())
        try:
            _save_chat(issue_id, chat)
        except OSError:
            pass
    return {"ok": ok, "draft_status": draft.get("status"), "text": reply}


def append_ai_note(issue_id, text, error=False, subject=""):


    with _lock(issue_id):
        chat = _load_chat(issue_id) or {"issue_id": issue_id, "subject": subject or "",
                                        "session_id": None, "created_at": _now(),
                                        "messages": []}
        if subject and not chat.get("subject"):
            chat["subject"] = subject
        msg = {"role": "ai", "text": text, "at": _now(), "ts": int(time.time())}
        if error:
            msg["error"] = True
        chat.setdefault("messages", []).append(msg)
        chat["updated_at"] = _now()
        try:
            _save_chat(issue_id, chat)
        except OSError:
            pass


@router.post("/{issue_id}")
def chat_send(issue_id: int, body: ChatSendRequest):


    text = body.message.strip()
    if not text and not body.attachments and not body.std_prompt:
        return {"ok": False, "error": "пустое сообщение"}
    if not text and body.attachments:
        text = "Посмотри приложенный файл."


    if not body.attachments:
        _draft = drafts.load_draft(issue_id)
        if _draft and _draft.get("status") == "pending" and drafts.is_decline(text):
            return _decide_draft(issue_id, body.subject, text, _draft, approve=False)
    atts = [a.dict() for a in body.attachments] if body.attachments else None
    _df, att_names = _prepare_attachments(atts)
    if _is_active(issue_id):
        return {"ok": False, "error": "агент ещё отвечает на предыдущее сообщение — дождись ответа"}
    with _lock(issue_id):


        if _is_active(issue_id):
            return {"ok": False,
                    "error": "агент ещё отвечает на предыдущее сообщение — дождись ответа"}
        dele = _load_deleted()
        if dele.pop(str(issue_id), None) is not None:
            _save_deleted(dele)
        feed = core.build_feed(core.ROOT, limit=1000)
        ents = _ticket_entities(feed, issue_id)
        chat = _load_chat(issue_id) or {"issue_id": issue_id, "subject": "",
                                        "session_id": None, "created_at": _now(),
                                        "messages": []}
        subject = (chat.get("subject") or body.subject
                   or next((e["subject"] for e in ents if e.get("subject")), ""))


        sid = chat.get("session_id") or _session_from_entities(ents)
        if not sid:
            _d = drafts.load_draft(issue_id)
            if _d and _d.get("status") == "pending":
                sid = _d.get("session_id")


        _ms = chat.get("messages") or []
        if _ms and _ms[-1].get("role") == "user" and _ms[-1].get("pending"):
            _ms[-1].pop("pending", None)
            _ms.append({"role": "ai", "text": "⚠ предыдущий запрос прервался (сервер/сеть). "
                        "Ответа не было.", "at": _now(), "ts": int(time.time()), "error": True})


        no_msgs = not any(m.get("role") == "user" for m in (chat.get("messages") or []))
        analyzed = bool(_agent_messages(ents)) or drafts.load_draft(issue_id) is not None
        first_msg = no_msgs and not analyzed
        std = ""
        if body.std_prompt or first_msg:
            try:
                std = standard_prompt(issue_id, subject, feed.get("redmine_url"),
                                      rmc.resolve_account(_secrets()).get("api_key"))
            except Exception as e:
                std = ""
                print("chat #%s: стандартный промпт не собрался (%s)" % (issue_id, e))
        send_text = ("%s\n\n%s" % (text, std)).strip() if std else text
        if not text:
            text = "Разбери заявку по стандартному промпту."


        now, ts = _now(), int(time.time())
        umsg = {"role": "user", "text": text, "at": now, "ts": ts, "pending": True}
        if std:
            umsg["std"] = True
        if att_names:
            umsg["att"] = att_names
        chat.setdefault("messages", []).append(umsg)
        chat.update(subject=subject, updated_at=now)
        try:
            _save_chat(issue_id, chat)
        except OSError as e:
            return {"ok": False, "error": "история не записалась: %s" % e}
        with _active_guard:
            _active.add(issue_id)


    _pd = drafts.load_draft(issue_id)
    draft_pending = bool(_pd and _pd.get("status") == "pending")
    threading.Thread(target=_answer_worker, daemon=True,
                     args=(issue_id, subject, sid, send_text, feed["redmine_url"],
                           body.model, body.effort, atts, draft_pending)).start()
    return {"ok": True, "queued": True, "session_id": sid}
