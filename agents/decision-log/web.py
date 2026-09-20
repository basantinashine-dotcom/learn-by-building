#!/usr/bin/env python3
"""The decision log in your browser.

    python web.py                 # then open http://127.0.0.1:8766

Standard library only. The server holds the notes, the brain and the API key.
The page never talks to Claude and never sees the key: it sends a question and
renders what comes back.

Two protections matter, because this server can spend your API credits:

* It listens on 127.0.0.1 only, so nothing else on your network can reach it.
* It rejects requests whose Host header is not this server, and requires JSON
  for every POST. Together those stop an unrelated website open in your browser
  from quietly driving your key.

A third protection matters because this server reads your work: every path it
serves is one of three fixed files, and the notes folder is the only place it
reads from. Nothing takes a file name from the browser.
"""

import argparse
import json
import os
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import live
import offline
from ask import answer, decision_card, offline_answer, render_note
from brain import decisions, load_brain, save_brain
from notes import load_raw_notes
from share import explain

HERE = Path(__file__).resolve().parent
WEB_ROOT = HERE / "web"
STATIC = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
}
MAX_BODY_BYTES = 64 * 1024
DEFAULT_PORT = 8766


class DecisionLog:
    """The notes, the log, and the one lock that keeps them consistent.

    The browser can fire two requests at once. A rebuild that runs halfway
    through a question would answer from half a brain, so the two never
    overlap.
    """

    def __init__(self, notes_dir, brain_dir, api_key=""):
        self.notes_dir = Path(notes_dir)
        self.brain_dir = Path(brain_dir)
        self.api_key = api_key
        self.lock = threading.Lock()
        self.brain = load_brain(self.brain_dir)
        self.last_report = None

    @property
    def can_go_live(self):
        return bool(self.api_key)

    def client(self):
        if not self.api_key:
            raise ValueError(
                "Live mode needs an API key. Set ANTHROPIC_API_KEY and restart, "
                "or use offline mode."
            )
        return live.make_client(self.api_key)

    def raw_notes(self):
        return load_raw_notes(self.notes_dir)

    def rebuild(self, mode):
        """Read every raw note again, from an empty brain.

        Rebuilding from scratch rather than adding to what is there means a
        note you fixed does not leave its old reading behind.
        """
        with self.lock:
            raws = self.raw_notes()
            if not raws:
                raise ValueError(f"No notes found in {self.notes_dir}.")
            if mode == "live":
                brain, report = live.build(raws, self.client())
            else:
                brain, report = offline.build(raws)
            self.brain, self.last_report = brain, report
            save_brain(self.brain_dir, brain)
            return report

    def ask(self, question, mode):
        with self.lock:
            if mode == "live":
                return answer(self.client(), self.brain, question)
            return offline_answer(self.brain, question)

    def explain(self, target, mode):
        with self.lock:
            client = self.client() if mode == "live" else None
            return explain(self.brain, target, client=client)

    def decision(self, note_id):
        with self.lock:
            note = self.brain.get(note_id)
            if note is None or note.type != "decision":
                raise ValueError(f"No decision called {note_id!r}.")
            return decision_card(self.brain, note)

    def state(self):
        """Everything the page needs to draw itself."""
        with self.lock:
            notes = [
                {
                    "source": raw.source,
                    "title": raw.title,
                    "date": raw.date,
                    "private_bullets": len(raw.bullets(private=True)),
                }
                for raw in self.raw_notes()
            ]
            log = []
            for note in decisions(self.brain):
                reasons = note.reasons()
                owner = self.brain.get(note.owner)
                project = self.brain.get(note.project)
                log.append({
                    "id": note.id,
                    "title": note.title,
                    "status": note.status,
                    "date": note.updated,
                    "owner": owner.title if owner else "",
                    "project": project.title if project else "",
                    "why": reasons[0].text if reasons else "",
                    "why_count": len(reasons),
                    "replaces": note.replaces,
                    "replaced_by": note.replaced_by,
                    "private": len(note.facts) - len(note.public_facts()),
                })

            cast = sorted(
                (
                    {
                        "id": note.id,
                        "title": note.title,
                        "kind": note.type,
                        "facts": len(note.facts),
                        "private": len(note.facts) - len(note.public_facts()),
                        "updated": note.updated,
                    }
                    for note in self.brain.values()
                    if note.type != "decision"
                ),
                key=lambda item: (item["kind"], item["title"].lower()),
            )
            report = self.last_report
            return {
                "notes_dir": str(self.notes_dir),
                "log_dir": str(self.brain_dir),
                "can_go_live": self.can_go_live,
                "model": live.MODEL,
                "notes": notes,
                "decisions": log,
                "cast": cast,
                "report": None if report is None else {
                    "notes_read": report.notes_read,
                    "facts_added": report.facts_added,
                    "skipped": report.skipped[:20],
                    "skipped_total": len(report.skipped),
                },
            }

    def read_raw(self, source):
        """One raw note, found by name in the notes folder.

        The name from the browser is only ever compared against names we
        already know, so no path from outside can be opened.
        """
        with self.lock:
            for raw in self.raw_notes():
                if raw.source == source:
                    return raw.text
        raise ValueError(f"No note called {source!r}.")

    def read_note(self, note_id):
        with self.lock:
            note = self.brain.get(note_id)
            if not note:
                raise ValueError(f"No note called {note_id!r}.")
            return render_note(note)


class Handler(BaseHTTPRequestHandler):
    server_version = "DecisionLog/1.0"
    app = None

    def log_message(self, *args):
        pass  # the console is for the model's work, not a request log

    # --- plumbing ----------------------------------------------------------

    def send_json(self, payload, status=HTTPStatus.OK):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def fail(self, message, status=HTTPStatus.BAD_REQUEST):
        self.send_json({"error": message}, status)

    def host_is_ours(self):
        host = (self.headers.get("Host") or "").split(":")[0]
        return host in ("127.0.0.1", "localhost", "[::1]", "::1")

    def read_json(self):
        if "application/json" not in (self.headers.get("Content-Type") or ""):
            return None, "send JSON"
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_BODY_BYTES:
            return None, "body too large or empty"
        try:
            return json.loads(self.rfile.read(length).decode("utf-8")), None
        except (ValueError, UnicodeDecodeError):
            return None, "body was not valid JSON"

    # --- routes ------------------------------------------------------------

    def do_GET(self):
        if not self.host_is_ours():
            return self.fail("bad host", HTTPStatus.FORBIDDEN)

        path, _, query = self.path.partition("?")
        if path in STATIC:
            name, content_type = STATIC[path]
            body = (WEB_ROOT / name).read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            return self.wfile.write(body)

        if path == "/api/state":
            return self.send_json(self.app.state())

        if path in ("/api/raw", "/api/note", "/api/decision"):
            wanted = ""
            for pair in query.split("&"):
                key, _, value = pair.partition("=")
                if key == "id":
                    from urllib.parse import unquote_plus

                    wanted = unquote_plus(value)
            try:
                if path == "/api/decision":
                    return self.send_json(self.app.decision(wanted))
                text = (
                    self.app.read_raw(wanted) if path == "/api/raw"
                    else self.app.read_note(wanted)
                )
            except ValueError as error:
                return self.fail(str(error), HTTPStatus.NOT_FOUND)
            return self.send_json({"text": text})

        self.fail("no such page", HTTPStatus.NOT_FOUND)

    def do_POST(self):
        if not self.host_is_ours():
            return self.fail("bad host", HTTPStatus.FORBIDDEN)

        payload, problem = self.read_json()
        if problem:
            return self.fail(problem)

        mode = "live" if payload.get("mode") == "live" else "offline"
        try:
            if self.path == "/api/build":
                report = self.app.rebuild(mode)
                return self.send_json({
                    "notes_read": report.notes_read,
                    "facts_added": report.facts_added,
                    "skipped": report.skipped[:20],
                    "skipped_total": len(report.skipped),
                })

            if self.path == "/api/ask":
                question = (payload.get("question") or "").strip()
                if not question:
                    return self.fail("ask something first")
                return self.send_json(self.app.ask(question, mode))

            if self.path == "/api/explain":
                target = (payload.get("target") or "").strip()
                if not target:
                    return self.fail("which decision should I explain?")
                return self.send_json(self.app.explain(target, mode))
        except ValueError as error:
            return self.fail(str(error))
        except Exception as error:  # an API failure should explain itself
            return self.fail(f"{type(error).__name__}: {error}", HTTPStatus.BAD_GATEWAY)

        self.fail("no such page", HTTPStatus.NOT_FOUND)


def main():
    parser = argparse.ArgumentParser(description="The decision log in your browser.")
    parser.add_argument("--notes", default=str(HERE / "sample-notes"),
                        help="folder of raw notes to read")
    parser.add_argument("--brain", default=str(HERE / "log"),
                        help="folder to keep the log in")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    Handler.app = DecisionLog(args.notes, args.brain, os.environ.get("ANTHROPIC_API_KEY", ""))
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}"

    print(f"The decision log is at {url}")
    print(f"  notes: {args.notes}")
    print(f"  log:   {args.brain}")
    print("  live mode: " + ("ready" if Handler.app.can_go_live else
                             "off (no ANTHROPIC_API_KEY)"))
    print("Press Ctrl+C to stop.")
    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
