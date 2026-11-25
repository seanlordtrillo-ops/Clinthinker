"""The small quiz server that phones connect to during a Classroom Quiz.

It runs only while a quiz is open, listens on the Wi-Fi/hotspot, and offers exactly
four routes: the student page, join, questions (without answers) and submit.
"""
from __future__ import annotations

import json
import os
import socket
import threading
import time

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

from . import classroom

MAX_BODY_BYTES = 64 * 1024
PORT_TRIES = 10
SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": (
        "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"
    ),
}


def _address(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _json(data: dict, status: int = 200) -> JSONResponse:
    return JSONResponse(data, status_code=status, headers=SECURITY_HEADERS)


async def _body(request: Request) -> dict:
    raw = await request.body()
    if len(raw) > MAX_BODY_BYTES:
        raise _Refused(413, "That request is too large.")
    try:
        data = json.loads(raw or b"{}")
    except ValueError as error:
        raise _Refused(400, "Send the form again.") from error
    if not isinstance(data, dict):
        raise _Refused(400, "Send the form again.")
    return data


class _Refused(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _handle(function):
    async def endpoint(request: Request):
        try:
            return _json(await function(request))
        except Exception as error:  # HTTP errors from classroom.py carry a status and message
            status = getattr(error, "status_code", None)
            if status is None:
                return _json({"detail": "Something went wrong. Try again."}, 500)
            return _json({"detail": str(getattr(error, "detail", "")) or "Request refused."}, status)
    return endpoint


async def _page(request: Request):
    return HTMLResponse(STUDENT_PAGE, headers=SECURITY_HEADERS)


async def _join(request: Request) -> dict:
    data = await _body(request)
    return classroom.join(data.get("code", ""), data.get("name", ""), _address(request))


async def _questions(request: Request) -> dict:
    return classroom.questions_for(request.headers.get("x-quiz-token", ""), _address(request))


async def _submit(request: Request) -> dict:
    data = await _body(request)
    return classroom.submit(request.headers.get("x-quiz-token", ""), data.get("answers", {}), _address(request))


async def _status(request: Request) -> dict:
    return classroom.student_status(request.headers.get("x-quiz-token", ""), _address(request))


def build_app() -> Starlette:
    return Starlette(routes=[
        Route("/", _page, methods=["GET"]),
        Route("/api/join", _handle(_join), methods=["POST"]),
        Route("/api/questions", _handle(_questions), methods=["GET"]),
        Route("/api/submit", _handle(_submit), methods=["POST"]),
        Route("/api/status", _handle(_status), methods=["GET"]),
    ])


def local_addresses() -> list[str]:
    """IPv4 addresses phones can use to reach this computer (hotspot first)."""
    found: list[str] = []
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect(("10.255.255.255", 1))  # no packet is sent; this only picks a route
            found.append(probe.getsockname()[0])
        finally:
            probe.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.append(info[4][0])
    except OSError:
        pass
    usable = [
        address for address in dict.fromkeys(found)
        if not address.startswith(("127.", "169.254.", "0."))
    ]
    # Windows Mobile Hotspot gives the laptop 192.168.137.1; list it first when present.
    return sorted(usable, key=lambda address: (not address.startswith("192.168.137."), address))


class QuizServer:
    """Starts and stops the quiz server in a background thread."""

    def __init__(self):
        self.server = None
        self.thread = None
        self.port = None
        self.lock = threading.Lock()

    def start(self, port: int) -> int:
        import uvicorn

        with self.lock:
            if self.server is not None:
                return self.port
            listener = None
            for candidate in range(port, port + PORT_TRIES):
                trial = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                if os.name != "nt":
                    # Lets a restarted quiz reuse the same port right away (Linux/macOS).
                    trial.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                try:
                    trial.bind(("0.0.0.0", candidate))
                    listener = trial
                    break
                except OSError:
                    trial.close()
            if listener is None:
                raise classroom.HTTPException(
                    status_code=409,
                    detail=f"Ports {port}–{port + PORT_TRIES - 1} are busy. Close other apps and try again.",
                )
            server = uvicorn.Server(uvicorn.Config(
                build_app(), host="0.0.0.0", port=listener.getsockname()[1],
                log_level="error", access_log=False, lifespan="off",
            ))
            thread = threading.Thread(
                target=server.run, kwargs={"sockets": [listener]},
                name="clinthinker-classroom-quiz", daemon=True,
            )
            thread.start()
            for _ in range(100):
                if server.started:
                    break
                if not thread.is_alive():
                    break
                time.sleep(0.05)
            if not server.started:
                server.should_exit = True
                raise classroom.HTTPException(status_code=500, detail="The quiz server could not start.")
            self.server, self.thread, self.port = server, thread, listener.getsockname()[1]
            return self.port

    def stop(self) -> None:
        with self.lock:
            if self.server is None:
                return
            self.server.should_exit = True
            if self.thread is not None:
                self.thread.join(timeout=5)
            self.server = self.thread = self.port = None


SERVER = QuizServer()


STUDENT_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Clinthinker Quiz</title>
<style>
  :root { --bg:#100d0a; --card:#1d1814; --line:#3a3129; --text:#f6efe6; --muted:#b7a99a; --accent:#e8b04a; --good:#5fbf7a; --bad:#e46a5d; }
  * { box-sizing:border-box; }
  body { margin:0; font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; background:var(--bg); color:var(--text); }
  main { max-width:640px; margin:0 auto; padding:18px 16px 96px; }
  h1 { font-size:22px; margin:8px 0 4px; }
  p.sub { color:var(--muted); margin:0 0 18px; font-size:14px; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:14px; padding:16px; margin:12px 0; }
  label { display:block; font-size:14px; color:var(--muted); margin:12px 0 6px; }
  input { width:100%; font-size:18px; padding:12px; border-radius:10px; border:1px solid var(--line); background:#0c0a08; color:var(--text); }
  button { font-size:16px; border-radius:10px; border:1px solid var(--line); background:#0c0a08; color:var(--text); padding:12px 14px; width:100%; text-align:left; margin:6px 0; }
  button.primary { background:var(--accent); color:#1b140b; border-color:var(--accent); font-weight:700; text-align:center; }
  button.selected { border-color:var(--accent); background:#2a2117; box-shadow:inset 0 0 0 1px var(--accent); }
  .row { display:flex; gap:10px; } .row button { text-align:center; }
  .q { font-weight:600; margin-bottom:8px; line-height:1.4; }
  .num { color:var(--accent); margin-right:6px; }
  .bar { position:fixed; left:0; right:0; bottom:0; background:rgba(16,13,10,.96); border-top:1px solid var(--line); padding:12px 16px; }
  .bar div { max-width:640px; margin:0 auto; }
  .msg { padding:12px; border-radius:10px; margin:12px 0; font-size:15px; }
  .err { background:#3a1814; color:#ffd6d0; } .ok { background:#14301d; color:#d4f5dd; }
  .score { font-size:44px; font-weight:800; color:var(--accent); margin:8px 0; }
  [hidden] { display:none !important; }
</style>
</head>
<body>
<main>
  <section id="join">
    <h1>Join the quiz</h1>
    <p class="sub">Type your name and the room code your teacher shows.</p>
    <div class="card">
      <label for="name">Your name</label>
      <input id="name" maxlength="40" autocomplete="name">
      <label for="code">Room code</label>
      <input id="code" inputmode="numeric" maxlength="4" pattern="[0-9]*">
      <div id="joinError" class="msg err" hidden></div>
      <button class="primary" id="joinButton" type="button">Join</button>
    </div>
  </section>
  <section id="quiz" hidden>
    <h1 id="title"></h1>
    <p class="sub" id="who"></p>
    <div id="questions"></div>
    <div id="quizError" class="msg err" hidden></div>
  </section>
  <section id="done" hidden>
    <h1>Submitted</h1>
    <div class="card"><p class="sub">Your score</p><div class="score" id="score"></div>
    <p class="sub">You can close this page. Your teacher will review the results.</p></div>
  </section>
  <section id="ended" hidden>
    <h1>The quiz has ended</h1>
    <p class="sub">Ask your teacher if you still need to answer.</p>
  </section>
</main>
<div class="bar" id="bar" hidden><div>
  <div class="sub" id="progress" style="color:var(--muted);font-size:14px;margin-bottom:6px"></div>
  <button class="primary" id="submitButton" type="button">Submit answers</button>
</div></div>
<script>
(function () {
  var store = { get: function (k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
                set: function (k, v) { try { localStorage.setItem(k, v); } catch (e) {} },
                del: function (k) { try { localStorage.removeItem(k); } catch (e) {} } };
  var token = store.get("quizToken"), answers = {}, total = 0;
  try { answers = JSON.parse(store.get("quizAnswers") || "{}") || {}; } catch (e) { answers = {}; }
  function $(id) { return document.getElementById(id); }
  function show(id) { ["join", "quiz", "done", "ended"].forEach(function (s) { $(s).hidden = s !== id; }); $("bar").hidden = id !== "quiz"; }
  function error(el, text) { el.textContent = text; el.hidden = !text; }
  function call(method, path, body) {
    var headers = { "Content-Type": "application/json" };
    if (token) headers["X-Quiz-Token"] = token;
    return fetch(path, { method: method, headers: headers, body: body ? JSON.stringify(body) : undefined })
      .then(function (r) { return r.json().catch(function () { return {}; }).then(function (d) { d._status = r.status; return d; }); });
  }
  function saveAnswers() { store.set("quizAnswers", JSON.stringify(answers)); progress(); }
  function progress() { var n = Object.keys(answers).filter(function (k) { return answers[k] !== ""; }).length; $("progress").textContent = n + " of " + total + " answered"; }
  function choiceButtons(q, box) {
    var letters = "ABCDEFGH";
    var options = q.type === "True or False" ? ["True", "False"] : q.choices;
    var wrap = document.createElement("div"); if (q.type === "True or False") wrap.className = "row";
    options.forEach(function (text, i) {
      var value = q.type === "True or False" ? text : letters[i];
      var b = document.createElement("button"); b.type = "button";
      b.textContent = q.type === "True or False" ? text : letters[i] + ".  " + text;
      if (answers[q.number] === value) b.className = "selected";
      b.addEventListener("click", function () {
        answers[q.number] = value; saveAnswers();
        Array.prototype.forEach.call(wrap.children, function (c) { c.className = ""; }); b.className = "selected";
      });
      wrap.appendChild(b);
    });
    box.appendChild(wrap);
  }
  function render(data) {
    total = data.total; $("title").textContent = data.title;
    $("who").textContent = data.name + " · Set " + data.set + " · " + data.total + " questions";
    var list = $("questions"); list.textContent = "";
    data.questions.forEach(function (q) {
      var card = document.createElement("div"); card.className = "card";
      var head = document.createElement("div"); head.className = "q";
      var num = document.createElement("span"); num.className = "num"; num.textContent = q.number + ".";
      head.appendChild(num); head.appendChild(document.createTextNode(q.text)); card.appendChild(head);
      if (q.type === "Identification") {
        var input = document.createElement("input"); input.maxLength = 200; input.placeholder = "Type your answer";
        input.value = answers[q.number] || "";
        input.addEventListener("input", function () { answers[q.number] = input.value; saveAnswers(); });
        card.appendChild(input);
      } else { choiceButtons(q, card); }
      list.appendChild(card);
    });
    progress(); show("quiz");
  }
  function load() {
    call("GET", "/api/questions").then(function (d) {
      if (d._status === 200) { if (d.submitted) { finish(d.score, d.total); } else { render(d); } return; }
      if (d._status === 410) { show("ended"); return; }
      token = null; store.del("quizToken"); show("join");
    }).catch(function () { show("join"); error($("joinError"), "Can't reach the quiz. Check that you're on the same Wi-Fi or hotspot."); });
  }
  function finish(score, outOf) { $("score").textContent = score + " / " + outOf; store.del("quizAnswers"); show("done"); }
  $("joinButton").addEventListener("click", function () {
    error($("joinError"), "");
    call("POST", "/api/join", { name: $("name").value, code: $("code").value }).then(function (d) {
      if (d._status !== 200) { error($("joinError"), d.detail || "Could not join."); return; }
      token = d.token; store.set("quizToken", token); answers = {}; saveAnswers(); load();
    }).catch(function () { error($("joinError"), "Can't reach the quiz. Check that you're on the same Wi-Fi or hotspot."); });
  });
  $("submitButton").addEventListener("click", function () {
    var answered = Object.keys(answers).filter(function (k) { return answers[k] !== ""; }).length;
    if (answered < total && !window.confirm((total - answered) + " question(s) are unanswered. Submit anyway?")) return;
    error($("quizError"), "");
    call("POST", "/api/submit", { answers: answers }).then(function (d) {
      if (d._status === 200) { finish(d.score, d.total); return; }
      if (d._status === 410) { show("ended"); return; }
      error($("quizError"), d.detail || "Could not submit. Try again.");
    }).catch(function () { error($("quizError"), "Connection lost. Your answers are saved on this phone — try Submit again."); });
  });
  if (token) { load(); } else { show("join"); }
})();
</script>
</body>
</html>
"""
