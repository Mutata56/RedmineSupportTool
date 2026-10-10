# -*- coding: utf-8 -*-


from collections import namedtuple
from datetime import datetime, timezone


Ctx = namedtuple("Ctx", [
    "root",
    "alert_overrides",
    "approval_held",
    "trig",
    "fresh",
    "alert_re",
    "req_tracker",
    "gf_tracker",
    "alert_excl",
    "alerts_on", "default_on",
    "deferred_178",
    "ticket_created",
])


Decision = namedtuple("Decision", [
    "branch",
    "key",
    "force",
], defaults=[None, False])


def is_alert(issue, ctx):


    pj = issue.get("project", {}).get("name", "")
    return bool(ctx.alert_re.search(issue.get("subject", "")) or
                (issue.get("tracker", {}).get("id") == ctx.gf_tracker
                 and not any(x and x in pj for x in ctx.alert_excl)))


def classify_ticket(issue, ctx, ap):


    iid = issue["id"]


    if ap and ap.get("pipe") == "opus":
        return Decision(branch="opus")


    manual_alert = iid in ctx.alert_overrides
    if manual_alert or (ctx.alerts_on and is_alert(issue, ctx)):
        return Decision(branch="alert", key="ticket-%d" % iid, force=manual_alert)


    if issue.get("tracker", {}).get("id") != ctx.req_tracker:
        return Decision(branch="skip")
    if not ctx.default_on or is_alert(issue, ctx):
        return Decision(branch="skip")


    if (issue.get("status", {}).get("id") not in ctx.trig and iid not in ctx.approval_held):
        return Decision(branch="skip")

    cr = ctx.ticket_created(issue)
    if cr is None:
        return Decision(branch="skip")


    ref_ts = ctx.deferred_178.get(iid)
    ref = (datetime.fromtimestamp(ref_ts, timezone.utc) if ref_ts
           else datetime.now(timezone.utc))
    if ((ref - cr).total_seconds() / 60.0 > ctx.fresh
            and iid not in ctx.approval_held):
        return Decision(branch="skip")

    return Decision(branch="default", key="default-%d" % iid)
