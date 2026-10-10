# -*- coding: utf-8 -*-


import re


UPTIME_SERVICE = [
    ("report", "reports"), ("scheduler", "sched"), ("ui ", "uiservice"),
    ("app uptime", "wmapp"), ("excel", "excelplugin"), ("socketserver", "socketserver"),
    ("socket", "socketserver"), ("support-printtab", "support-printtab"), ("printtab", "support-printtab"),
]

SITE_APP_HOST = {
    "CLB_SITE05": r"example-app-01-1|example-app-01-2", "CLB_SITE04": r"EXAMPLE-APP-02-1|EXAMPLE-APP-02-2",
    "CLB_SITE03": r"EXAMPLE-APP-03-1", "CLB_SITE02": r"example-app-04-1", "CLB_SITE01": r"example-app-05-1|EXAMPLE-APP-05-2",
    "CLD_SITE04": r"example-app-06-1", "CLD_SITE02": r"EXAMPLE-APP-07-1", "CLD_SITE07": r"EXAMPLE-APP-08-1|EXAMPLE-APP-08-2",
    "CLD_SITE06": r"example-app-09-1", "CLD_SITE09": r"EXAMPLE-APP-10-1", "CLD_SITE05": r"EXAMPLE-APP-11-1",
    "CLD_SITE08": r"example-app-12-1", "CLE": r"example-app-13-1|EXAMPLE-APP-13-2",
}

RF_TASKKILL = ("<pre><code>\n"
               "taskkill /f /t /im telnetd64.exe\n"
               "taskkill /f /t /im conhost.exe\n"
               "taskkill /f /t /im cmd.exe\n"
               "</code></pre>")


def _alert_type(subj):
    s = (subj or "").lower()
    if "locks" in s:
        return "locks"
    if "архивация" in s or "бэкап" in s or "backup" in s or "фуллбэкап" in s:
        return "archive_backup"
    if "транзакц" in s:
        return "transaction"
    if "tempdb" in s:
        return "tempdb"
    if "log_size" in s or "log size" in s:
        return "log_size"
    if "freespace" in s or "св. место" in s or "свободное место" in s:
        return "freespace"
    if "heapmemory" in s or "heap memory" in s:
        return "heap"
    if "кол-во rf" in s or "кол_во rf" in s:
        return "rf"
    if "jboss" in s:
        return "jboss"
    if "apache" in s:
        return "apache"
    if "uptime" in s:
        return "uptime"
    return None


def _locks_wait_value(description):


    if not description:
        return None
    s = description.lower()


    for anchor in ("t_admlockblock.max", "value"):
        i = s.find(anchor)
        if i >= 0:
            m = re.search(r"(\d{4,}\.\d+)", s[i + len(anchor):])
            if m:
                try:
                    return int(float(m.group(1)))
                except ValueError:
                    pass
    return None


def _heap_service(subj):


    m = re.search(r"heapmemory\s*([A-Za-z0-9_\-]+)", subj or "", re.I)
    if m and m.group(1).lower() not in ("alert", "alerting"):
        return m.group(1)
    return None


def _uptime_service(subj):
    s = (subj or "").lower()
    for needle, svc in UPTIME_SERVICE:
        if needle in s:
            return svc
    return None


def alert_name_substr(subject):


    atype = _alert_type(subject)
    if atype == "uptime":
        s = (subject or "").lower()
        m = re.search(r"([a-zа-я0-9_\-]+)\s+uptime", s)
        return (m.group(1) + " uptime") if m else "uptime"
    if atype == "jboss":
        return "jboss"
    if atype == "rf":
        return "кол-во rf"
    if atype == "apache":
        return "apache"
    return None


def _is_alive(influx, alert_type, code, service):

    if influx is None:
        return None, "проверка, что служба жива, не выполнялась"
    host_rx = SITE_APP_HOST.get(code)
    if not host_rx:
        return None, "нет паттерна app-хоста для площадки"
    try:
        if alert_type == "apache":
            q = ("SELECT last(\"BusyWorkers\") FROM apache WHERE host=~/%s/ "
                 "AND time > now()-10m" % host_rx)
        else:
            if not service:


                return None, "служба из темы алерта не распознана"
            q = ("SELECT last(\"Uptime\") FROM java_runtime WHERE host=~/%s/ "
                 "AND service=~/%s/ AND time > now()-10m" % (host_rx, service))


        r0 = (influx(q).get("results") or [{}])[0]
        if r0.get("error"):


            return None, "InfluxDB вернул ошибку: %s" % r0["error"]
        d = r0.get("series", [])
        if d and d[0].get("values"):
            return True, "метрика поступает (свежая точка за 10 мин)"
        return False, "метрика молчит (нет свежих точек за 10 мин)"
    except Exception as e:
        return None, "проверка не удалась: %s" % e


def build_service_verdict(subject, site_name="", code="", influx=None, alert_state=None,
                          description=None, metric_fresh=None):
    atype = _alert_type(subject)
    if atype is None:
        return None
    head = "h3. Разбор\n\n"
    who = site_name or code


    if atype == "locks":
        wait = _locks_wait_value(description)
        where = ("wait_duration_ms = %d" % wait) if wait else "wait_duration_ms > 60000"
        sql = (
            "<pre><code class=\"sql\">\n"
            "select top 1000 text_blocking, text_blocked, resource_type, object_name\n"
            "from wms_example.dbo.t_AdmLockBlock\n"
            "where " + where + "\n"
            "order by last_request_blocking desc;\n"
            "</code></pre>")
        body = head + sql
        return {"mode": "deterministic", "type": "locks", "comment": body,
                "reason": "locks - t_AdmLockBlock по wait_duration_ms из тела заявки"}


    if atype == "archive_backup":

        sql_jobs = (
            "<pre><code class=\"sql\">\n"
            "SELECT j.name AS job,\n"
            "       msdb.dbo.agent_datetime(h.run_date, h.run_time) AS run_at,\n"
            "       h.run_status, h.step_id, h.step_name, LEFT(h.message, 500) AS msg\n"
            "FROM msdb.dbo.sysjobs j\n"
            "JOIN msdb.dbo.sysjobhistory h ON h.job_id = j.job_id\n"
            "WHERE (j.name LIKE '%Archive%' OR j.name LIKE '%BackUp%'\n"
            "       OR j.name LIKE '%Бэкап%' OR j.name LIKE '%Архив%')\n"
            "  AND h.run_status <> 1\n"
            "  AND h.run_date >= CONVERT(int, CONVERT(varchar, DATEADD(DAY,-2,GETDATE()), 112))\n"
            "ORDER BY h.instance_id DESC;\n"
            "</code></pre>")
        body = (head +
                "Какой джоб упал и почему (история SQL Agent, msdb):\n\n" + sql_jobs + "\n\n"
                "Пляшем от этого.")
        return {"mode": "deterministic", "type": "archive_backup", "comment": body,
                "reason": "архивация/бэкап - msdb история упавшего джоба"}


    if atype == "transaction":
        sql_tran = (
            "<pre><code class=\"sql\">\n"
            "SELECT DATEDIFF(SECOND, at.transaction_begin_time, GETDATE()) AS secs,\n"
            "       st.session_id, es.login_name, es.host_name, es.program_name, es.status\n"
            "FROM sys.dm_tran_active_transactions at\n"
            "LEFT JOIN sys.dm_tran_session_transactions st ON st.transaction_id = at.transaction_id\n"
            "LEFT JOIN sys.dm_exec_sessions es ON es.session_id = st.session_id\n"
            "WHERE DATEDIFF(SECOND, at.transaction_begin_time, GETDATE()) > 300\n"
            "ORDER BY secs DESC;\n"
            "</code></pre>")
        sql_blk = (
            "<pre><code class=\"sql\">\n"
            "SELECT TOP 200 InsertDate, wait_duration_ms, resource_type, object_name,\n"
            "       text_blocking, text_blocked\n"
            "FROM wms_example.dbo.t_AdmLockBlock\n"
            "WHERE InsertDate >= DATEADD(HOUR, -3, GETDATE())\n"
            "ORDER BY wait_duration_ms DESC;\n"
            "</code></pre>")
        body = (head +
                "Часто отвисает сама.\n\n"
                "Посмотреть какая и чья висит транзакция\n\n" + sql_tran + "\n\n"
                "Проанализировать транзакции последние:\n\n" + sql_blk + "\n\n"
                "Чем занята зависшая сессия - @DBCC INPUTBUFFER(<session_id>)@ по её session_id "
                "из первого запроса.")
        return {"mode": "deterministic", "type": "transaction", "comment": body,
                "reason": "транзакции - долгая транзакция + блокировки (t_AdmLockBlock) + наблюдение"}


    if atype == "tempdb":
        sql_compose = (
            "<pre><code class=\"sql\">\n"
            "SELECT CAST(SUM(unallocated_extent_page_count)*8/1024.0 AS decimal(10,1)) AS free_mb,\n"
            "       CAST(SUM(user_object_reserved_page_count)*8/1024.0 AS decimal(10,1)) AS user_obj_mb,\n"
            "       CAST(SUM(internal_object_reserved_page_count)*8/1024.0 AS decimal(10,1)) AS internal_obj_mb,\n"
            "       CAST(SUM(version_store_reserved_page_count)*8/1024.0 AS decimal(10,1)) AS version_store_mb\n"
            "FROM tempdb.sys.dm_db_file_space_usage;\n"
            "</code></pre>")
        sql_who = (
            "<pre><code class=\"sql\">\n"
            "SELECT ssu.session_id,\n"
            "       CAST((ssu.user_objects_alloc_page_count\n"
            "             + ssu.internal_objects_alloc_page_count)*8/1024.0 AS decimal(10,1)) AS alloc_mb,\n"
            "       es.login_name, es.host_name, es.program_name, er.status, t.text AS sql_text\n"
            "FROM tempdb.sys.dm_db_session_space_usage ssu\n"
            "JOIN sys.dm_exec_sessions es ON es.session_id = ssu.session_id\n"
            "LEFT JOIN sys.dm_exec_requests er ON er.session_id = ssu.session_id\n"
            "OUTER APPLY sys.dm_exec_sql_text(er.sql_handle) t\n"
            "WHERE (ssu.user_objects_alloc_page_count + ssu.internal_objects_alloc_page_count) > 0\n"
            "ORDER BY alloc_mb DESC;\n"
            "</code></pre>")
        sql_files = (
            "<pre><code class=\"sql\">\n"
            "SELECT mf.name, mf.physical_name,\n"
            "       CAST(mf.size*8/1024.0 AS decimal(10,1)) AS size_mb,\n"
            "       CAST(100.0*vs.available_bytes/vs.total_bytes AS decimal(5,1)) AS drive_free_pct\n"
            "FROM sys.master_files mf\n"
            "CROSS APPLY sys.dm_os_volume_stats(mf.database_id, mf.file_id) vs\n"
            "WHERE mf.database_id = DB_ID('tempdb');\n"
            "</code></pre>")
        body = (head +
                "Из чего сейчас состоит tempdb (свободно / user / internal / версионник):\n\n"
                + sql_compose + "\n\n"
                "Кто его занял, по сессиям (сколько МБ, кто, что выполняет):\n\n" + sql_who + "\n\n"
                "Файлы tempdb и место на их диске:\n\n" + sql_files + "\n\n"
                "По первому запросу видно причину: большой version_store - долгая или незакрытая "
                "транзакция копит версии строк; большой internal - тяжёлые сортировки и соединения; "
                "распух лог - почти всегда долгая транзакция. Пока причина не ясна, заявку не "
                "закрывать.")
        return {"mode": "deterministic", "type": "tempdb", "comment": body,
                "reason": "tempdb - состав/кто занял/файлы+диск (2012-safe DMV) + как читать"}


    if atype == "log_size":
        sql_size = (
            "<pre><code class=\"sql\">\n"
            "CREATE TABLE #ls (DBName sysname, LogMB float, UsedPct float, Status int);\n"
            "INSERT #ls EXEC ('DBCC SQLPERF(LOGSPACE)');\n"
            "SELECT DBName, LogMB, UsedPct,\n"
            "       CAST(LogMB * (1 - UsedPct/100.0) AS decimal(10,1)) AS ReclaimableMB\n"
            "FROM #ls ORDER BY ReclaimableMB DESC;\n"
            "DROP TABLE #ls;\n"
            "</code></pre>")
        sql_model = (
            "<pre><code class=\"sql\">\n"
            "SELECT name, recovery_model_desc, log_reuse_wait_desc\n"
            "FROM sys.databases ORDER BY log_reuse_wait_desc;\n"
            "</code></pre>")
        sql_disk = (
            "<pre><code class=\"sql\">\n"
            "SELECT DISTINCT vs.volume_mount_point AS drive,\n"
            "       CAST(100.0*vs.available_bytes/vs.total_bytes AS decimal(5,1)) AS free_pct\n"
            "FROM sys.master_files mf\n"
            "CROSS APPLY sys.dm_os_volume_stats(mf.database_id, mf.file_id) vs\n"
            "ORDER BY free_pct;\n"
            "</code></pre>")
        body = (head +
                "Сколько занимают логи и сколько освободит шринк (ReclaimableMB):\n\n"
                + sql_size + "\n\n"
                "Модель восстановления и почему лог не усекается (колонка log_reuse_wait_desc):\n\n"
                + sql_model + "\n\n"
                "Место на дисках (куда встанет лог или его бэкап):\n\n" + sql_disk + "\n\n"
                "Как читать вторую таблицу: SIMPLE - лог усекается сам, шринк нужен только если "
                "файл раздулся разово. FULL - лог растёт, пока не сняли BACKUP LOG. В колонке "
                "log_reuse_wait_desc: LOG_BACKUP значит ждёт бэкап журнала, ACTIVE_TRANSACTION "
                "значит держит долгая транзакция (её и разбирать).\n\n"
                "Шринк лога (БД в FULL, ReclaimableMB большой, ПОСЛЕ BACKUP LOG):\n\n"
                "<pre><code class=\"sql\">\n"
                "DBCC SHRINKFILE (N'<LogName>', <target_mb>);\n"
                "</code></pre>")
        return {"mode": "deterministic", "type": "log_size", "comment": body,
                "reason": "Log_Size - Reclaimable/recovery/log_reuse + правила шринка"}


    if atype == "freespace":
        sql_drive = (
            "<pre><code class=\"sql\">\n"
            "SELECT DISTINCT vs.volume_mount_point AS drive,\n"
            "       CAST(vs.available_bytes/1073741824.0 AS decimal(10,1)) AS free_gb,\n"
            "       CAST(100.0*vs.available_bytes/vs.total_bytes AS decimal(5,1)) AS free_pct\n"
            "FROM sys.master_files mf\n"
            "CROSS APPLY sys.dm_os_volume_stats(mf.database_id, mf.file_id) vs\n"
            "ORDER BY free_pct;\n"
            "</code></pre>")
        sql_files = (
            "<pre><code class=\"sql\">\n"
            "SELECT DB_NAME(database_id) AS db, name AS file_name, type_desc,\n"
            "       CAST(size*8/1024.0 AS decimal(10,1)) AS size_mb, physical_name\n"
            "FROM sys.master_files ORDER BY size DESC;\n"
            "</code></pre>")
        sql_shrink = (
            "<pre><code class=\"sql\">\n"
            "CREATE TABLE #ls (DBName sysname, LogMB float, UsedPct float, Status int);\n"
            "INSERT #ls EXEC ('DBCC SQLPERF(LOGSPACE)');\n"
            "SELECT DBName, LogMB, UsedPct,\n"
            "       CAST(LogMB * (1 - UsedPct/100.0) AS decimal(10,1)) AS ReclaimableMB\n"
            "FROM #ls ORDER BY ReclaimableMB DESC;\n"
            "DROP TABLE #ls;\n"
            "SELECT name, recovery_model_desc, log_reuse_wait_desc\n"
            "FROM sys.databases ORDER BY log_reuse_wait_desc;\n"
            "</code></pre>")
        body = (head +
                "Мало места на диске. Смотрим, где кончается, что занимает и можно ли освободить.\n\n"
                "На каком диске мало места:\n\n" + sql_drive + "\n\n"
                "Что занимает: размеры файлов баз (данные и логи):\n\n" + sql_files + "\n\n"
                "Можно ли шринкануть логи и почему лог не усекается (ReclaimableMB - сколько МБ "
                "реально освободит шринк, то есть свободное место внутри лог-файла):\n\n"
                + sql_shrink + "\n\n"
                "Что делать: если ReclaimableMB большой - лог можно шринкануть @DBCC "
                "SHRINKFILE(N'<LogName>', <target_mb>)@ после .trn-бэкапа лога (он идёт каждые "
                "15 мин): бэкап сдвигает активные данные в VLF к голове лога, а хвост обрезаем "
                "шринком. Если место съели не логи - зайти на "
                "сервер и посмотреть крупные папки на этом диске: бэкапы и архивы (старые .bak / "
                ".trn), выгрузки, логи приложений, почистить устаревшее. Заявку не закрывать, пока "
                "место не освободили.")
        return {"mode": "deterministic", "type": "freespace", "comment": body,
                "reason": "FREESPACE - диск/файлы/шринк/log_reuse, разбор вручную"}


    if atype == "heap":
        svc = _heap_service(subject) or "службы"
        body = (head +
                "Возможно утечка памяти, снять дампы.\n\n"
                "Снять с сервера службы дампы (JDK идёт в комплекте JBoss). Сначала найти PID:\n"
                "<pre><code>\njps -l\n# или: tasklist | findstr java\n</code></pre>\n"
                "Thread dump (что делают потоки):\n"
                "<pre><code>\njstack -l <PID> > jstack_%s.txt\n</code></pre>\n"
                "Гистограмма объектов кучи (быстро, что занимает память):\n"
                "<pre><code>\njmap -histo:live <PID> > histo_%s.txt\n</code></pre>\n"
                "Полный heap dump (для глубокого анализа, тяжёлый файл):\n"
                "<pre><code>\njmap -dump:live,format=b,file=heap_%s.hprof <PID>\n</code></pre>\n"
                "Дампы приложить к заявке, эскалировать 2-й линии/программистам. "
                "Заявку не закрывать." % (svc, svc, svc))
        return {"mode": "deterministic", "type": "heap", "comment": body,
                "reason": "HeapMemory %s - команды дампа + эскалация, не закрывать" % svc}


    if alert_state == "ok":
        fresh = metric_fresh
        if fresh is None and atype in ("apache", "uptime"):

            svc = _uptime_service(subject) if atype == "uptime" else None
            fresh, _ = _is_alive(influx, atype, code, svc)
        if fresh is False:
            body = (head +
                    "Алерт по службе в Grafana зелёный, НО метрика не поступает — панель показывает "
                    "«No data». Grafana держит зелёное сердечко и при отсутствии данных (настройка "
                    "no-data алерта), поэтому зелёный алерт тут НЕ подтверждает, что служба в норме "
                    "(скорее наоборот — сбор метрик/служба под вопросом). Проверить на площадке %s, "
                    "поднята ли служба и идёт ли сбор метрик (JMX/telegraf). Заявку по зелёному "
                    "алерту НЕ закрывать, пока метрика молчит." % who)
            return {"mode": "deterministic", "type": atype, "comment": body,
                    "reason": "%s: алерт ok, но метрика молчит (No data) - не закрывать, проверить службу/сбор" % atype}
        body = (head + "Проверил в Grafana: алерт погас, служба в норме на площадке %s. "
                "Ложное/кратковременное срабатывание. Можно закрывать." % who)
        return {"mode": "deterministic", "type": atype, "comment": body,
                "reason": "%s: алерт погас (state=ok) - служба в норме, закрыть" % atype}


    if atype == "rf":
        body = (head +
                "Растёт число RF-сессий. Обычно нормализуется само.\n\n"
                "Беру в наблюдение: если график снижается и жалоб от склада нет - жду "
                "нормализации. Чистка сессий - только при остановке контура:\n\n"
                "%s" % RF_TASKKILL)
        return {"mode": "deterministic", "type": "rf", "comment": body,
                "reason": "RF - наблюдение по сменам, чистка при остановке контура"}


    if atype == "jboss":
        body = (head +
                "JBoss Connection Pool. Пул обычно отвисает сам, скачок коннектов временный.\n\n"
                "Беру в наблюдение (превентивные мероприятия). Если график вернулся в норму - "
                "закрываю.")
        return {"mode": "deterministic", "type": "jboss", "comment": body,
                "reason": "JBoss - наблюдение, пул отвисает сам"}


    service = _uptime_service(subject) if atype == "uptime" else None
    alive, note = _is_alive(influx, atype, code, service)
    svc_label = ("Apache" if atype == "apache"
                 else "*%s*" % (service or "служба"))

    if alive is True:
        body = (head +
                "Проверил в мониторинге: %s снова отдаёт метрики, служба в норме (%s). Ложное "
                "срабатывание - обрыв сбора метрик/сети, сама служба не падала.\n\n"
                "Превентивные мероприятия. Можно закрывать." % (svc_label, note))
        return {"mode": "deterministic", "type": atype, "comment": body,
                "reason": "%s: служба жива (%s) - ложное, закрыть" % (atype, note)}
    if alive is False:
        body = (head +
                "Проверил в мониторинге: %s НЕ отдаёт метрики (%s).\n\n"
                "Проверить службу на сервере! Включить, если выключена." % (svc_label, note))
        return {"mode": "deterministic", "type": atype, "comment": body,
                "reason": "%s: служба молчит (%s) - проверить/включить на сервере" % (atype, note)}

    body = (head +
            "%s: автоматически проверить состояние службы не удалось (%s).\n\n"
            "Проверить службу на сервере вручную! Включить, если выключена." % (svc_label, note))
    return {"mode": "deterministic", "type": atype, "comment": body,
            "reason": "%s: не проверить, жива ли служба (%s) - проверить вручную" % (atype, note)}
