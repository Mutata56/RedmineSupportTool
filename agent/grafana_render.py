# -*- coding: utf-8 -*-


import base64
import json
import os
import shutil
import signal
import socket
import subprocess
import tempfile
import time
import urllib.request

import websocket

BROWSER_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]

_LINUX_BROWSERS = ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable",
                   "brave", "brave-browser", "microsoft-edge", "microsoft-edge-stable")


READY_JS = """(function () {
  try {
    if (location.pathname.indexOf('/login') >= 0) return 'login';
    if (document.querySelector('.panel-loading')) return 'wait';
    var panel = document.querySelector('[data-panelid], .panel-container, .panel-solo, .dashboard-solo');
    if (!panel) return 'wait';
    var txt = (panel.innerText || '');
    var canv = document.querySelectorAll('canvas').length;
    if (/no data/i.test(txt) && !canv) return 'nodata';
    if (canv > 0) return 'ready';
    if (txt.replace(/\\s+/g, '').length > 3) return 'ready';
    return 'wait';
  } catch (e) { return 'wait'; }
})()"""


HOVER_JS = """(function () {
  try {
    function fire(el, type, x, y) {
      el.dispatchEvent(new MouseEvent(type, {clientX: x, clientY: y,
        bubbles: true, cancelable: true, view: window}));
    }
    var o = document.querySelector('.flot-overlay') || document.querySelector('.u-over');
    if (!o) return 'no-overlay';
    var r = o.getBoundingClientRect();
    var y = r.top + r.height / 2;
    fire(o, 'mouseenter', r.left + r.width * 0.5, y);
    var xs = [0.5, 0.7, 0.85, 0.93, 0.97];
    for (var i = 0; i < xs.length; i++) {
      fire(o, 'mousemove', r.left + r.width * xs[i], y);
    }
    return 'ok';
  } catch (e) { return 'err'; }
})()"""


def find_browser(configured=""):
    if configured:
        if os.path.exists(configured):
            return configured
        w = shutil.which(configured)
        if w:
            return w
    for p in BROWSER_CANDIDATES:
        if os.path.exists(p):
            return p
    for name in _LINUX_BROWSERS:
        w = shutil.which(name)
        if w:
            return w
    raise RuntimeError("не найден браузер для headless-рендера "
                       "(Windows: Edge/Chrome; Linux: chromium/google-chrome/brave). "
                       "Установить на Linux: apt install chromium | pacman -S chromium")


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class HeadlessBrowser:


    def __init__(self, browser_path, log=None):
        self.log = log
        self.port = _free_port()
        self.profile = tempfile.mkdtemp(prefix="wa_grafana_")
        args = [browser_path, "--headless=new", "--disable-gpu", "--no-first-run",
                "--no-default-browser-check", "--mute-audio",
                "--remote-debugging-port=%d" % self.port,
                "--user-data-dir=%s" % self.profile,
                "--window-size=1280,760"]
        if os.name != "nt":

            args += ["--no-sandbox", "--disable-dev-shm-usage"]
        args.append("about:blank")

        self.proc = subprocess.Popen(
            args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=(os.name != "nt"))
        self.ws = None
        self._id = 0
        self.session = None
        self._connect()

    def _connect(self):
        ws_url = None
        for _ in range(40):
            try:
                with urllib.request.urlopen("http://127.0.0.1:%d/json/version" % self.port, timeout=2) as r:
                    ws_url = json.loads(r.read().decode()).get("webSocketDebuggerUrl")
                if ws_url:
                    break
            except Exception:
                time.sleep(0.5)
        if not ws_url:
            self.close()
            raise RuntimeError("headless-браузер не поднялся (CDP не отвечает)")
        try:
            self.ws = websocket.create_connection(ws_url, timeout=60, suppress_origin=True)
            target = self._cmd("Target.createTarget", {"url": "about:blank"})
            attach = self._cmd("Target.attachToTarget",
                               {"targetId": target["targetId"], "flatten": True})
            self.session = attach["sessionId"]
            self._cmd("Network.enable", {}, session=True)
            self._cmd("Page.enable", {}, session=True)
        except Exception:

            self.close()
            raise

    def _cmd(self, method, params=None, session=False):
        self._id += 1
        msg = {"id": self._id, "method": method, "params": params or {}}
        if session and self.session:
            msg["sessionId"] = self.session
        self.ws.send(json.dumps(msg))
        deadline = time.time() + 90
        while time.time() < deadline:
            data = json.loads(self.ws.recv())
            if data.get("id") == self._id:
                if "error" in data:
                    raise RuntimeError("CDP %s: %s" % (method, data["error"].get("message")))
                return data.get("result", {})

        raise RuntimeError("CDP %s: таймаут ответа" % method)

    def set_cookie(self, name, value, domain):
        self._cmd("Network.setCookie",
                  {"name": name, "value": value, "domain": domain, "path": "/"},
                  session=True)

    def render(self, url, out_png, width=1100, height=520, scale=2, timeout=45, settle=1.5,
               hover=True):


        self._cmd("Emulation.setDeviceMetricsOverride",
                  {"width": width, "height": height, "deviceScaleFactor": scale, "mobile": False},
                  session=True)
        self._cmd("Page.navigate", {"url": url}, session=True)
        state = "wait"
        timed_out = True
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                r = self._cmd("Runtime.evaluate",
                              {"expression": READY_JS, "returnByValue": True}, session=True)
                state = (r.get("result") or {}).get("value") or "wait"
            except Exception:
                state = "wait"
            if state in ("ready", "nodata", "login"):
                timed_out = False
                break
            time.sleep(0.5)


        if timed_out:
            return "timeout"
        if state == "login":
            return "login"
        time.sleep(settle)
        if hover and state == "ready":
            try:
                self._cmd("Runtime.evaluate",
                          {"expression": HOVER_JS, "returnByValue": True}, session=True)
                time.sleep(0.6)
            except Exception:
                pass
        shot = self._cmd("Page.captureScreenshot",
                         {"format": "png", "captureBeyondViewport": True}, session=True)
        with open(out_png, "wb") as f:
            f.write(base64.b64decode(shot["data"]))
        return "ok" if state == "ready" else "nodata"

    def close(self):
        try:
            if self.ws:
                self.ws.close()
        except Exception:
            pass
        proc = getattr(self, "proc", None)
        if proc:


            try:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
                else:
                    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except Exception:
                pass
            try:
                proc.terminate()
                proc.wait(timeout=10)
            except Exception:
                try:
                    if os.name != "nt":
                        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                    else:
                        proc.kill()
                except Exception:
                    pass
        prof = getattr(self, "profile", None)
        if prof:
            shutil.rmtree(prof, ignore_errors=True)
