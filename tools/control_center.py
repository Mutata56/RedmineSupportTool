#!/usr/bin/env python3
# -*- coding: utf-8 -*-


import argparse
import json
import os
import re
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_CODE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _CODE_ROOT)
from agent import approvals

ROOT = os.environ.get("WA_CC_ROOT") or _CODE_ROOT
_TICKET_KEY = re.compile(r"^(ticket|default|opus)-(\d+)$")
PIPE_LABEL = {"ticket": "алерт", "default": "default", "opus": "opus"}
DETAIL_CAP = 20000


def _redmine_url(root):
    try:
        with open(os.path.join(root, "config", "secrets.local.json"), encoding="utf-8") as f:
            return (json.load(f).get("redmine_url") or "").rstrip("/")
    except Exception:
        return ""


def _read_jsonl(path, max_bytes=6_000_000):

    out = []
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            if size > max_bytes:
                f.seek(size - max_bytes)
                f.readline()
            for raw in f:
                try:
                    rec = json.loads(raw.decode("utf-8", "replace"))
                except json.JSONDecodeError:
                    continue
                if isinstance(rec, dict):
                    out.append(rec)
    except OSError:
        pass
    return out


def _num(v):


    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def build_feed(root=None, limit=300):


    root = root or ROOT
    recs = _read_jsonl(os.path.join(root, "state", "processed.jsonl"))
    ent = {}
    for r in recs:
        key = str(r.get("message_id") or "?")
        if key not in ent:
            m = _TICKET_KEY.match(key)
            ent[key] = {"key": key,
                        "kind": "ticket" if m else "mail",
                        "pipe": PIPE_LABEL.get(m.group(1)) if m else None,
                        "entity_id": int(m.group(2)) if m else None,
                        "subject": "", "issue_id": None, "records": []}
        e = ent[key]
        detail = r.get("detail")
        if detail and len(detail) > DETAIL_CAP:
            detail = detail[:DETAIL_CAP] + "\n… (обрезано)"


        e["records"].append({"ts": _num(r.get("ts")), "at": r.get("at") or "",
                             "verdict": r.get("verdict") or "", "note": r.get("note") or "",
                             "rule": r.get("rule"), "issue_id": r.get("issue_id"),
                             "interim": bool(r.get("interim")), "detail": detail})
        if r.get("subject"):
            e["subject"] = r["subject"]
        if r.get("issue_id"):
            e["issue_id"] = r["issue_id"]
    entities = list(ent.values())
    for e in entities:
        e["records"].sort(key=lambda x: x["ts"])
        term = [r for r in e["records"] if not r["interim"]]
        head = (term or e["records"])[-1]
        last = e["records"][-1]
        e["last_ts"], e["last_at"] = last["ts"], last["at"]
        e["verdict"], e["note"] = head["verdict"], head["note"]
        if e["kind"] == "ticket" and not e["issue_id"]:
            e["issue_id"] = e["entity_id"]
    entities.sort(key=lambda x: -x["last_ts"])
    pend = [ap for ap in approvals.load_all(root) if ap.get("status") == "pending"]
    for ap in pend:
        if len(ap.get("proposal") or "") > DETAIL_CAP:
            ap["proposal"] = ap["proposal"][:DETAIL_CAP] + "\n… (обрезано)"
    pend.sort(key=lambda a: a.get("created_at", ""), reverse=True)
    return {"mails": [e for e in entities if e["kind"] == "mail"][:limit],
            "tickets": [e for e in entities if e["kind"] == "ticket"][:limit],
            "approvals": pend,
            "redmine_url": _redmine_url(root)}


def read_logs(root=None, q="", n=400):

    root = root or ROOT
    recs = _read_jsonl(os.path.join(root, "logs", "agent.jsonl"))
    if q:
        ql = q.lower()
        recs = [r for r in recs if ql in str(r.get("msg", "")).lower()
                or ql in str(r.get("exc", "")).lower()]
    try:
        n = max(1, min(int(n), 5000))
    except (TypeError, ValueError):
        n = 400
    return recs[-n:]


PAGE = """<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>work_agent - центр управления</title>
<style>
 :root{
  --bg:#0b0e14; --surface:#121722; --surface2:#171d2b; --line:#1f2735; --line2:#2a3448;
  --fg:#e2e8f4; --dim:#94a0b8; --faint:#5c677d; --link:#7aabff;
  --ok:#4ade80; --dry:#7ea6e0; --skip:#8b94a7; --mute:#5c677d;
  --warn:#fbbf24; --err:#f87171; --ai:#c084fc; --veto:#fb923c; --step:#60a5fa;
 }
 *{box-sizing:border-box}
 body{margin:0;background:var(--bg);color:var(--fg);
      font:14px/1.5 -apple-system,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif}
 header{display:flex;gap:20px;align-items:center;padding:0 24px;height:56px;
        border-bottom:1px solid var(--line);position:sticky;top:0;background:rgba(11,14,20,.92);
        backdrop-filter:blur(8px);z-index:10}
 .brand{font-size:15px;font-weight:700;letter-spacing:.3px}
 .brand small{color:var(--faint);font-weight:400;margin-left:8px}
 nav{display:flex;background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:3px}
 nav button{background:none;border:0;color:var(--dim);padding:7px 18px;border-radius:8px;
            cursor:pointer;font-size:13px;font-weight:600;transition:all .15s}
 nav button.on{background:var(--surface2);color:var(--fg);box-shadow:0 1px 3px rgba(0,0,0,.4)}
 nav button:hover:not(.on){color:var(--fg)}
 .stats{display:flex;gap:8px;flex-wrap:wrap;margin-left:auto}
 .stat{font-size:11.5px;color:var(--dim);background:var(--surface);border:1px solid var(--line);
       border-radius:8px;padding:4px 10px}
 .stat b{color:var(--fg);font-weight:600}
 #upd{font-size:11.5px;color:var(--faint);white-space:nowrap}
 main{max-width:1240px;margin:0 auto;padding:18px 24px 80px}
 .toolbar{display:flex;gap:10px;margin-bottom:14px;align-items:center}
 input[type=text]{background:var(--surface);border:1px solid var(--line);color:var(--fg);
    border-radius:9px;padding:8px 12px;font-size:13px;min-width:320px;outline:none}
 input[type=text]:focus{border-color:var(--line2)}
 .btn{background:var(--surface);border:1px solid var(--line);color:var(--dim);border-radius:9px;
      padding:8px 14px;font-size:12.5px;cursor:pointer}
 .btn:hover{color:var(--fg);border-color:var(--line2)}
 /* карточка сущности */
 .item{background:var(--surface);border:1px solid var(--line);border-radius:12px;
       margin-bottom:10px;overflow:hidden;transition:border-color .15s}
 .item:hover{border-color:var(--line2)}
 .head{display:grid;grid-template-columns:150px auto auto 1fr auto;gap:12px;align-items:center;
       padding:12px 16px;cursor:pointer}
 .time{color:var(--faint);font-size:12px;font-variant-numeric:tabular-nums}
 .badge{font-size:11px;font-weight:600;padding:3px 10px;border-radius:20px;white-space:nowrap;
        justify-self:start}
 .chip{font-size:10.5px;font-weight:600;color:var(--dim);border:1px solid var(--line2);
       border-radius:6px;padding:2px 7px;text-transform:uppercase;letter-spacing:.4px}
 .subj{font-weight:600;font-size:13.5px;overflow-wrap:anywhere}
 .subj a{color:var(--link);text-decoration:none;font-weight:600;margin-left:8px;font-size:12.5px}
 .subj a:hover{text-decoration:underline}
 .note{grid-column:1/-1;color:var(--dim);font-size:12.5px;margin-top:-4px;padding:0 16px 10px;
       overflow-wrap:anywhere}
 .arr{color:var(--faint);font-size:11px;transition:transform .15s}
 .item.open .arr{transform:rotate(90deg)}
 /* жизненный цикл */
 .life{display:none;border-top:1px solid var(--line);background:var(--surface2);padding:16px 20px}
 .item.open .life{display:block}
 .lifehead{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px}
 .lifehead h4{margin:0;font-size:12px;color:var(--faint);font-weight:600;
              text-transform:uppercase;letter-spacing:.6px}
 .step{display:grid;grid-template-columns:26px 1fr;gap:12px;position:relative;padding-bottom:16px}
 .step:last-child{padding-bottom:2px}
 .step::before{content:"";position:absolute;left:12px;top:26px;bottom:0;width:1.5px;
               background:var(--line2)}
 .step:last-child::before{display:none}
 .dot{width:25px;height:25px;border-radius:50%;background:var(--surface);border:1.5px solid var(--line2);
      display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;
      color:var(--dim);z-index:1}
 .sbody{padding-top:2px}
 .srow{display:flex;gap:10px;align-items:baseline;flex-wrap:wrap}
 .stitle{font-weight:600;font-size:13px}
 .stime{color:var(--faint);font-size:11.5px;font-variant-numeric:tabular-nums}
 .snote{color:var(--dim);font-size:12.5px;margin-top:2px;overflow-wrap:anywhere}
 details.doc{margin-top:8px}
 details.doc summary{cursor:pointer;font-size:12px;color:var(--link);user-select:none}
 details.doc pre{background:var(--bg);border:1px solid var(--line);border-radius:9px;
    padding:12px 14px;margin:8px 0 0;font:12px/1.55 ui-monospace,'Cascadia Code',Consolas,monospace;
    white-space:pre-wrap;overflow-wrap:anywhere;max-height:440px;overflow:auto;color:#cdd6e8}
 /* логи */
 .log{font:12px/1.55 ui-monospace,Consolas,monospace;padding:4px 10px;
      border-left:3px solid var(--line);margin:3px 0;overflow-wrap:anywhere;white-space:pre-wrap;
      background:var(--surface);border-radius:0 8px 8px 0}
 .log.WARNING{border-left-color:var(--warn)} .log.ERROR,.log.CRITICAL{border-left-color:var(--err)}
 .log .lg{color:var(--faint)}
 .empty{color:var(--faint);text-align:center;padding:60px 0;font-size:13px}
</style></head><body>
<header>
 <span class="brand">work_agent<small>центр управления</small></span>
 <nav>
  <button id="tb_mails" onclick="show('mails')">Письма</button>
  <button id="tb_tickets" onclick="show('tickets')">Заявки</button>
  <button id="tb_apps" onclick="show('apps')">Решения</button>
  <button id="tb_logs" onclick="show('logs')">Логи</button>
 </nav>
 <div class="stats" id="stats"></div>
 <span id="upd"></span>
</header>
<main>
 <div class="toolbar">
  <input type="text" id="q" placeholder="поиск..."
         onkeydown="if(event.key==='Enter')refresh()">
  <button class="btn" onclick="refresh()">искать</button>
  <button class="btn" onclick="document.getElementById('q').value='';refresh()">сброс</button>
 </div>
 <div id="content"><div class="empty">загрузка…</div></div>
</main>
<script>
const V = {
 routed:["step","распознано и замаршрутизировано"],
 created:["ok","создана заявка"], dry_run_create:["dry","создал бы заявку (dry-run)"],
 issue_taken:["ok","взята в работу"], taken_in_work:["ok","взята в работу"],
 note_posted:["ok","написан приватный комментарий"],
 duplicate:["skip","дубль: уже есть в дашборде"], stale_skipped:["skip","устарело - не берём"],
 no_marker:["mute","нет маркера - не наше письмо"], blacklisted:["mute","чёрный список"],
 unknown_server:["warn","сервер не распознан"], error:["err","ошибка обработки"],
 grafana_attached:["ok","приложены графики"], grafana_dry_run:["dry","взял бы (dry-run)"],
 grafana_error:["warn","в работе, графики не приложились"],
 ticket_taken:["ok","взята в работу (без графиков)"], ticket_no_match:["mute","не наш алерт"],
 ticket_stale:["skip","старый алерт - не берём"], ticket_status_skip:["skip","статус не берём"],
 ticket_no_date:["skip","дата не распозналась"],
 storm_grouped:["warn","шторм: взята и связана"], storm_dry_run:["dry","шторм (dry-run)"],
 llm_analysis:["ai","написан разбор Sonnet"],
 llm_low_confidence:["veto","ИИ не уверен - в Redmine не писали"],
 default_dispatched:["ai","Opus-анализ запущен"], default_done:["ai","Opus-анализ готов"],
 default_low_confidence:["veto","Opus не уверен - коммент не публиковался"],
 default_error:["err","Opus-анализ упал"], default_dry:["dry","default (dry-run)"],
 approval_requested:["warn","ждёт твоего решения"],
 approved:["ok","запись одобрена"],
 opus_requested:["ai","запрос на запуск Opus"],
 opus_launched:["ai","Opus запущен"],
 opus_launched_dry:["dry","одобрено, DRY - Opus не запускался"],
 opus_declined:["mute","Opus не запускать"],
 ignored:["mute","игнор - помечено обработанным"],
 manual_decision:["mute","решение: вручную, ничего не делаем"]};
let tab="mails", feed=null;
// ОДИНАРНАЯ кавычка тоже экранируется: атрибуты вида onclick='...' обрамлены именно ей,
// и тема письма с апострофом («x' onmouseover=alert(1) '») выходила из атрибута.
const esc = s => String(s??"").replace(/[&<>"']/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[m]));
const vinfo = v => V[v]||["mute",v];
function badge(v){const [c,t]=vinfo(v);
 return `<span class="badge" style="color:var(--${c});background:color-mix(in srgb,var(--${c}) 12%,transparent);border:1px solid color-mix(in srgb,var(--${c}) 35%,transparent)">${esc(t)}</span>`}
function show(t){tab=t;location.hash=t;
 for(const b of ["mails","tickets","apps","logs"])
  document.getElementById("tb_"+b).classList.toggle("on",b===t);
 document.getElementById("q").placeholder = t==="logs"?"фильтр логов (Enter)…":"поиск по теме…";
 refresh();}
function logsFor(q,ev){ev.stopPropagation();document.getElementById("q").value=q;show("logs")}
function toggle(el){el.closest(".item").classList.toggle("open")}
function lifecycle(e){
 return e.records.map((r,i)=>{
  const doc = r.detail?`<details class="doc"><summary>полный текст (${r.detail.length} симв.)</summary><pre>${esc(r.detail)}</pre></details>`:"";
  return `<div class="step"><div class="dot">${i+1}</div><div class="sbody">
    <div class="srow"><span class="stitle">${esc(vinfo(r.verdict)[1])}</span>
    <span class="stime">${esc(r.at)}</span></div>
    <div class="snote">${esc(r.note||"")}</div>${doc}</div></div>`}).join("");}
function entity(e){
 const link = e.issue_id && feed.redmine_url
   ? `<a href="${feed.redmine_url}/issues/${e.issue_id}" target="_blank" onclick="event.stopPropagation()">#${e.issue_id} ↗</a>`:"";
 const pipe = e.pipe?`<span class="chip">${esc(e.pipe)}</span>`:`<span class="chip">почта</span>`;
 const lq = e.kind==="ticket"?("#"+e.entity_id):(e.subject||"").slice(0,30);
 const iid = e.issue_id || e.entity_id;
 const opusCtrl = (e.kind==="ticket" && iid) ? `<div class="note" style="padding-top:0">
    <button class="btn" style="padding:4px 10px;color:var(--ai)" onclick="opusToggle(${iid});event.stopPropagation()">🤖 Вызвать Opus</button>
    <div id="opf_${iid}" style="display:none;margin-top:10px">
     <textarea id="opt_${iid}" data-subject="${esc(e.subject||"")}" rows="3"
       placeholder="инструкция для Opus (пусто = пусть сам ищет похожие заявки)"
       style="width:100%;background:var(--surface);border:1px solid var(--line);color:var(--fg);border-radius:9px;padding:8px 12px;font:13px/1.5 inherit;outline:none;resize:vertical"></textarea>
     <div style="margin-top:8px;display:flex;gap:10px">
      <button class="btn" style="color:#fff;background:var(--ai);border-color:var(--ai)" onclick="invokeOpus(${iid})">🤖 Запустить</button>
      <button class="btn" onclick="opusToggle(${iid})">Отмена</button>
     </div></div></div>` : "";
 return `<div class="item"><div class="head" onclick="toggle(this)">
   <span class="time">${esc(e.last_at)}</span>${pipe}${badge(e.verdict)}
   <span class="subj">${esc(e.subject||"(без темы)")}${link}</span>
   <span class="arr">▶</span></div>
  <div class="note">${esc(e.note||"")}</div>
  ${opusCtrl}
  <div class="life"><div class="lifehead"><h4>Жизненный цикл</h4>
   <button class="btn" style="padding:4px 10px" onclick='logsFor(${esc(JSON.stringify(lq))},event)'>логи сущности</button></div>
   ${lifecycle(e)}</div></div>`}
const pipeLbl = p => p==="opus"?"opus":p||"заявка";
function appKind(a){
 if(a.pipe==="opus")return "opus";
 return "legacy";}
function appTitle(a){const k=appKind(a);
 if(k==="opus")return ({default:"Незнакомая заявка — запустить Opus?",
   alert:"Разбор алерта неуверенный — запустить Opus?",manual:"Ручной запуск Opus"})[a.reason]||"Запустить Opus?";
 return "Запрос одобрения";}
function appBadgeV(a){const k=appKind(a);
 return k==="opus"?"opus_requested":"approval_requested";}
function approvalCard(a){
 const iid=a.issue_id, k=appKind(a);
 const link = feed.redmine_url
   ? `<a href="${feed.redmine_url}/issues/${iid}" target="_blank">#${iid} ↗</a>` : "#"+iid;
 const accent = k==="opus"?"--ai":"--warn";
 const plabel = k==="opus"?"заявка" : "что будет выполнено";
 const opusPrompt = (k==="opus" && a.prompt)
   ? `<details class="doc" open><summary>Инструкция Opus</summary><pre>${esc(a.prompt)}</pre></details>` : "";
 let buttons;
 if(k==="opus"){
  buttons = `<button class="btn" style="color:#fff;background:var(--ai);border-color:var(--ai)"
      onclick="decide(${iid},'approved','Запустить Opus по заявке #${iid}?')">🤖 Запустить Opus</button>
    <button class="btn" onclick="decide(${iid},'ignore')">🚫 Не запускать / игнор</button>
    <button class="btn" style="color:var(--warn)" onclick="decide(${iid},'manual')">✋ Вручную</button>`;
 }else{
  buttons = `<button class="btn" style="color:var(--ok);border-color:var(--ok)"
      onclick="decide(${iid},'approved')">✅ Одобрить и выполнить</button>
    <button class="btn" style="color:var(--warn)" onclick="decide(${iid},'manual')">✋ Вручную</button>
    <button class="btn" onclick="decide(${iid},'ignore')">🚫 Игнор</button>`;
 }
 return `<div class="item" style="border-color:color-mix(in srgb,var(${accent}) 45%,var(--line))">
  <div class="head" style="cursor:default">
   <span class="time">${esc(a.created_at||"")}</span>
   <span class="chip">${esc(pipeLbl(a.pipe))}</span>${badge(appBadgeV(a))}
   <span class="subj" style="color:var(${accent})">${esc(appTitle(a))}</span><span></span></div>
  <div class="life" style="display:block">
   <div class="snote" style="margin-bottom:8px"><b>${esc(a.subject||"(без темы)")}</b> ${link}</div>
   ${opusPrompt}
   <details class="doc" open><summary>предпросмотр: ${esc(plabel)}</summary>
    <pre>${esc(a.proposal||"(нет предпросмотра)")}</pre></details>
   <div style="display:flex;gap:10px;margin-top:14px;flex-wrap:wrap">${buttons}</div>
  </div></div>`}
async function decide(iid,decision,confirmMsg){
 const q = confirmMsg || ({
   approved:'Одобрить действие по заявке #'+iid+'?',
   manual:'Решение «вручную»: агент по заявке #'+iid+' ничего делать не будет. Подтвердить?',
   ignore:'Игнорировать заявку #'+iid+'? Будет помечена обработанной, ничего не выполняем.'
 })[decision];
 if(q&&!confirm(q))return;
 try{
  const r=await fetch('/api/decide',{method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({issue_id:iid,decision:decision})});
  const j=await r.json();
  if(!j.ok)alert('Не получилось: '+j.error);
 }catch(e){alert('Ошибка запроса: '+e)}
 refresh();}
function opusToggle(iid){const b=document.getElementById('opf_'+iid);
 if(b)b.style.display = b.style.display==='none'?'block':'none';}
async function invokeOpus(iid){
 const ta=document.getElementById('opt_'+iid);
 const prompt=ta?ta.value:'', subj=ta?(ta.dataset.subject||''):'';
 if(!confirm('Вызвать Opus по заявке #'+iid+(prompt.trim()?' с вашей инструкцией?':' (Opus сам подберёт похожие заявки)?')))return;
 try{
  const r=await fetch('/api/invoke_opus',{method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({issue_id:iid,subject:subj,prompt:prompt})});
  const j=await r.json();
  if(!j.ok){alert('Не получилось: '+j.error);return;}
  alert('Запрос на Opus по #'+iid+' создан.');
 }catch(e){alert('Ошибка запроса: '+e)}
 refresh();}
function render(){
 if(!feed)return;
 // подстраховка: показываем только pending (build_feed уже фильтрует, но мало ли)
 const apps=(feed.approvals||[]).filter(a=>(a.status||"pending")==="pending");
 document.getElementById("tb_apps").textContent =
   "Решения"+(apps.length?` (${apps.length})`:"");
 if(tab==="apps"){
  document.getElementById("content").innerHTML = apps.length
    ? apps.map(approvalCard).join("")
    : '<div class="empty">запросов на одобрение нет</div>';
 } else {
 const q=(document.getElementById("q").value||"").toLowerCase();
 let list = tab==="mails"?feed.mails:feed.tickets;
 if(q) list=list.filter(e=>(e.subject+" "+e.note).toLowerCase().includes(q));
 document.getElementById("content").innerHTML = list.length? list.map(entity).join("") :
   '<div class="empty">пусто - агент ещё ничего не обработал (или ничего не нашлось по фильтру)</div>';
 }
 const day=Date.now()/1000-86400;
 const fresh=[...feed.mails,...feed.tickets].flatMap(e=>e.records).filter(r=>r.ts>day);
 const n=v=>fresh.filter(r=>r.verdict===v).length;
 const veto=n("llm_low_confidence")+n("default_low_confidence");
 document.getElementById("stats").innerHTML =
  (apps.length?`<span class="stat" style="border-color:var(--warn)">ждут решения <b>${apps.length}</b></span>`:"")+
  `<span class="stat">24ч: письма <b>${feed.mails.filter(e=>e.last_ts>day).length}</b></span>`+
  `<span class="stat">заявки <b>${feed.tickets.filter(e=>e.last_ts>day).length}</b></span>`+
  `<span class="stat">создано <b>${n("created")+n("dry_run_create")}</b></span>`+
  `<span class="stat">дубли <b>${n("duplicate")}</b></span>`+
  `<span class="stat">ИИ-вето <b>${veto}</b></span>`+
  `<span class="stat">ошибки <b>${n("error")+n("default_error")}</b></span>`;}
async function refresh(){
 if(tab==="logs"){
  const q=document.getElementById("q").value;
  try{const logs=await (await fetch("/api/logs?n=600&q="+encodeURIComponent(q))).json();
   document.getElementById("content").innerHTML = logs.length? logs.map(r=>
    `<div class="log ${esc(r.level)}"><span class="lg">${esc(r.at)} ${esc(r.level)} [${esc(r.logger)}]</span> ${esc(r.msg)}`+
    (r.exc?`\\n<span style="color:var(--err)">${esc(r.exc)}</span>`:"")+`</div>`).join("") :
    '<div class="empty">ничего не найдено</div>';
   stamp();}catch(e){}
 }else{
  try{feed=await (await fetch("/api/feed")).json();render();stamp();}catch(e){}
 }}
function stamp(){document.getElementById("upd").textContent="обновлено "+new Date().toLocaleTimeString()}
setInterval(refresh,10000);
show(["mails","tickets","apps","logs"].includes(location.hash.slice(1))?location.hash.slice(1):"mails");
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(u.query)
        if u.path == "/":
            body, ctype = PAGE.encode("utf-8"), "text/html; charset=utf-8"
        elif u.path == "/api/feed":
            try:
                limit = int((qs.get("limit") or ["300"])[0])
            except ValueError:
                limit = 300
            body = json.dumps(build_feed(limit=limit), ensure_ascii=False).encode("utf-8")
            ctype = "application/json; charset=utf-8"
        elif u.path == "/api/logs":
            body = json.dumps(read_logs(q=(qs.get("q") or [""])[0],
                                        n=(qs.get("n") or ["400"])[0]),
                              ensure_ascii=False).encode("utf-8")
            ctype = "application/json; charset=utf-8"
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):


        origin = self.headers.get("Origin") or self.headers.get("Referer")
        if origin:
            host = urllib.parse.urlsplit(origin).hostname
            if host not in ("127.0.0.1", "localhost", "::1"):
                body = json.dumps({"ok": False, "error": "cross-origin запрос отклонён"},
                                  ensure_ascii=False).encode("utf-8")
                self.send_response(403)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
        u = urllib.parse.urlparse(self.path)
        if u.path not in ("/api/decide", "/api/invoke_opus"):
            self.send_error(404)
            return
        try:
            n = int(self.headers.get("Content-Length") or 0)
            data = json.loads(self.rfile.read(n).decode("utf-8"))
            if u.path == "/api/decide":
                ok, err = approvals.decide(ROOT, int(data.get("issue_id")),
                                           str(data.get("decision") or ""))
            else:
                ok, err = approvals.create_manual_opus(
                    ROOT, int(data.get("issue_id")),
                    str(data.get("subject") or ""), str(data.get("prompt") or ""))
        except Exception as e:
            ok, err = False, "битый запрос: %s" % e
        body = json.dumps({"ok": ok, "error": err}, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def main():
    ap = argparse.ArgumentParser(description="центр управления work_agent (read-only GUI)")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print("центр управления: http://127.0.0.1:%d  (Ctrl+C для остановки)" % args.port)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
