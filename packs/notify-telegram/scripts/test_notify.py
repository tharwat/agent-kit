#!/usr/bin/env python3
# Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License).
"""Tests for the notify script. Run: python3 -m unittest test_notify.py

A local http.server stub stands in for the Bot API through TELEGRAM_API_BASE.
"""

import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "notify")
TOKEN = "123456:TEST-token-value-never-printed"
CHAT = "-1000000000001"


class StubHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        form = urllib.parse.parse_qs(self.rfile.read(length).decode("utf-8"))
        server = self.server
        server.requests.append({"path": self.path, "form": {k: v[0] for k, v in form.items()}})
        if server.mode == "slow":
            time.sleep(2)
        if server.mode == "http_error":
            # Echo the path (which holds the token) to prove the script redacts it.
            body = {"ok": False, "error_code": 401, "description": "Unauthorized for " + self.path}
            status = 401
        else:
            body = {"ok": True, "result": {"message_id": len(server.requests)}}
            status = 200
        payload = json.dumps(body).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        except OSError:
            pass


class Stub:
    def __init__(self, mode="ok"):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), StubHandler)
        self.server.daemon_threads = True
        self.server.mode = mode
        self.server.requests = []
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def base(self):
        return "http://127.0.0.1:%d" % self.server.server_address[1]

    @property
    def requests(self):
        return self.server.requests

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def clean_env(**extra):
    env = {k: v for k, v in os.environ.items() if not k.startswith("TELEGRAM_")}
    env.update(extra)
    return env


class NotifyTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        # Install a copy where the script expects it: <project>/.claude/scripts/notify
        self.claude_dir = os.path.join(self._tmp.name, ".claude")
        os.makedirs(os.path.join(self.claude_dir, "scripts"))
        self.script = os.path.join(self.claude_dir, "scripts", "notify")
        shutil.copy2(SCRIPT, self.script)
        self.outputs = []

    def run_notify(self, text, env):
        result = subprocess.run(
            [sys.executable, self.script, text], capture_output=True, text=True, env=env, timeout=30,
        )
        self.outputs.append(result.stdout + result.stderr)
        return result

    def tearDown(self):
        for out in self.outputs:
            self.assertNotIn(TOKEN, out)
            self.assertNotIn(TOKEN.split(":")[1], out)

    def test_missing_config(self):
        result = self.run_notify("[Example] hello", clean_env())
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, "notify: not configured (TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID)\n")

    def test_missing_chat_id_only(self):
        result = self.run_notify("[Example] hello", clean_env(TELEGRAM_BOT_TOKEN=TOKEN))
        self.assertEqual(result.returncode, 0)
        self.assertIn("not configured", result.stderr)

    def test_success_plain_text(self):
        with Stub() as stub:
            env = clean_env(TELEGRAM_BOT_TOKEN=TOKEN, TELEGRAM_CHAT_ID=CHAT, TELEGRAM_API_BASE=stub.base)
            result = self.run_notify("[Example] 🚀 Shipped ABC-1 *not markdown* <b>", env)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, "")
        self.assertEqual(len(stub.requests), 1)
        req = stub.requests[0]
        self.assertEqual(req["path"], "/bot%s/sendMessage" % TOKEN)
        self.assertEqual(req["form"]["chat_id"], CHAT)
        self.assertEqual(req["form"]["text"], "[Example] 🚀 Shipped ABC-1 *not markdown* <b>")
        self.assertNotIn("parse_mode", req["form"])

    def test_env_file_fallback(self):
        with open(os.path.join(self.claude_dir, "notify.env"), "w", encoding="utf-8") as fh:
            fh.write("# local only\nexport TELEGRAM_BOT_TOKEN='%s'\nTELEGRAM_CHAT_ID=%s\n" % (TOKEN, CHAT))
        with Stub() as stub:
            result = self.run_notify("[Example] from file", clean_env(TELEGRAM_API_BASE=stub.base))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, "")
        self.assertEqual(stub.requests[0]["form"]["chat_id"], CHAT)

    def test_environment_wins_over_file(self):
        with open(os.path.join(self.claude_dir, "notify.env"), "w", encoding="utf-8") as fh:
            fh.write("TELEGRAM_BOT_TOKEN=%s\nTELEGRAM_CHAT_ID=from-file\n" % TOKEN)
        with Stub() as stub:
            env = clean_env(TELEGRAM_CHAT_ID="from-env", TELEGRAM_API_BASE=stub.base)
            self.run_notify("[Example] x", env)
        self.assertEqual(stub.requests[0]["form"]["chat_id"], "from-env")

    def test_http_error(self):
        with Stub(mode="http_error") as stub:
            env = clean_env(TELEGRAM_BOT_TOKEN=TOKEN, TELEGRAM_CHAT_ID=CHAT, TELEGRAM_API_BASE=stub.base)
            result = self.run_notify("[Example] x", env)
        self.assertEqual(result.returncode, 0)
        self.assertTrue(result.stderr.startswith("notify: send failed: HTTP 401"), result.stderr)
        self.assertIn("<redacted>", result.stderr)
        self.assertEqual(result.stderr.count("\n"), 1)

    def test_network_error(self):
        env = clean_env(TELEGRAM_BOT_TOKEN=TOKEN, TELEGRAM_CHAT_ID=CHAT,
                        TELEGRAM_API_BASE="http://127.0.0.1:%d" % free_port())
        result = self.run_notify("[Example] x", env)
        self.assertEqual(result.returncode, 0)
        self.assertTrue(result.stderr.startswith("notify: send failed: network error"), result.stderr)
        self.assertEqual(result.stderr.count("\n"), 1)

    def test_timeout(self):
        loader = importlib.machinery.SourceFileLoader("notify_under_test", self.script)
        spec = importlib.util.spec_from_loader("notify_under_test", loader)
        module = importlib.util.module_from_spec(spec)
        with mock.patch.object(sys, "dont_write_bytecode", True):
            loader.exec_module(module)
        module.TIMEOUT = 0.5
        with Stub(mode="slow") as stub:
            env = clean_env(TELEGRAM_BOT_TOKEN=TOKEN, TELEGRAM_CHAT_ID=CHAT, TELEGRAM_API_BASE=stub.base)
            err = io.StringIO()
            with mock.patch.dict(os.environ, env, clear=True), contextlib.redirect_stderr(err):
                started = time.monotonic()
                code = module.main(["[Example] slow"])
                elapsed = time.monotonic() - started
        self.outputs.append(err.getvalue())
        self.assertEqual(code, 0)
        self.assertLess(elapsed, 1.9)
        self.assertTrue(err.getvalue().startswith("notify: send failed"), err.getvalue())
        self.assertIn("timed out", err.getvalue())
        self.assertEqual(err.getvalue().count("\n"), 1)

    def test_long_text_is_split(self):
        lines = ["line %04d %s" % (i, "x" * 60) for i in range(150)]  # ~10,500 chars
        text = "[Example] report\n" + "\n".join(lines)
        with Stub() as stub:
            env = clean_env(TELEGRAM_BOT_TOKEN=TOKEN, TELEGRAM_CHAT_ID=CHAT, TELEGRAM_API_BASE=stub.base)
            result = self.run_notify(text, env)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, "")
        sent = [r["form"]["text"] for r in stub.requests]
        self.assertEqual(len(sent), 3)
        self.assertTrue(all(len(s) <= 4000 for s in sent))
        self.assertEqual("\n".join(sent), text)

    def test_unbroken_long_text_is_split(self):
        text = "y" * 9000
        with Stub() as stub:
            env = clean_env(TELEGRAM_BOT_TOKEN=TOKEN, TELEGRAM_CHAT_ID=CHAT, TELEGRAM_API_BASE=stub.base)
            self.run_notify(text, env)
        sent = [r["form"]["text"] for r in stub.requests]
        self.assertEqual([len(s) for s in sent], [4000, 4000, 1000])
        self.assertEqual("".join(sent), text)

    def test_empty_text(self):
        result = self.run_notify("", clean_env(TELEGRAM_BOT_TOKEN=TOKEN, TELEGRAM_CHAT_ID=CHAT))
        self.assertEqual(result.returncode, 0)
        self.assertIn("nothing to send", result.stderr)


if __name__ == "__main__":
    unittest.main()
