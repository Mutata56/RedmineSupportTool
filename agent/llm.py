# -*- coding: utf-8 -*-


import json
import re
import urllib.request

API_URL = "https://api.anthropic.com/v1/messages"

SYSTEM = (
    "Ты маршрутизатор алертов техподдержки WMS (Infor SCE). По письму (тема + текст) "
    "определи, к какому проекту Redmine из предложенного списка оно относится: ищи имя "
    "сервера, РЦ или клиента в тексте и сопоставь с названием проекта. "
    "Отвечай ТОЛЬКО JSON без пояснений: "
    '{"project_id": <число из списка или null>, "server": "<имя сервера из письма или null>", '
    '"confidence": "high" или "low"}. '
    "Если однозначного соответствия нет - project_id: null. Никогда не выдумывай id, "
    "которых нет в списке."
)


def classify_server(api_key, model, projects, subject, body, timeout=30):


    plist = "\n".join(f"{pid}: {name}" for pid, name in sorted(projects.items()))
    user = (f"Проекты (id: название):\n{plist}\n\n"
            f"Письмо.\nТема: {subject}\nТекст:\n{(body or '')[:2000]}")
    payload = {
        "model": model,
        "max_tokens": 150,
        "system": SYSTEM,
        "messages": [{"role": "user", "content": user}],
    }
    req = urllib.request.Request(API_URL, data=json.dumps(payload).encode("utf-8"), headers={
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.load(r)
    text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        out = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    pid = out.get("project_id")
    if not isinstance(pid, int) or out.get("confidence") != "high":
        return None
    return {"project_id": pid, "server": out.get("server")}
