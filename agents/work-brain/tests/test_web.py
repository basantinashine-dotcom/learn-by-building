"""Tests for the local server: the routes, and the checks that protect it.

A real server is started on a spare port and driven over HTTP, because the
protections being tested (the Host check, the JSON requirement) live in the
HTTP layer and would be skipped by calling the functions directly.

Everything here runs in offline mode, so no API key is needed and no request
leaves the machine.
"""

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from web import Handler, WorkBrain

SAMPLES = Path(__file__).resolve().parent.parent / "sample-notes"


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        Handler.app = WorkBrain(SAMPLES, Path(cls.folder.name) / "brain", api_key="")
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.folder.cleanup()

    def url(self, path):
        return f"http://127.0.0.1:{self.port}{path}"

    def get(self, path, host=None):
        request = urllib.request.Request(self.url(path))
        if host:
            request.add_header("Host", host)
        with urllib.request.urlopen(request) as response:
            return response.status, response.read()

    def post(self, path, payload, content_type="application/json", host=None):
        body = json.dumps(payload).encode("utf-8") if isinstance(payload, dict) else payload
        request = urllib.request.Request(self.url(path), data=body, method="POST")
        request.add_header("Content-Type", content_type)
        if host:
            request.add_header("Host", host)
        with urllib.request.urlopen(request) as response:
            return response.status, json.loads(response.read())


class PageTest(ServerTest):
    def test_the_page_and_its_two_files_are_served(self):
        for path, marker in (("/", b"Work Brain"), ("/app.js", b"api("), ("/style.css", b"--ink")):
            status, body = self.get(path)
            self.assertEqual(status, 200)
            self.assertIn(marker, body)

    def test_an_unknown_path_is_a_404(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.get("/secrets")
        self.assertEqual(caught.exception.code, 404)


class GuardTest(ServerTest):
    def test_a_request_from_another_site_is_refused(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.get("/api/state", host="evil.example.com")
        self.assertEqual(caught.exception.code, 403)

    def test_a_post_that_is_not_json_is_refused(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.post("/api/ask", b"question=hi", content_type="text/plain")
        self.assertEqual(caught.exception.code, 400)

    def test_a_note_name_from_outside_the_folder_is_refused(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.get("/api/raw?id=..%2F..%2Fbrain.py")
        self.assertEqual(caught.exception.code, 404)

    def test_live_mode_without_a_key_explains_itself(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.post("/api/build", {"mode": "live"})
        self.assertEqual(caught.exception.code, 400)
        self.assertIn("needs an API key", json.loads(caught.exception.read())["error"])


class FlowTest(ServerTest):
    def test_build_then_ask_then_share(self):
        status, report = self.post("/api/build", {"mode": "offline"})
        self.assertEqual(status, 200)
        self.assertEqual(report["notes_read"], 4)
        self.assertTrue(report["facts_added"])

        _, state = self.get("/api/state")
        state = json.loads(state)
        self.assertEqual(len(state["notes"]), 4)
        self.assertFalse(state["can_go_live"])
        folders = {group["folder"]: group["notes"] for group in state["groups"]}
        self.assertTrue(folders["people"] and folders["projects"] and folders["decisions"])

        _, answer = self.post("/api/ask", {"question": "guest checkout", "mode": "offline"})
        self.assertIn("guest checkout", answer["text"].lower())
        self.assertTrue(answer["cited"])

        _, update = self.post("/api/share", {"topic": "checkout redesign", "mode": "offline"})
        self.assertNotIn("Search team", update["text"])
        self.assertTrue(update["used"])

    def test_the_brain_is_written_to_disk(self):
        self.post("/api/build", {"mode": "offline"})
        written = list(Path(Handler.app.brain_dir).rglob("*.md"))
        self.assertTrue(written)

    def test_a_raw_note_can_be_read_back(self):
        _, body = self.get("/api/raw?id=2026-09-12-one-on-one-marcus.md")
        self.assertIn("Search team", json.loads(body)["text"])

    def test_a_brain_note_can_be_read_back(self):
        self.post("/api/build", {"mode": "offline"})
        _, body = self.get("/api/note?id=people/marcus-lee")
        self.assertIn("[private]", json.loads(body)["text"])

    def test_an_empty_question_is_refused(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.post("/api/ask", {"question": "   ", "mode": "offline"})
        self.assertEqual(caught.exception.code, 400)


if __name__ == "__main__":
    unittest.main()
