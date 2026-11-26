"""The small quiz server that phones connect to during a Classroom Quiz.

It runs only while a quiz is open, listens on the Wi-Fi/hotspot, and offers only the
student page, join, questions (without answers), submit, status, "left the page"
reports and, after the teacher allows it, a student's own corrections.
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


async def _away(request: Request) -> dict:
    data = await _body(request)
    return classroom.report_away(request.headers.get("x-quiz-token", ""), data.get("away") is True, _address(request))


async def _review(request: Request) -> dict:
    return classroom.review_for(request.headers.get("x-quiz-token", ""), _address(request))


def build_app() -> Starlette:
    return Starlette(routes=[
        Route("/", _page, methods=["GET"]),
        Route("/api/join", _handle(_join), methods=["POST"]),
        Route("/api/questions", _handle(_questions), methods=["GET"]),
        Route("/api/submit", _handle(_submit), methods=["POST"]),
        Route("/api/status", _handle(_status), methods=["GET"]),
        Route("/api/away", _handle(_away), methods=["POST"]),
        Route("/api/review", _handle(_review), methods=["GET"]),
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
  main { max-width:640px; margin:0 auto; padding:18px 16px 110px; }
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
  .barline { display:flex; justify-content:space-between; color:var(--muted); font-size:14px; margin-bottom:6px; }
  .timer { font-weight:700; color:var(--text); font-variant-numeric:tabular-nums; }
  .timer.low { color:var(--bad); }
  .msg { padding:12px; border-radius:10px; margin:12px 0; font-size:15px; }
  .err { background:#3a1814; color:#ffd6d0; } .ok { background:#14301d; color:#d4f5dd; } .info { background:#2a2117; color:var(--text); }
  .score { font-size:44px; font-weight:800; color:var(--accent); margin:8px 0; }
  .mark { font-weight:800; margin-right:6px; } .mark.right { color:var(--good); } .mark.wrong { color:var(--bad); }
  .line { font-size:15px; margin:4px 0; color:var(--muted); } .line b { color:var(--text); font-weight:600; }
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
    <div class="msg info" id="stayNote">Stay on this page until you submit. Your teacher can see if you leave it.</div>
    <div id="questions"></div>
    <div id="quizError" class="msg err" hidden></div>
  </section>
  <section id="done" hidden>
    <h1>Submitted</h1>
    <div class="card"><p class="sub">Your score</p><div class="score" id="score"></div>
    <p class="sub" id="doneNote">You can keep this page open. If your teacher shows the answers, your corrections will appear here.</p>
    <div id="doneMsg" class="msg ok" hidden></div></div>
  </section>
  <section id="review" hidden>
    <h1>Your corrections</h1>
    <p class="sub" id="reviewWho"></p>
    <div id="reviewList"></div>
  </section>
  <section id="closed" hidden>
    <h1>Submissions are closed</h1>
    <p class="sub" id="closedReason"></p>
  </section>
  <section id="ended" hidden>
    <h1>The quiz has ended</h1>
    <p class="sub">Ask your teacher if you still need to answer.</p>
  </section>
</main>
<div class="bar" id="bar" hidden><div>
  <div class="barline"><span id="progress"></span><span class="timer" id="timer" hidden></span></div>
  <button class="primary" id="submitButton" type="button">Submit answers</button>
</div></div>
<script>
(function () {
  var store = { get: function (k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
                set: function (k, v) { try { localStorage.setItem(k, v); } catch (e) {} },
                del: function (k) { try { localStorage.removeItem(k); } catch (e) {} } };
  var token = store.get("quizToken"), answers = {}, total = 0, screen = "join";
  var deadline = null, submitting = false, autoSubmitted = false, pollTimer = null, tick = null;
  try { answers = JSON.parse(store.get("quizAnswers") || "{}") || {}; } catch (e) { answers = {}; }
  function $(id) { return document.getElementById(id); }
  function show(id) {
    screen = id;
    ["join", "quiz", "done", "review", "closed", "ended"].forEach(function (s) { $(s).hidden = s !== id; });
    $("bar").hidden = id !== "quiz";
  }
  function error(el, text) { el.textContent = text; el.hidden = !text; }
  function call(method, path, body, keepalive) {
    var headers = { "Content-Type": "application/json" };
    if (token) headers["X-Quiz-Token"] = token;
    return fetch(path, { method: method, headers: headers, keepalive: !!keepalive, body: body ? JSON.stringify(body) : undefined })
      .then(function (r) { return r.json().catch(function () { return {}; }).then(function (d) { d._status = r.status; return d; }); });
  }
  function answeredCount() { return Object.keys(answers).filter(function (k) { return answers[k] !== ""; }).length; }
  function saveAnswers() { store.set("quizAnswers", JSON.stringify(answers)); progress(); }
  function progress() { $("progress").textContent = answeredCount() + " of " + total + " answered"; }

  // ----- timer -----
  function setDeadline(secondsLeft) {
    if (secondsLeft === null || secondsLeft === undefined) { deadline = null; $("timer").hidden = true; return; }
    deadline = Date.now() + secondsLeft * 1000;
    $("timer").hidden = false;
    if (!tick) { tick = setInterval(drawTimer, 500); }
    drawTimer();
  }
  function drawTimer() {
    if (deadline === null) { return; }
    var left = Math.max(0, Math.round((deadline - Date.now()) / 1000));
    var m = Math.floor(left / 60), s = left % 60;
    $("timer").textContent = (left ? m + ":" + (s < 10 ? "0" : "") + s + " left" : "Time is up");
    $("timer").className = "timer" + (left <= 60 ? " low" : "");
    if (left === 0 && screen === "quiz" && !autoSubmitted) { autoSubmitted = true; submit(true, 0); }
  }

  // ----- questions -----
  function choiceButtons(q, box) {
    var letters = "ABCDEFGH";
    var options = q.type === "True or False" ? ["True", "False"] : q.choices;
    var wrap = document.createElement("div"); if (q.type === "True or False") wrap.className = "row";
    options.forEach(function (text, i) {
      var value = q.type === "True or False" ? text : letters[i];
      var b = document.createElement("button"); b.type = "button";
      b.textContent = q.type === "True or False" ? text : letters[i] + ".  " + text;
      if (answers[q.key] === value) b.className = "selected";
      b.addEventListener("click", function () {
        answers[q.key] = value; saveAnswers();
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
        input.value = answers[q.key] || "";
        input.addEventListener("input", function () { answers[q.key] = input.value; saveAnswers(); });
        card.appendChild(input);
      } else { choiceButtons(q, card); }
      list.appendChild(card);
    });
    progress(); show("quiz"); setDeadline(data.seconds_left); startPolling(10000);
  }
  function closed(reason) { $("closedReason").textContent = reason || "Ask your teacher."; show("closed"); stopPolling(); }
  function load() {
    call("GET", "/api/questions").then(function (d) {
      if (d._status === 200) {
        if (d.submitted) { finish(d.score, d.total); if (d.answers_released) { loadReview(); } return; }
        if (d.closed_reason) { closed(d.closed_reason); return; }
        render(d); return;
      }
      if (d._status === 410) { show("ended"); return; }
      token = null; store.del("quizToken"); show("join");
    }).catch(function () { show("join"); error($("joinError"), "Can't reach the quiz. Check that you're on the same Wi-Fi or hotspot."); });
  }
  function finish(score, outOf) {
    $("score").textContent = score + " / " + outOf; store.del("quizAnswers"); show("done"); startPolling(5000);
  }

  // ----- corrections -----
  function loadReview() {
    call("GET", "/api/review").then(function (d) {
      if (d._status !== 200) { return; }
      stopPolling();
      $("reviewWho").textContent = d.name + " · Score " + d.score + " / " + d.total;
      var list = $("reviewList"); list.textContent = "";
      d.items.forEach(function (item) {
        var card = document.createElement("div"); card.className = "card";
        var head = document.createElement("div"); head.className = "q";
        var mark = document.createElement("span"); mark.className = "mark " + (item.correct ? "right" : "wrong");
        mark.textContent = item.correct ? "✓" : "✗";
        head.appendChild(mark); head.appendChild(document.createTextNode(item.number + ". " + item.text)); card.appendChild(head);
        var yours = document.createElement("div"); yours.className = "line";
        yours.appendChild(document.createTextNode("Your answer: "));
        var yb = document.createElement("b"); yb.textContent = item.your_answer || "(no answer)"; yours.appendChild(yb);
        card.appendChild(yours);
        if (!item.correct) {
          var right = document.createElement("div"); right.className = "line";
          right.appendChild(document.createTextNode("Correct answer: "));
          var rb = document.createElement("b"); rb.textContent = item.correct_answer; right.appendChild(rb);
          card.appendChild(right);
        }
        list.appendChild(card);
      });
      show("review");
    }).catch(function () {});
  }

  // ----- status checks -----
  function stopPolling() { if (pollTimer) { clearInterval(pollTimer); pollTimer = null; } }
  function startPolling(every) { stopPolling(); pollTimer = setInterval(poll, every); }
  function poll() {
    call("GET", "/api/status").then(function (d) {
      if (d._status !== 200) { return; }
      if (d.state === "ended") {
        stopPolling();
        if (screen === "done") { $("doneNote").textContent = "The quiz has ended. You can close this page."; } else { show("ended"); }
        return;
      }
      if (d.state === "unknown") { stopPolling(); return; }
      if (screen === "quiz") {
        setDeadline(d.seconds_left);
        if (d.closed_reason && d.answers_released) { closed(d.closed_reason); }
      } else if (screen === "done" && d.answers_released) { loadReview(); }
    }).catch(function () {});
  }

  // ----- leaving the page -----
  document.addEventListener("visibilitychange", function () {
    if (screen !== "quiz" || !token) { return; }
    call("POST", "/api/away", { away: document.visibilityState === "hidden" }, true).catch(function () {});
  });

  // ----- join and submit -----
  $("joinButton").addEventListener("click", function () {
    error($("joinError"), "");
    call("POST", "/api/join", { name: $("name").value, code: $("code").value }).then(function (d) {
      if (d._status !== 200) { error($("joinError"), d.detail || "Could not join."); return; }
      token = d.token; store.set("quizToken", token); answers = {}; saveAnswers(); load();
    }).catch(function () { error($("joinError"), "Can't reach the quiz. Check that you're on the same Wi-Fi or hotspot."); });
  });
  function submit(auto, tries) {
    if (submitting) { return; }
    if (!auto && answeredCount() < total && !window.confirm((total - answeredCount()) + " question(s) are unanswered. Submit anyway?")) return;
    submitting = true; error($("quizError"), auto ? "Time is up. Sending your answers…" : "");
    call("POST", "/api/submit", { answers: answers }).then(function (d) {
      submitting = false;
      if (d._status === 200) {
        finish(d.score, d.total);
        if (auto) { $("doneMsg").textContent = "Time was up, so your answers were sent automatically."; $("doneMsg").hidden = false; }
        return;
      }
      if (d._status === 410 && d.detail && d.detail.indexOf("quiz has ended") >= 0) { show("ended"); return; }
      if (d._status === 410) { closed(d.detail); return; }
      error($("quizError"), d.detail || "Could not submit. Try again.");
    }).catch(function () {
      submitting = false;
      if (auto && tries < 10) { setTimeout(function () { submit(true, tries + 1); }, 3000); return; }
      error($("quizError"), "Connection lost. Your answers are saved on this phone — try Submit again.");
    });
  }
  $("submitButton").addEventListener("click", function () { submit(false, 0); });
  if (token) { load(); } else { show("join"); }
})();
</script>
</body>
</html>
"""
