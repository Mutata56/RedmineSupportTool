# -*- coding: utf-8 -*-


import re

__all__ = (
    "PLACEHOLDER_RE", "AI_CLICHES", "FACT_CATEGORIES", "IDENT_STOPWORDS",
    "freeze_code", "restore_code",
    "extract_facts", "check_facts",
    "ai_marks", "deterministic_fix", "lint_report",
    "build_humanize_prompt",
)


_PH_OPEN = "⟦"
_PH_CLOSE = "⟧"
PLACEHOLDER_RE = re.compile(_PH_OPEN + r"CODE_\d+" + _PH_CLOSE)


def _placeholder(n):
    return "%sCODE_%d%s" % (_PH_OPEN, n, _PH_CLOSE)


_CODE_RE = re.compile(
    r"```.*?```"
    r"|<pre\b[^>]*>.*?</pre>"
    r"|<code\b[^>]*>.*?</code>",
    re.DOTALL | re.IGNORECASE,
)


_BLOCK_SEP = re.compile(r"(\n[ \t]*\n)")
_SQL_STMT_KW = re.compile(r"^\s*(SELECT|INSERT|UPDATE|DELETE|WITH|MERGE)\b", re.I)
_SQL_STRUCT = re.compile(r"\b(FROM|WHERE|VALUES|SET|INTO|JOIN)\b", re.I)


def _looks_like_sql_block(block):


    lines = [ln for ln in block.split("\n") if ln.strip()]
    if not lines:
        return False
    first = next((ln for ln in lines if not ln.strip().startswith("--")), "")
    if not _SQL_STMT_KW.match(first):
        return False
    return bool(_SQL_STRUCT.search(" ".join(lines)))


def freeze_code(text):


    if not isinstance(text, str):
        return text, {}
    code_map = {}
    counter = [0]

    def _repl(m):
        counter[0] += 1
        key = _placeholder(counter[0])
        code_map[key] = m.group(0)
        return key

    frozen = _CODE_RE.sub(_repl, text)


    segs = _BLOCK_SEP.split(frozen)
    for i, seg in enumerate(segs):
        if i % 2 == 1:
            continue
        if _PH_OPEN in seg:
            continue
        if _looks_like_sql_block(seg):
            counter[0] += 1
            key = _placeholder(counter[0])
            code_map[key] = seg
            segs[i] = key
    frozen = "".join(segs)
    return frozen, code_map


def restore_code(text, code_map):


    if not isinstance(text, str):
        text = "" if text is None else str(text)
    if not isinstance(code_map, dict):
        return text, False, []
    missing = []
    restored = text
    for key, original in code_map.items():
        if key in restored:
            restored = restored.replace(key, original)
        else:
            missing.append(key)
    return restored, (not missing), missing


FACT_CATEGORIES = ("numbers", "issue_refs", "idents", "codes", "ips")


_NUM_RE = re.compile(r"\d{2,}")

_ISSUE_RE = re.compile(r"#\d+")


_IDENT_RE = re.compile(r"\b[A-Z][A-Z0-9_]{2,}\b")

_CODE_TOKEN_RES = (
    re.compile(r"\b[A-Za-z]{2,}-\d{2,}\b"),
    re.compile(r"\bwmwhse\d+\b", re.IGNORECASE),
    re.compile(r"\b[Mm]_\d{3,}\b"),
)

_IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


IDENT_STOPWORDS = frozenset({
    "SQL", "DB", "ERP", "WMS", "RF", "PTL", "ID", "DBA", "MSK", "UTC",
    "CPU", "OS", "API", "URL", "HTTP", "HTTPS", "JMX", "IP", "TCP", "UDP",
    "PDF", "CSV", "JSON", "XML", "HTML", "SKU", "OK", "UI", "UX", "DNS",
    "VPN", "RAM", "SSD", "HDD", "GUI", "CLI", "REST", "IMAP", "SMTP",


    "SELECT", "FROM", "WHERE", "UPDATE", "INSERT", "DELETE", "JOIN", "GROUP",
    "ORDER", "INTO", "VALUES", "SET", "TOP", "AND", "OR", "NOT", "NULL",
    "LEFT", "RIGHT", "INNER", "OUTER", "ON", "AS", "BY", "COUNT", "SUM",
    "EXEC", "TRUNCATE", "ALTER", "CREATE", "DROP", "TABLE", "INDEX", "VIEW",
})


def extract_facts(text):


    facts = {cat: set() for cat in FACT_CATEGORIES}
    if not isinstance(text, str):
        return facts

    text = PLACEHOLDER_RE.sub(" ", text)

    facts["numbers"].update(_NUM_RE.findall(text))
    facts["issue_refs"].update(_ISSUE_RE.findall(text))
    for w in _IDENT_RE.findall(text):
        if w not in IDENT_STOPWORDS:
            facts["idents"].add(w)
    for rx in _CODE_TOKEN_RES:
        facts["codes"].update(rx.findall(text))
    facts["ips"].update(_IP_RE.findall(text))
    return facts


def check_facts(original_text, candidate_text):


    orig = extract_facts(original_text)
    cand = extract_facts(candidate_text)
    missing = {}
    for cat in FACT_CATEGORIES:
        gone = orig[cat] - cand[cat]
        if gone:
            missing[cat] = sorted(gone)
    added_numbers = sorted(cand["numbers"] - orig["numbers"])
    ok = (not missing) and (not added_numbers)
    return {"ok": ok, "missing": missing, "added_numbers": added_numbers}


AI_CLICHES = (

    "более того",
    "стоит отметить",
    "важно отметить",
    "следует отметить",
    "необходимо отметить",
    "хотелось бы отметить",
    "стоит подчеркнуть",
    "следует подчеркнуть",
    "таким образом",
    "в целом",
    "в конечном счёте",
    "в конечном счете",
    "в конечном итоге",
    "играет ключевую роль",
    "играет важную роль",
    "играет значительную роль",
    "представляет собой",
    "является ключевым",
    "является важной частью",
    "комплексный подход",
    "комплексный",

    "не только",
    "не просто",

    "отличный вопрос",
    "хороший вопрос",
    "прекрасный вопрос",
    "надеюсь, это поможет",
    "надеюсь это поможет",
    "надеюсь, поможет",
    "если что, обращайтесь",
    "обращайтесь, если",
    "буду рад помочь",
    "рад помочь",
    "с удовольствием помогу",
    "вы абсолютно правы",
    "вы правы",

    "давайте разберёмся",
    "давайте разберемся",
    "давайте рассмотрим",
    "давайте посмотрим",
    "стоит учитывать",
    "важно понимать",
    "важно учитывать",
    "необходимо понимать",
    "было выявлено",
    "было принято решение",
    "в современном мире",
    "на сегодняшний день",
    "в данном контексте",
    "в рамках данной",

    "delve",
    "moreover",
    "furthermore",
    "in conclusion",
    "it is important to note",
    "it's important to note",
    "a testament to",
    "plays a crucial role",
    "plays a key role",
    "plays a vital role",
    "plays a pivotal role",
    "at its core",
    "let's dive in",
    "let's dive into",
    "let's explore",
    "in the realm of",
    "when it comes to",
    "seamless",
)


_EM_DASH = "—"
_EN_DASH = "–"
_DASH_RE = re.compile(r"[—–]")

_ARROW_RE = re.compile(r"→|←|⇒|->")


_EMOJI_RANGES = (
    (0x1F300, 0x1F5FF),
    (0x1F600, 0x1F64F),
    (0x1F680, 0x1F6FF),
    (0x1F900, 0x1F9FF),
    (0x1FA70, 0x1FAFF),
    (0x2600, 0x26FF),
    (0x2700, 0x27BF),
    (0x1F1E6, 0x1F1FF),
    (0x2B50, 0x2B55),
)
_EMOJI_RE = re.compile(
    "[" + "".join("%s-%s" % (chr(a), chr(b)) for a, b in _EMOJI_RANGES) + "]"
)


_EMOJI_JUNK_RE = re.compile("[︎️‍⃣]")


_BOLD_DOUBLE_RE = re.compile(r"\*\*[^*\n]+?\*\*")
_BOLD_DOUBLE_SUB_RE = re.compile(r"\*\*([^*\n]+?)\*\*")
_BOLD_SINGLE_RE = re.compile(r"(?<!\*)\*(?=\S)[^*\n]+?(?<=\S)\*(?!\*)")


_HEADING_RE = re.compile(r"^\s*h[1-6]\.", re.IGNORECASE)
_LEAD_LABEL_RE = re.compile(r"^\s*(\*{1,2})\s*([^*\n]{1,60}?)\s*\1")
_TEMPLATE_LABELS = frozenset({
    "что случилось", "что за проблема", "что происходит", "что делать",
    "что делаю", "что сделал", "что проверил", "проверил", "что покажут",
    "вывод", "выводы", "итог", "итоги", "причина", "причины",
    "вероятные причины", "рекомендации", "решение", "диагностика",
    "суть", "проблема", "sql",
})


_RULE3_RE = re.compile(r"\b\w[\w-]*,\s+\w[\w-]*\s+(?:и|and)\s+\w[\w-]*\b", re.IGNORECASE)


def _count_bold(text):
    doubles = _BOLD_DOUBLE_RE.findall(text)

    stripped = _BOLD_DOUBLE_RE.sub("  ", text)
    singles = _BOLD_SINGLE_RE.findall(stripped)
    return len(doubles) + len(singles)


def _is_template_line(line):
    if _HEADING_RE.match(line):
        return True
    m = _LEAD_LABEL_RE.match(line)
    if m:
        inner = m.group(2).strip()
        norm = inner.strip(" .:").lower()
        if norm in _TEMPLATE_LABELS:
            return True

        if len(norm.split()) <= 4 and re.search(r"[.:]\s*$", inner):
            return True
    return False


def _count_emoji(text):
    return len(_EMOJI_RE.findall(text))


def ai_marks(text):


    if not isinstance(text, str):
        return {"dashes": 0, "cliches": [], "emoji": 0, "bold_runs": 0,
                "arrows": 0, "template_headers": 0, "rule_of_three": 0}
    low = text.lower()
    cliches = [c for c in AI_CLICHES if c in low]
    template = sum(1 for ln in text.splitlines() if _is_template_line(ln))
    return {
        "dashes": len(_DASH_RE.findall(text)),
        "cliches": cliches,
        "emoji": _count_emoji(text),
        "bold_runs": _count_bold(text),
        "arrows": len(_ARROW_RE.findall(text)),
        "template_headers": template,
        "rule_of_three": len(_RULE3_RE.findall(text)),
    }


def deterministic_fix(text):


    fixes = {"dashes": 0, "arrows": 0, "bold": 0, "emoji": 0}
    if not isinstance(text, str):
        return text, fixes

    fixes["emoji"] = _count_emoji(text)
    text = _EMOJI_RE.sub("", text)


    text = _EMOJI_JUNK_RE.sub("", text)


    fixes["dashes"] = len(_DASH_RE.findall(text))
    text = re.sub(r"(?m)^([ \t]*)[—–][ \t]+", r"\1- ", text)
    text = re.sub(r"(?<=\d)[ \t]*[—–][ \t]*(?=\d)", "-", text)
    text = re.sub(r"[ \t]*[—–][ \t]*", ", ", text)

    fixes["arrows"] = len(_ARROW_RE.findall(text))
    text = re.sub(r"[ \t]*(?:→|←|⇒|->)[ \t]*", ", ", text)

    fixes["bold"] = len(_BOLD_DOUBLE_SUB_RE.findall(text))
    text = _BOLD_DOUBLE_SUB_RE.sub(r"\1", text)

    return text, fixes


def lint_report(text):


    m = ai_marks(text)
    return {
        "dashes": m["dashes"],
        "cliches": len(m["cliches"]),
        "cliches_list": m["cliches"],
        "emoji": m["emoji"],
        "bold_runs": m["bold_runs"],
        "arrows": m["arrows"],
        "template_headers": m["template_headers"],
        "rule_of_three": m["rule_of_three"],
        "facts_ok": None,
    }


_NO_DB_RE = re.compile(
    r"коннект[а-я]*\s+к\s+(бд|базе|базе\s+данных)\s+(у\s+меня\s+)?нет|"
    r"без\s+бд\s+точно\s+не\s+скаж|нет\s+доступа\s+к\s+бд|бд\s+недоступн|"
    r"коннект[а-я]*\s+к\s+бд\s+(у\s+меня\s+)?рв[её]тся|привожу\s+(sql|запрос[а-я]*)\s+текстом",
    re.I)


def content_flags(text):


    flags = []
    if _NO_DB_RE.search(text or ""):
        flags.append("no_db")
    return flags


_PROMPT_HEADER = (
    "Ты редактор-стилист службы сопровождения WMS. Тебе дают готовый разбор заявки. Перепиши "
    "ТОЛЬКО ПОДАЧУ (как написано) под стиль автора, НЕ трогая смысл, факты и выводы.\n\n"
    "Жёсткие правила:\n"
    "1. Сохрани КАЖДОЕ число, ID, имя таблицы/поля, код и вывод ДОСЛОВНО. Ничего не добавляй "
    "и не выдумывай, новых чисел не вводи.\n"
    "2. Плейсхолдеры вида ⟦CODE_1⟧, ⟦CODE_2⟧ не трогай, не переводи и не "
    "переписывай — оставь ровно на своих местах.\n"
    "3. БЕЗ длинных тире (— и –): ставь точку, запятую, двоеточие или скобки.\n"
    "4. БЕЗ ИИ-клише из списка ниже и без канцелярита.\n"
    "5. КРАТКО, это главное. Пиши ЗАМЕТНО КОРОЧЕ оригинала: режь воду, повторы, разжёвывание "
    "очевидного, преамбулы («ниже разбор», «чтобы понять, что…»), хеджи и мета-рассуждения «как "
    "проверить». Оставляй ТОЛЬКО суть, факты, вывод и SQL. Инженер пишет телеграфно — целься примерно "
    "вдвое короче, если смысл и факты не теряются. Никаких потерь фактов ради краткости (правило 1 главнее).\n"
    "6. Структуру каждый раз делай СВОЮ, не по одному шаблону; без заголовка h3 и без "
    "трафаретных ярлыков-подзаголовков.\n"
    "7. Пиши по-русски, живо и по делу, английские термины оставляй как есть.\n"
    "8. НЕ называй файлы-плейбуки и не ссылайся на них: убери «Плейбук: <имя>.md», «по "
    "документу <файл>», «согласно раннбуку» — просто примени знание, будто сам его знаешь.\n"
    "9. НЕ пиши мета-ремарки про доступ к БД: «коннекта к БД (у меня) нет», «без БД точно не "
    "скажу», «привожу SQL текстом», «прогони из своего клиента». SQL-блоки (⟦CODE_n⟧) ОСТАВЬ на "
    "местах, но подавай их как обычные запросы для проверки, без оговорок про отсутствие доступа.\n"
    "10. НЕ ссылайся на внутренние имена методов/классов из кода как на доказательство («по коду "
    "видно», «в методе getFromLot», «дёргает checkCherryReplenishmentLock»): опиши механизм "
    "своими словами. Имена ТАБЛИЦ/полей/событий КАПСОМ (LOTXLOCXID, ROUTEFINISHALL) — это факты, "
    "их СОХРАНЯЙ дословно.\n"
    "11. Причины НЕ выстраивай жёстким нумерованным списком «1) … 2) … 3)» с одинаковой "
    "подводкой; если их несколько, дай живым текстом."
)


def build_humanize_prompt(frozen_analysis, profile_text, examples):


    frozen_analysis = frozen_analysis if isinstance(frozen_analysis, str) else ""
    profile_text = (profile_text or "").strip() if isinstance(profile_text, str) else ""
    examples = list(examples) if examples else []

    parts = [_PROMPT_HEADER]

    cliche_list = ", ".join("«%s»" % c for c in AI_CLICHES[:22])
    parts.append("Клише, которых быть НЕ должно: " + cliche_list + " и подобные.")

    if profile_text:
        parts.append("Карта стиля автора (ориентир, как он пишет):\n" + profile_text)

    good = [str(e).strip() for e in examples if str(e).strip()]
    if good:
        block = "\n\n".join("--- пример %d ---\n%s" % (i + 1, e) for i, e in enumerate(good))
        parts.append("Примеры того, КАК автор пишет (перенимай тон, не копируй содержание):\n" + block)

    parts.append("Текст для переписывания (между маркерами, верни только переписанный вариант):\n"
                 "<<<НАЧАЛО\n" + frozen_analysis + "\nКОНЕЦ>>>")
    parts.append("Верни ТОЛЬКО переписанный текст, без пояснений и без обёрток.")

    return "\n\n".join(parts)
