# -*- coding: utf-8 -*-


import json
import os
import shutil
import signal
import subprocess
import threading
import time

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from .. import core, drafts
from agent import cli_json
from agent import humanizer as hz
from . import chats

router = APIRouter(prefix="/api/drafts")


_active_guard = threading.Lock()
_active = set()


def _is_active(issue_id):
    with _active_guard:
        return issue_id in _active


def _cfg():


    return core.load_config().get("humanizer") or {}


def _abs(rel):
    return rel if os.path.isabs(rel) else os.path.join(core.ROOT, rel)


def _read_profile(cfg):

    rel = cfg.get("profile_file") or "documentation/style/maintainer-style-profile.md"
    try:
        with open(_abs(rel), encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def _read_examples(cfg):


    rel = cfg.get("examples_file") or "state/style_corpus/examples.jsonl"
    try:
        max_ex = int(cfg.get("max_examples") or 0)
    except (TypeError, ValueError):
        max_ex = 0
    out = []
    try:
        with open(_abs(rel), encoding="utf-8") as f:
            for line in f:
                if max_ex and len(out) >= max_ex:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                notes = obj.get("notes") if isinstance(obj, dict) else None
                if isinstance(notes, str) and notes.strip():
                    out.append(notes.strip())
    except OSError:
        return []
    return out


def _claude_bin():
    return chats._claude_bin()


def _run_model(prompt, model, effort, timeout):


    claude_bin = _claude_bin()
    if not shutil.which(claude_bin) and not os.path.isabs(claude_bin):
        return None, "claude CLI не найден (%s)" % claude_bin


    cmd = [claude_bin, "-p", "--output-format", "json", "--strict-mcp-config"]
    if model:
        cmd += ["--model", str(model)]
    if effort:
        cmd += ["--effort", str(effort)]
    env = os.environ.copy()
    env.pop("ANTHROPIC_API_KEY", None)
    env.pop("ANTHROPIC_AUTH_TOKEN", None)
    try:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, env=env, start_new_session=True, text=True)
    except OSError as e:
        return None, "запуск не удался: %s" % e
    try:
        out, err = proc.communicate(input=prompt, timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except OSError:
            proc.kill()
        proc.communicate()
        return None, "таймаут %d сек" % timeout
    if proc.returncode != 0:
        return None, "claude rc=%s (%s)" % (proc.returncode, (err or "").strip()[:200])
    envelope = cli_json.parse_envelope(out)
    if envelope is None:
        return None, "битый JSON-ответ CLI"
    if not isinstance(envelope, dict) or envelope.get("is_error"):
        return None, "CLI вернул ошибку: %s" % str(envelope)[:200]
    result = envelope.get("result")
    if not isinstance(result, str) or not result.strip():
        return None, "пустой ответ модели"
    return result, None


def _lint_remaining(marks):


    out = []
    if marks.get("cliches"):
        out.append("клише (%s)" % ", ".join(marks["cliches"]))
    if marks.get("template_headers"):
        out.append("шаблонные подзаголовки-ярлыки (%d)" % marks["template_headers"])
    if marks.get("bold_runs"):
        out.append("markdown-жирный/курсив (%d)" % marks["bold_runs"])
    if marks.get("dashes"):
        out.append("длинные тире (%d)" % marks["dashes"])
    if marks.get("arrows"):
        out.append("стрелки (%d)" % marks["arrows"])
    if marks.get("rule_of_three"):
        out.append("«правило трёх» (%d)" % marks["rule_of_three"])
    return out


def _facts_reason(facts):

    parts = []
    miss = facts.get("missing") or {}
    if miss:
        parts.append("пропали факты (%s)" % "; ".join(
            "%s: %s" % (cat, ", ".join(vals)) for cat, vals in miss.items()))
    added = facts.get("added_numbers") or []
    if added:
        parts.append("появились новые числа (%s)" % ", ".join(added))
    return "; ".join(parts) or "искажены факты/числа"


def _facts_feedback(facts):


    lost = []
    for _cat, vals in (facts.get("missing") or {}).items():
        lost.extend(vals)
    added = facts.get("added_numbers") or []
    msg = ("КРИТИЧНО: в прошлый раз ты ВЫРОНИЛ или изменил факты, которые обязан сохранять "
           "СИМВОЛ-В-СИМВОЛ (имена таблиц/полей КАПСОМ, номера, коды): "
           + ", ".join(lost) + ". Впиши их обратно ТОЧЬ-В-ТОЧЬ на свои места, не перефразируй и "
           "не выкидывай. Стиль сохрани, но эти токены — как есть.")
    if added:
        msg += (" Ещё убери числа, которых НЕ было в оригинале: " + ", ".join(added) + ".")
    return msg


def _notify_chat(issue_id, text, subject=""):


    with chats._lock(issue_id):
        chat = chats._load_chat(issue_id) or {"issue_id": issue_id, "subject": subject,
                                              "session_id": None, "created_at": chats._now(),
                                              "messages": []}
        chat.setdefault("messages", []).append(
            {"role": "agent", "text": text, "at": chats._now(), "ts": int(time.time())})
        chat["updated_at"] = chats._now()
        try:
            chats._save_chat(issue_id, chat)
        except OSError:
            pass


def _fail(issue_id, reason, attempts):

    d = drafts.load_draft(issue_id)
    subject = (d or {}).get("subject") or ""
    if d is not None:
        d["humanize"] = {"status": "error", "at": chats._now(),
                         "model": _cfg().get("model") or "sonnet",
                         "attempts": attempts, "error": reason}
        try:
            drafts.save_draft(issue_id, d)
        except OSError:
            pass
    _notify_chat(issue_id, "⚠ Humanize не прошёл: %s. Черновик оставлен как есть." % reason,
                 subject=subject)


def _success(issue_id, orig_analysis, orig_comment, restored, cand_frozen, model, attempts, src):


    d = drafts.load_draft(issue_id)
    if d is None:
        return _fail(issue_id, "черновик по заявке пропал во время переписывания", attempts)


    if (d.get("analysis") or "") != (orig_analysis or ""):
        return _fail(issue_id, "черновик изменился, пока шло переписывание (правка из чата) — "
                               "результат humanize отброшен, нажми Humanize ещё раз", attempts)
    if d.get("analysis_original") is None:
        d["analysis_original"] = orig_analysis
        d["comment_original"] = orig_comment
    d["analysis"] = restored
    d["comment"] = restored
    d["humanize"] = {"status": "done", "at": chats._now(), "model": model,
                     "attempts": attempts, "lint": hz.lint_report(cand_frozen),
                     "flags": hz.content_flags(src)}
    try:
        drafts.save_draft(issue_id, d)
    except OSError:
        _fail(issue_id, "не удалось сохранить переписанный черновик (диск)", attempts)


def _humanize_worker(issue_id):


    attempts = 0
    try:
        draft = drafts.load_draft(issue_id)
        if not draft:
            _fail(issue_id, "черновик по заявке не найден", attempts)
            return

        if draft.get("analysis_original") is not None:
            src = draft.get("analysis_original") or ""
        else:
            src = draft.get("analysis") or ""
        orig_analysis = draft.get("analysis") or ""
        orig_comment = draft.get("comment") or ""


        frozen, cmap = hz.freeze_code(src)


        cfg = _cfg()
        model = cfg.get("model") or "sonnet"
        effort = cfg.get("effort") or "medium"
        try:
            timeout = int(cfg.get("timeout") or 300)
        except (TypeError, ValueError):
            timeout = 300
        try:
            max_retries = max(0, int(cfg.get("lint_max_retries") or 2))
        except (TypeError, ValueError):
            max_retries = 0
        try:
            brevity = float(cfg.get("brevity") or 0.85)
        except (TypeError, ValueError):
            brevity = 0.0
        profile_text = _read_profile(cfg)
        examples = _read_examples(cfg)


        base_prompt = hz.build_humanize_prompt(frozen, profile_text, examples)
        base_prompt += ("\n\nВерни ТОЛЬКО итоговый переписанный текст, без преамбулы и пояснений; "
                        "плейсхолдеры вида ⟦CODE_1⟧ сохрани дословно на своих местах.")

        feedback = ""
        while True:
            attempts += 1
            prompt = base_prompt + (("\n\n" + feedback) if feedback else "")

            result, err = _run_model(prompt, model, effort, timeout)
            if err:
                _fail(issue_id, "модель не переписала текст: %s" % err, attempts)
                return
            cand_frozen = result.strip()

            cand_frozen, _fixes = hz.deterministic_fix(cand_frozen)


            facts = hz.check_facts(frozen, cand_frozen)
            if not facts["ok"]:
                if attempts <= max_retries:
                    feedback = _facts_feedback(facts)
                    continue
                _fail(issue_id, _facts_reason(facts), attempts)
                return

            restored, ok, missing = hz.restore_code(cand_frozen, cmap)
            if not ok:
                _fail(issue_id, "модель повредила блок(и) кода: %s" % ", ".join(missing), attempts)
                return


            remaining = _lint_remaining(hz.ai_marks(cand_frozen))
            too_long = bool(brevity) and len(cand_frozen) > len(frozen) * brevity
            if not remaining and not too_long:
                _success(issue_id, orig_analysis, orig_comment, restored, cand_frozen,
                         model, attempts, src)
                return
            if attempts <= max_retries:
                fb = []
                if remaining:
                    fb.append("остались нежелательные элементы: " + "; ".join(remaining) + " — убери их")
                if too_long:
                    fb.append("текст всё ещё длинный — СОКРАТИ заметно: режь воду, повторы, "
                              "преамбулы, разжёвывание; оставь только суть, факты и SQL (факты НЕ терять)")
                feedback = ". ".join(fb) + ". Перепиши ещё раз, соблюдая все правила."
                continue

            if remaining:
                _fail(issue_id, "не удалось убрать ИИ-марки за %d попыт(ки): %s"
                      % (attempts, "; ".join(remaining)), attempts)
                return
            _success(issue_id, orig_analysis, orig_comment, restored, cand_frozen,
                     model, attempts, src)
            return
    except Exception as e:
        try:
            _fail(issue_id, "внутренняя ошибка воркера: %s" % e, attempts)
        except Exception:
            pass
    finally:
        with _active_guard:
            _active.discard(issue_id)


@router.post("/{issue_id}/humanize")
def humanize_start(issue_id: int):


    if not _cfg().get("enabled", True):
        return JSONResponse({"ok": False, "reason": "disabled",
                             "message": "humanizer выключен в конфиге (humanizer.enabled=false)"},
                            status_code=400)
    draft = drafts.load_draft(issue_id)
    if not draft:
        return JSONResponse({"ok": False, "reason": "no_draft"}, status_code=404)
    if draft.get("status") != "pending":
        return JSONResponse({"ok": False, "reason": "not_pending",
                             "status": draft.get("status")}, status_code=400)
    with _active_guard:
        if issue_id in _active:
            return JSONResponse({"ok": False, "reason": "already_running"}, status_code=409)
        _active.add(issue_id)
    draft["humanize"] = {"status": "running", "at": chats._now()}
    try:
        drafts.save_draft(issue_id, draft)
    except OSError as e:
        with _active_guard:
            _active.discard(issue_id)
        return JSONResponse({"ok": False, "reason": "save_failed", "error": str(e)},
                            status_code=500)
    threading.Thread(target=_humanize_worker, daemon=True, args=(issue_id,)).start()
    return {"ok": True, "status": "running"}


@router.post("/{issue_id}/humanize/revert")
def humanize_revert(issue_id: int):


    draft = drafts.load_draft(issue_id)
    if not draft:
        return JSONResponse({"ok": False, "reason": "no_draft"}, status_code=404)
    if draft.get("analysis_original") is None:
        return {"ok": False, "reason": "nothing_to_revert"}
    draft["analysis"] = draft.get("analysis_original")
    draft["comment"] = draft.get("comment_original")

    draft.pop("analysis_original", None)
    draft.pop("comment_original", None)
    draft["humanize"] = {"status": "idle", "at": chats._now()}
    try:
        drafts.save_draft(issue_id, draft)
    except OSError as e:
        return JSONResponse({"ok": False, "reason": "save_failed", "error": str(e)},
                            status_code=500)
    return {"ok": True}
