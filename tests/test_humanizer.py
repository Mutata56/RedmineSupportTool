# -*- coding: utf-8 -*-


from agent import humanizer as H


def test_freeze_restore_sql_roundtrip():
    text = "До кода.\n```sql\nselect * from LOTxLOCxID where loc = '144в';\n```\nПосле кода."
    frozen, cmap = H.freeze_code(text)
    assert len(cmap) == 1
    assert "```" not in frozen
    assert "⟦CODE_1⟧" in frozen
    restored, ok, missing = H.restore_code(frozen, cmap)
    assert ok is True and missing == []
    assert restored == text


def test_freeze_restore_byte_exact_with_backslash_and_dollar():

    text = "```\nregex \\1 and $1 and \\g<0> \\\\ path C:\\temp\n```"
    frozen, cmap = H.freeze_code(text)
    restored, ok, missing = H.restore_code(frozen, cmap)
    assert ok is True and restored == text


def test_freeze_pre_with_inner_code_is_one_block():

    text = "текст <pre>line1\n<code>inner</code>\nline2</pre> хвост"
    frozen, cmap = H.freeze_code(text)
    assert len(cmap) == 1
    assert "<pre>" not in frozen and "<code>" not in frozen
    restored, ok, _ = H.restore_code(frozen, cmap)
    assert ok and restored == text


def test_freeze_multiple_blocks_order():
    text = ("A ```sql\nselect 1\n``` B <pre>PRE</pre> C <code>inline</code> D")
    frozen, cmap = H.freeze_code(text)
    assert len(cmap) == 3
    assert frozen.index("⟦CODE_1⟧") < frozen.index("⟦CODE_2⟧") < frozen.index("⟦CODE_3⟧")
    restored, ok, _ = H.restore_code(frozen, cmap)
    assert ok and restored == text


def test_freeze_no_blocks_and_empty():
    for text in ("Просто проза без кода.", ""):
        frozen, cmap = H.freeze_code(text)
        assert cmap == {} and frozen == text
        restored, ok, missing = H.restore_code(frozen, cmap)
        assert ok and missing == [] and restored == text


def test_restore_missing_placeholder_hard_fail():
    text = "before ```code``` after"
    frozen, cmap = H.freeze_code(text)
    broken = frozen.replace("⟦CODE_1⟧", "")
    restored, ok, missing = H.restore_code(broken, cmap)
    assert ok is False
    assert "⟦CODE_1⟧" in missing


def test_freeze_bare_sql_block():

    text = ("Диагностика по приёмке:\n\n"
            "-- 1. приёмки\n"
            "SELECT receiptkey, SUSR4, EXTERNRECEIPTKEY, storerkey\n"
            "FROM wmwhse1.RECEIPT\n"
            "WHERE receiptkey IN ('0000059276','0000059277');\n\n"
            "Дальше смотрим stamp.")
    frozen, cmap = H.freeze_code(text)
    assert len(cmap) == 1
    restored, ok, missing = H.restore_code(frozen, cmap)
    assert ok and restored == text

    f = H.extract_facts(frozen)
    assert "EXTERNRECEIPTKEY" not in f["idents"] and "RECEIPT" not in f["idents"]
    assert "0000059277" not in f["numbers"]


def test_freeze_bare_sql_not_false_positive_on_prose():

    text = ("Оператор жмёт SELECT и ждёт.\n"
            "Дальше ничего не происходит, зависает.")
    frozen, cmap = H.freeze_code(text)
    assert cmap == {} and frozen == text


def test_restore_damaged_placeholder_hard_fail():
    text = "before ```code``` after"
    frozen, cmap = H.freeze_code(text)
    broken = frozen.replace("⟦CODE_1⟧", "⟦CODE_9⟧")
    restored, ok, missing = H.restore_code(broken, cmap)
    assert ok is False and "⟦CODE_1⟧" in missing


def test_extract_numbers_ge_two_digits():
    facts = H.extract_facts("порог 50, стало 51, всего 138782 и код 0000018351, но 1 короб")
    assert facts["numbers"] == {"50", "51", "138782", "0000018351"}
    assert "1" not in facts["numbers"]


def test_extract_issue_refs():
    facts = H.extract_facts("см. баг #10102 и заявку #10106")
    assert facts["issue_refs"] == {"#10102", "#10106"}


def test_extract_idents_with_stopwords():
    facts = H.extract_facts("таблица LOTXLOCXID и RECEIPT, событие ROUTEFINISHALL, но SQL/БД/RF/DBA")
    assert {"LOTXLOCXID", "RECEIPT", "ROUTEFINISHALL"} <= facts["idents"]
    for stop in ("SQL", "RF", "DBA", "БД"):
        assert stop not in facts["idents"]


def test_extract_codes_and_ip():
    facts = H.extract_facts("накладная TTN-0950760625 на складе wmwhse1, сервер 192.0.2.10")
    assert "TTN-0950760625" in facts["codes"]
    assert "wmwhse1" in facts["codes"]
    assert "192.0.2.10" in facts["ips"]


def test_extract_facts_ignores_placeholders():

    facts = H.extract_facts("смотри ⟦CODE_10⟧ там дальше")
    assert facts["numbers"] == set()


def test_check_facts_ok_on_preserved():
    original = "На хосте EXAMPLE-APP-02-102 стало 51 сессий при пороге 50, см. #10102."
    candidate = "Хост EXAMPLE-APP-02-102: 51 сессия при пороге 50 (см. #10102), число держится."
    r = H.check_facts(original, candidate)
    assert r["ok"] is True
    assert r["missing"] == {} and r["added_numbers"] == []


def test_check_facts_missing_fact():
    original = "Таблица LOTXLOCXID, порог 50."
    candidate = "Порог 50."
    r = H.check_facts(original, candidate)
    assert r["ok"] is False
    assert "LOTXLOCXID" in r["missing"].get("idents", [])


def test_check_facts_added_number_hallucination():
    original = "Сессий 51 при пороге 50."
    candidate = "Сессий 51 при пороге 50, было 37 утром."
    r = H.check_facts(original, candidate)
    assert r["ok"] is False
    assert "37" in r["added_numbers"]


def test_ai_marks_detects_everything():
    dirty = ("h3. Разбор\n\n*Вывод* по заявке #51 — таким образом всё готово 🚀. "
             "Проверил → нашёл, **важно** и *курсив*. Отличный вопрос!")
    m = H.ai_marks(dirty)
    assert m["dashes"] == 1
    assert "таким образом" in m["cliches"]
    assert "отличный вопрос" in m["cliches"]
    assert m["emoji"] == 1
    assert m["arrows"] == 1
    assert m["bold_runs"] >= 2
    assert m["template_headers"] >= 1


def test_ai_marks_rule_of_three():
    m = H.ai_marks("мероприятие даёт инновации, вдохновение и инсайты для всех")
    assert m["rule_of_three"] >= 1


def test_ai_marks_clean_text_all_zero():


    clean = ("Число telnet-сессий на хосте выросло до 51 при пороге 50.\n"
             "Метрика свежая, точки идут, хост живой.\n"
             "2 * 2 = 4, счёт держится у порога, поэтому пока рано закрывать.\n"
             "* пункт наблюдения по сменам")
    m = H.ai_marks(clean)
    assert m["dashes"] == 0
    assert m["cliches"] == []
    assert m["emoji"] == 0
    assert m["arrows"] == 0
    assert m["bold_runs"] == 0
    assert m["template_headers"] == 0
    assert m["rule_of_three"] == 0


def test_ai_marks_placeholder_not_emoji():

    assert H.ai_marks("текст ⟦CODE_1⟧ текст")["emoji"] == 0


def test_fix_dash_to_comma_numbers_intact():
    fixed, fixes = H.deterministic_fix("порог 50 — уже 51 сессия")
    assert fixed == "порог 50, уже 51 сессия"
    assert fixes["dashes"] == 1
    assert "50" in fixed and "51" in fixed


def test_fix_hyphen_in_word_and_code_untouched():
    src = "RF-транзакции и накладная TTN-0950760625"
    fixed, fixes = H.deterministic_fix(src)
    assert fixed == src
    assert fixes["dashes"] == 0


def test_fix_removes_emoji():
    fixed, fixes = H.deterministic_fix("готово 🚀")
    assert "🚀" not in fixed and "готово" in fixed
    assert fixes["emoji"] == 1


def test_fix_placeholder_and_numbers_untouched():
    src = "смотри ⟦CODE_1⟧ там 138782"
    fixed, fixes = H.deterministic_fix(src)
    assert "⟦CODE_1⟧" in fixed and "138782" in fixed
    assert fixes == {"dashes": 0, "arrows": 0, "bold": 0, "emoji": 0}


def test_fix_strips_double_bold_only():
    fixed, fixes = H.deterministic_fix("**важно** не трогать *курсив*")
    assert "важно не трогать" in fixed
    assert "*курсив*" in fixed
    assert fixes["bold"] == 1


def test_fix_arrow_to_comma():
    fixed, fixes = H.deterministic_fix("блокировка → DBA")
    assert fixed == "блокировка, DBA"
    assert fixes["arrows"] == 1


def test_lint_report_shape():
    r = H.lint_report("готово — таким образом всё 🚀")
    assert r["dashes"] == 1
    assert r["cliches"] == 1
    assert r["emoji"] == 1
    assert r["facts_ok"] is None
    assert "таким образом" in r["cliches_list"]


def test_build_prompt_contains_all_constraints():
    p = H.build_humanize_prompt("Разбор ⟦CODE_1⟧ по заявке #51",
                                 "СТИЛЬ: короткие фразы",
                                 ["пример один"])
    low = p.lower()

    assert "⟦CODE_1⟧" in p or "⟦code_1⟧" in low
    assert "дословно" in low
    assert "тире" in low
    assert "клише" in low
    assert "коротко" in low or "короче" in low
    assert "h3" in low
    assert "структур" in low

    assert "СТИЛЬ: короткие фразы" in p
    assert "пример один" in p

    assert "Разбор ⟦CODE_1⟧ по заявке #51" in p


def test_build_prompt_optional_args():

    p = H.build_humanize_prompt("текст", "", [])
    assert isinstance(p, str) and "текст" in p


def test_dash_keeps_ranges_and_bullets():


    assert H.deterministic_fix("окно 10—15 мин")[0] == "окно 10-15 мин"
    assert H.deterministic_fix("заявки 10109—10110")[0] == "заявки 10109-10110"
    assert H.deterministic_fix("— проверил\n— перезапустил")[0] == "- проверил\n- перезапустил"

    assert H.deterministic_fix("Проверил логи — всё ок")[0] == "Проверил логи, всё ок"


def test_dash_range_survives_fact_guard():

    frozen, _ = H.freeze_code("Окно обрезки 10—15 мин по таблице ORDERS")
    fixed, _ = H.deterministic_fix(frozen)
    assert "10-15" in fixed and H.check_facts(frozen, fixed)["ok"]


def test_emoji_cleanup_leaves_no_invisible_junk():


    out, _ = H.deterministic_fix("Готово \u2705\ufe0f и \U0001F468\u200d\U0001F4BB и 1\ufe0f\u20e3")
    for junk in ("\ufe0f", "\ufe0e", "\u200d", "\u20e3"):
        assert junk not in out, "остался %r в %r" % (junk, out)
