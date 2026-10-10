# -*- coding: utf-8 -*-


import json
import logging
import os
import re
import shutil
import signal
import subprocess
import tempfile

from . import cli_json

log = logging.getLogger("agent.llm")


def _log_usage(kind, envelope):


    if not isinstance(envelope, dict):
        return
    u = envelope.get("usage") or {}
    log.info("%s: %s мс, токены in=%s out=%s (cache read=%s), cost=%s", kind,
             envelope.get("duration_ms"), u.get("input_tokens"), u.get("output_tokens"),
             u.get("cache_read_input_tokens"), envelope.get("total_cost_usd"))


_DENY_TOOLS = "Bash,Edit,Write,Read,Glob,Grep,WebSearch,WebFetch,Task,NotebookEdit,TodoWrite"

_INSTRUCTION = (
    "Ты — маршрутизатор алертов техподдержки WMS (Infor SCE). По письму (тема + текст) "
    "выбери проект Redmine из списка ниже: ищи имя сервера, РЦ или клиента в тексте и "
    "сопоставь с названием проекта.\n"
    "Верни СТРОГО JSON одной строкой, без пояснений и без markdown-ограждений:\n"
    '{"project_id": <число из списка или null>, "server": "<имя сервера из письма или null>", '
    '"confidence": "high" или "low"}\n'
    "Если однозначного соответствия нет — project_id: null, confidence: \"low\". "
    "НИКОГДА не выдумывай id, которого нет в списке. Инструменты не используй — просто ответь JSON."
)


def _build_prompt(projects, subject, body):
    plist = "\n".join("%s: %s" % (pid, name) for pid, name in sorted(projects.items()))
    return ("%s\n\nПроекты (id: название):\n%s\n\nПисьмо.\nТема: %s\nТекст:\n%s"
            % (_INSTRUCTION, plist, subject or "", (body or "")[:2000]))


def _run(claude_bin, prompt, model, effort, timeout):

    cmd = [
        claude_bin, "-p", prompt,
        "--output-format", "json",
        "--model", model,
        "--effort", effort,
        "--disallowedTools", _DENY_TOOLS,


        "--strict-mcp-config",
        "--permission-mode", "default",
    ]

    env = os.environ.copy()
    env.pop("ANTHROPIC_API_KEY", None)
    env.pop("ANTHROPIC_AUTH_TOKEN", None)
    cwd = tempfile.mkdtemp(prefix="wa_route_")
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=env, cwd=cwd, start_new_session=True, text=True)
        try:
            out, err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except OSError:
                proc.kill()
            proc.communicate()
            return None, "таймаут %.0fс" % timeout
        if proc.returncode != 0:
            return None, "claude rc=%s (%s)" % (proc.returncode, (err or "").strip()[:120])
        return out, None
    finally:
        shutil.rmtree(cwd, ignore_errors=True)


def _extract_json(text):

    return cli_json.extract_inner_json(text)


def classify_server(projects, subject, body, model="sonnet", effort="low",
                    timeout=25, claude_bin="claude"):


    if not shutil.which(claude_bin) and not os.path.isabs(claude_bin):
        return None
    out, reason = _run(claude_bin, _build_prompt(projects, subject, body),
                       model, effort, timeout)
    if out is None:
        return None
    envelope = cli_json.parse_envelope(out)
    if not envelope:
        return None
    _log_usage("роутинг-письма", envelope)
    if envelope.get("is_error"):
        return None
    session_id = envelope.get("session_id")
    verdict = _extract_json(envelope.get("result", ""))
    if not verdict:
        return None
    pid = verdict.get("project_id")
    if not isinstance(pid, int) or verdict.get("confidence") != "high":
        return None
    return {"project_id": pid, "server": verdict.get("server"), "session_id": session_id}


_ANALYSIS_INSTRUCTION = (
    "Ты — инженер поддержки WMS (Infor SCE). Напиши ПРИВАТНЫЙ комментарий в заявку Redmine "
    "для дежурного, который может быть новичком. Объясняй так, чтобы понял даже человек без "
    "глубокого контекста, расшифровывай термины.\n\n"
    "Формат — РОВНО три блока в разметке Redmine textile, коротко и по делу:\n\n"
    "h3. Что это за алерт\n"
    "2–4 предложения простыми словами: что за таблица/метрика/служба, что вообще значит этот "
    "алерт и почему он прилетел. Расшифруй термины (например: что такое «обрезка таблицы», "
    "tempdb, лог БД, транзакция) — как будто объясняешь стажёру.\n\n"
    "h3. Что показал анализ\n"
    "Своими словами перескажи факты из блока ДАННЫЕ: что происходит в норме (годовой профиль) и "
    "что не так сейчас — почему это считается аномалией. Если в ДАННЫХ есть свежий ряд значений "
    "из InfluxDB — ОБЯЗАТЕЛЬНО опирайся на него: назови текущее значение, скажи растёт метрика "
    "или уже снижается и насколько это выше нормы. Без воды.\n\n"
    "h3. Что делать\n"
    "Пронумерованный список конкретных шагов для дежурного, по порядку и простыми словами: что "
    "проверить, чего дождаться, кому эскалировать. SQL-запросы НЕ пиши и не придумывай — готовые "
    "диагностические запросы дежурному приложат отдельным блоком после твоего разбора. Последним "
    "пунктом: пока причина не ясна или метрика не вернулась в норму — заявку НЕ закрывать.\n\n"
    "Правила: только по-русски; НИЧЕГО не выдумывай сверх блока ДАННЫЕ — если чего-то не знаешь, "
    "прямо скажи «нужно проверить вручную»; инструменты не используй; без markdown-ограждений (```).\n\n"
    "САМОЙ ПОСЛЕДНЕЙ строкой отдельно напиши служебную пометку:\n"
    "CONFIDENCE: high  (если данных достаточно и разбор надёжен)\n"
    "CONFIDENCE: low   (если данных мало / аномалия непонятна / ты гадаешь)\n"
    "Оценивай честно - при low твой разбор НЕ уйдёт в заявку (его посмотрит человек в логах), "
    "это нормальный исход. Пометка в комментарий не попадёт."
)


def _build_analysis_prompt(context):
    return "%s\n\nДАННЫЕ:\n%s" % (_ANALYSIS_INSTRUCTION, context)


def analyze(context, model="sonnet", effort="medium", timeout=90, claude_bin="claude"):


    if not context:
        return None
    if not shutil.which(claude_bin) and not os.path.isabs(claude_bin):
        return None
    out, reason = _run(claude_bin, _build_analysis_prompt(context), model, effort, timeout)
    if out is None:
        return None
    envelope = cli_json.parse_envelope(out)
    if not envelope:
        return None
    _log_usage("разбор-алерта", envelope)
    if envelope.get("is_error"):
        return None
    text = (envelope.get("result") or "").strip()
    if not text:
        return None
    conf = None
    m = re.search(r"CONFIDENCE\s*:\s*(high|low)\W*$", text, re.I)
    if m:
        conf = m.group(1).lower()
        text = text[:m.start()].rstrip()
    if not text:
        return None
    return {"text": text, "confidence": conf, "session_id": envelope.get("session_id")}
