# -*- coding: utf-8 -*-


import subprocess

from . import sql_engine as se


DIAG = {
    "locks": {


        "sql": ("select replace(replace(text_blocking, char(13), ' '), char(10), ' ') as text_blocking,\n"
                "       replace(replace(text_blocked,  char(13), ' '), char(10), ' ') as text_blocked,\n"
                "       resource_type, object_name, wait_duration_ms\n"
                "from wms_example.dbo.t_AdmLockBlock\n"
                "where {where}\n"
                "order by last_request_blocking desc"),
        "cols": ["text_blocking", "text_blocked", "resource_type", "object_name",
                 "wait_duration_ms"],
        "max_rows": 3,
    },
    "freespace": {

        "sql": ("SELECT DISTINCT vs.volume_mount_point,\n"
                "       CAST(vs.available_bytes/1073741824.0 AS decimal(10,1)) AS free_gb,\n"
                "       CAST(100.0*vs.available_bytes/vs.total_bytes AS decimal(5,1)) AS free_pct\n"
                "FROM sys.master_files mf\n"
                "CROSS APPLY sys.dm_os_volume_stats(mf.database_id, mf.file_id) vs\n"
                "ORDER BY free_pct"),
        "cols": ["volume_mount_point", "free_gb", "free_pct"],
        "max_rows": 8,
    },
    "log_size": {


        "sql": ("SELECT d.name AS db, d.log_reuse_wait_desc AS reuse_wait,\n"
                "       CAST(mf.size*8/1024.0 AS decimal(10,1)) AS log_mb,\n"
                "       d.recovery_model_desc AS recovery\n"
                "FROM sys.databases d\n"
                "JOIN sys.master_files mf ON mf.database_id = d.database_id AND mf.type = 1\n"
                "WHERE d.log_reuse_wait_desc <> 'NOTHING'\n"
                "ORDER BY mf.size DESC"),
        "cols": ["db", "log_mb", "reuse_wait", "recovery"],
        "max_rows": 6,
    },
    "transaction": {

        "sql": ("SELECT TOP 20 DATEDIFF(SECOND, at.transaction_begin_time, GETDATE()) AS secs,\n"
                "       es.session_id, es.login_name, es.host_name, es.program_name, es.status\n"
                "FROM sys.dm_tran_active_transactions at\n"
                "JOIN sys.dm_tran_session_transactions st ON st.transaction_id = at.transaction_id\n"
                "JOIN sys.dm_exec_sessions es ON es.session_id = st.session_id\n"
                "WHERE es.is_user_process = 1\n"
                "ORDER BY secs DESC"),
        "cols": ["secs", "session_id", "login_name", "host_name", "program_name"],
        "max_rows": 10,
    },
    "archive_backup": {

        "sql": ("SELECT j.name AS job,\n"
                "       msdb.dbo.agent_datetime(h.run_date, h.run_time) AS run_at,\n"
                "       h.step_name, LEFT(h.message, 300) AS msg\n"
                "FROM msdb.dbo.sysjobs j\n"
                "JOIN msdb.dbo.sysjobhistory h ON h.job_id = j.job_id\n"
                "WHERE (j.name LIKE '%Archive%' OR j.name LIKE '%BackUp%'\n"
                "       OR j.name LIKE '%Бэкап%' OR j.name LIKE '%Архив%')\n"
                "  AND h.run_status <> 1\n"
                "  AND h.run_date >= CONVERT(int, CONVERT(varchar, DATEADD(DAY,-2,GETDATE()), 112))\n"
                "ORDER BY h.instance_id DESC"),
        "cols": ["job", "run_at", "step_name", "msg"],
        "max_rows": 6,
    },
}


def diag_sql(atype, ctx=None):


    spec = DIAG.get(atype)
    if not spec:
        return None
    sql = spec["sql"]
    if "{where}" in sql:
        where = (ctx or {}).get("where")
        if not where:
            where = "wait_duration_ms > 60000"
        sql = sql.replace("{where}", where)
    return sql


def _clip(v, n=140):

    v = " ".join(str(v).split())
    return v if len(v) <= n else v[:n - 1] + "…"


def format_transposed(header, rows, cols, max_rows=6, clip=140):


    if not header:
        return "(запрос не вернул колонок)"
    pairs = [(c, se._colidx(header, c)) for c in cols]
    pairs = [(c, i) for c, i in pairs if i is not None]
    if not pairs:
        return "(важные колонки не найдены в ответе)"
    rows = rows[:max_rows]
    if not rows:
        return "(0 строк)"
    label_w = max(len(c) for c, _ in pairs)
    n = len(rows)

    cell = {}
    for c, i in pairs:
        for k, r in enumerate(rows):
            cell[(c, k)] = _clip(r[i] if i < len(r) else "", clip)

    colw = []
    for k in range(n):
        w = len("строка %d" % (k + 1))
        for c, _ in pairs:
            w = max(w, len(cell[(c, k)]))
        colw.append(w)
    head = " " * label_w + "  " + "  ".join(("строка %d" % (k + 1)).ljust(colw[k]) for k in range(n))
    lines = [head.rstrip()]
    for c, _ in pairs:
        line = c.ljust(label_w) + "  " + "  ".join(cell[(c, k)].ljust(colw[k]) for k in range(n))
        lines.append(line.rstrip())
    return "\n".join(lines)


def run_diag(server, atype, ctx=None, _session=None):


    sql = diag_sql(atype, ctx)
    if not sql:
        return False, [], [], "нет DIAG-запроса для типа «%s»" % atype
    okg, reason = se.read_only_guard(sql)
    if not okg:
        return False, [], [], "SQL не прошёл read-only гард: %s" % reason
    login = server.get("login") or se.DB_LOGIN
    try:
        if _session is not None:
            sess = _session
        else:
            pwd = se.read_db_pass(login)
            if not pwd:
                return False, [], [], "нет пароля логина «%s» (secrets.local.json db.logins)" % login
            sess = se.TsqlSession(server["host"], server.get("port", 1433), login=login, pwd=pwd)
        sess.start()
        try:
            ok, text = sess.run_batch(sql)
        finally:
            sess.close()
    except se.SessionDead as e:
        return False, [], [], "БД недоступна: %s" % e
    except (OSError, subprocess.SubprocessError) as e:

        return False, [], [], "tsql/FreeTDS недоступен: %s" % e
    if not ok:


        return False, [], [], (text or "").strip()[:300]
    header, rows = se._tsql_rows(text)
    return True, header, rows, ""


def build_report_block(atype, sql, header, rows):

    spec = DIAG.get(atype) or {}
    cols = spec.get("cols") or (header or [])
    max_rows = spec.get("max_rows", 6)
    table = format_transposed(header, rows, cols, max_rows=max_rows)
    return ("<pre><code class=\"sql\">\n"
            "%s\n"
            "-- РЕЗУЛЬТАТ (важные колонки)\n"
            "/*\n%s\n*/\n"
            "</code></pre>" % (sql.rstrip(), table))
