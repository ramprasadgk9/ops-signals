"""A stand-in for a Slack incoming webhook: accepts the same POSTs and renders them as a Slack-like
channel, so the demo (or local development) shows exactly what would land in Slack without a
Slack workspace.

    POST /webhook (or any /services/... path)  store a Block Kit payload, reply "ok" like Slack
    GET  /                                     the channel view (polls for new messages)
    GET  /api/messages                         everything received, newest first, as JSON
    GET  /healthz

Standard library only. Messages are kept in memory and, if SLACK_SINK_STORE is set, appended to
that JSONL file so they survive a restart.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PORT = int(os.environ.get("SLACK_SINK_PORT", "8090"))
CHANNEL = os.environ.get("SLACK_SINK_CHANNEL", "#checkout-oncall")
STORE = Path(os.environ["SLACK_SINK_STORE"]) if os.environ.get("SLACK_SINK_STORE") else None
MAX_BODY_BYTES = 1_000_000

_lock = threading.Lock()
_messages: list[dict] = []


def _load() -> None:
    if not STORE or not STORE.exists():
        return
    for line in STORE.read_text(encoding="utf-8").splitlines():
        try:
            _messages.append(json.loads(line))
        except json.JSONDecodeError:
            continue


def _store(payload: dict) -> None:
    entry = {"received_at": datetime.now(timezone.utc).isoformat(), "payload": payload}
    with _lock:
        _messages.append(entry)
        if STORE:
            STORE.parent.mkdir(parents=True, exist_ok=True)
            with STORE.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry) + "\n")


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        if not (self.path == "/webhook" or self.path.startswith("/services/")):
            return self._send(404, "text/plain", b"no_service")
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_BODY_BYTES:
            return self._send(400, "text/plain", b"invalid_payload")
        try:
            payload = json.loads(self.rfile.read(length))
        except json.JSONDecodeError:
            return self._send(400, "text/plain", b"invalid_payload")
        if not isinstance(payload, dict) or not (payload.get("text") or payload.get("blocks")):
            return self._send(400, "text/plain", b"no_text")
        _store(payload)
        self._send(200, "text/plain", b"ok")

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/api/messages":
            with _lock:
                body = json.dumps(list(reversed(_messages))).encode("utf-8")
            return self._send(200, "application/json", body)
        if self.path == "/healthz":
            return self._send(200, "text/plain", b"ok\n")
        if self.path in {"/", "/index.html"}:
            return self._send(200, "text/html; charset=utf-8", PAGE.replace("{{CHANNEL}}", CHANNEL).encode("utf-8"))
        self._send(404, "text/plain", b"not found\n")

    def _send(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        if args and str(args[0]).startswith("POST"):
            print(f"slack-sink: {format % args}", flush=True)


PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{CHANNEL}} · Slack sink</title>
<style>
  :root {
    --bg: #ffffff; --panel: #f8f8f8; --text: #1d1c1d; --muted: #616061; --border: #e2e2e2;
    --link: #1264a3; --code-bg: #f4f4f4; --code-text: #c01343; --accent: #4a154b; --bar: #dddddd;
    color-scheme: light;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #1a1d21; --panel: #222529; --text: #d1d2d3; --muted: #9a9b9d; --border: #35373b;
      --link: #1d9bd1; --code-bg: #2c2e33; --code-text: #e8912d; --accent: #350d36; --bar: #4a4c50;
      color-scheme: dark;
    }
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--text);
         font: 15px/1.47 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; }
  header { position: sticky; top: 0; z-index: 1; background: var(--accent); color: #fff;
           padding: 12px 20px; display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; }
  header h1 { margin: 0; font-size: 17px; font-weight: 800; }
  header span { opacity: .8; font-size: 13px; }
  main { max-width: 860px; margin: 0 auto; padding: 8px 20px 48px; }
  .empty { color: var(--muted); padding: 48px 0; text-align: center; }
  .msg { display: grid; grid-template-columns: 36px 1fr; gap: 10px; padding: 14px 0; border-bottom: 1px solid var(--border); }
  .avatar { width: 36px; height: 36px; border-radius: 6px; background: #2eb67d; color: #fff;
            display: grid; place-items: center; font-weight: 800; font-size: 14px; }
  .meta { display: flex; gap: 8px; align-items: baseline; flex-wrap: wrap; }
  .meta b { font-weight: 800; }
  .app { font-size: 10px; font-weight: 700; color: var(--muted); background: var(--panel);
         border: 1px solid var(--border); border-radius: 3px; padding: 0 3px; }
  .time { color: var(--muted); font-size: 12px; }
  .block { margin-top: 6px; overflow-wrap: anywhere; }
  .header-block { font-size: 18px; font-weight: 800; margin-top: 4px; }
  .context { color: var(--muted); font-size: 13px; }
  .divider { border: 0; border-top: 1px solid var(--border); margin: 10px 0; }
  .fields { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 6px 16px; }
  a { color: var(--link); text-decoration: none; }
  a:hover { text-decoration: underline; }
  code { font: 12px/1.5 Menlo, Monaco, Consolas, monospace; background: var(--code-bg); color: var(--code-text);
         border: 1px solid var(--border); border-radius: 3px; padding: 1px 3px; }
  .note { color: var(--muted); font-size: 12px; margin: 12px 0 0; }
</style>
</head>
<body>
<header><h1>{{CHANNEL}}</h1><span>Slack sink · messages Ops Signals would post to Slack</span></header>
<main>
  <div id="messages"><p class="empty">Waiting for the first message…</p></div>
  <p class="note">This page updates by itself. Point a real Slack webhook at the backend to post to Slack instead.</p>
</main>
<script>
function esc(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}
// Slack mrkdwn -> HTML. Escape first, then turn <url|label>, `code`, *bold*, _italic_ into markup.
function mrkdwn(text) {
  const links = [];
  let s = String(text || "").replace(/<((?:https?|mailto):[^|>]+)(?:\|([^>]+))?>/g, function (_, url, label) {
    links.push('<a href="' + esc(url) + '" target="_blank" rel="noopener">' + esc(label || url) + "</a>");
    return "\u0000" + (links.length - 1) + "\u0000";
  });
  s = esc(s)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/(^|[\s(])\*([^*\n]+)\*/g, "$1<b>$2</b>")
    .replace(/(^|[\s(])_([^_\n]+)_/g, "$1<i>$2</i>")
    .replace(/\n/g, "<br>");
  return s.replace(/\u0000(\d+)\u0000/g, function (_, i) { return links[Number(i)]; });
}
function textOf(obj) {
  if (!obj) return "";
  return obj.type === "plain_text" ? esc(obj.text) : mrkdwn(obj.text);
}
function renderBlock(block) {
  switch (block.type) {
    case "header": return '<div class="block header-block">' + esc(block.text && block.text.text) + "</div>";
    case "divider": return '<hr class="divider">';
    case "context":
      return '<div class="block context">' + (block.elements || []).map(textOf).join(" ") + "</div>";
    case "section": {
      let html = block.text ? '<div class="block">' + textOf(block.text) + "</div>" : "";
      if (block.fields) html += '<div class="block fields">' + block.fields.map(function (f) { return "<div>" + textOf(f) + "</div>"; }).join("") + "</div>";
      return html;
    }
    default: return "";
  }
}
function render(messages) {
  const root = document.getElementById("messages");
  if (!messages.length) { root.innerHTML = '<p class="empty">Waiting for the first message…</p>'; return; }
  root.innerHTML = messages.map(function (m) {
    const p = m.payload || {};
    const body = p.blocks && p.blocks.length ? p.blocks.map(renderBlock).join("") : '<div class="block">' + mrkdwn(p.text) + "</div>";
    const when = new Date(m.received_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    return '<article class="msg"><div class="avatar">OS</div><div>' +
      '<div class="meta"><b>Ops Signals</b><span class="app">APP</span><span class="time">' + esc(when) + "</span></div>" +
      body + "</div></article>";
  }).join("");
}
let last = "";
async function poll() {
  try {
    const res = await fetch("/api/messages", { cache: "no-store" });
    const text = await res.text();
    if (text !== last) { last = text; render(JSON.parse(text)); }
  } catch (e) { /* sink restarting; try again */ }
}
poll();
setInterval(poll, 3000);
</script>
</body>
</html>
"""


if __name__ == "__main__":
    _load()
    print(f"slack-sink: listening on :{PORT} (POST /webhook, view at /)", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
