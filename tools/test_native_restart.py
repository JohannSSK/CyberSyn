#!/usr/bin/env python3
"""Exercise run.sh against real Flask and SQLite, in a disposable checkout.

Usage after setup: .venv/bin/python tools/test_native_restart.py --models
Omit --models to check only the web app on an installation without model weights.
No provider calls are made, and the real checkout's database is not touched.
"""

import argparse
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = json.loads((ROOT / "includes/constants.json").read_text(encoding="utf-8"))
OWNER = {"username": "restart_fixture", "password": "DisposableNativeTest123!"}


class NativeRestart(unittest.TestCase):
    verify_models = False

    def setUp(self):
        self.assertNotEqual(sys.prefix, sys.base_prefix, "Run this with the project venv Python")
        self.temp = Path(self.enterContext(tempfile.TemporaryDirectory(prefix="cybersyn-restart-"))).resolve()
        self.project = self.temp / "project with spaces"
        for name in ("src", "includes", "assets"):
            shutil.copytree(ROOT / name, self.project / name, ignore=shutil.ignore_patterns("backend", "__pycache__"))
        shutil.copy2(ROOT / "run.sh", self.project)
        (self.project / "tools").mkdir()
        shutil.copy2(ROOT / "tools/local_python.sh", self.project / "tools")
        (self.project / ".venv").symlink_to(sys.prefix, target_is_directory=True)
        if self.verify_models:
            cache = Path(REGISTRY["PATHS"]["MODEL_CACHE"])
            self.assertTrue((ROOT / cache).is_dir(), "Prepare the default project cache with ./setup.sh")
            dest = self.project / cache
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.symlink_to(ROOT / cache, target_is_directory=True)

        # No activated venv, uv or system Python on PATH, and run.sh is itself
        # found through a symlink outside the checkout.
        self.bin = self.temp / "bin"
        self.bin.mkdir()
        for command in ("bash", "dirname", "readlink"):
            (self.bin / command).symlink_to(shutil.which(command))
        self.launcher = self.bin / "cybersyn"
        self.launcher.symlink_to(self.project / "run.sh")
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            self.port = listener.getsockname()[1]
        config = {**REGISTRY, "HOST": "127.0.0.1", "PORT": self.port}
        (self.project / "includes/constants.json").write_text(json.dumps(config), encoding="utf-8")
        self.url = f"http://127.0.0.1:{self.port}"

    def shell(self):
        home = Path(tempfile.mkdtemp(dir=self.temp))
        return dict(cwd=home, env=dict(PATH=str(self.bin), HOME=str(home),
            HF_HUB_CACHE=str(home / "empty-hub"), HF_HUB_OFFLINE="1", PIP_NO_INDEX="1",
            CYBERSYN_WARM_MODELS="1" if self.verify_models else "0"))

    def cli(self, *args, **overrides):
        options = self.shell()
        options["env"].update(overrides)
        return subprocess.run([self.launcher, *args], **options, timeout=20, text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

    @contextmanager
    def running(self, stop_with):
        with tempfile.TemporaryFile(mode="w+b") as log:
            process = subprocess.Popen([self.launcher], **self.shell(), stdout=log, stderr=subprocess.STDOUT)

            def logs():
                # A separate file offset would be needed for simultaneous
                # writes and reads; pread leaves the child's offset alone.
                return os.pread(log.fileno(), 65536, 0).decode("utf-8", "replace")

            try:
                deadline = time.monotonic() + (180 if self.verify_models else 15)
                while time.monotonic() < deadline and process.poll() is None:
                    try:
                        with urlopen(self.url, timeout=1) as response:
                            ready = "Team member sign in" in response.read().decode("utf-8")
                    except OSError:
                        ready = False
                    if ready and (not self.verify_models or "models: ['spacy', 'zero-shot']" in logs()):
                        break
                    time.sleep(0.1)
                else:
                    self.fail("Server did not become ready:\n" + logs())
                yield
            finally:
                if process.poll() is None:
                    process.send_signal(stop_with)
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
                        self.fail("Launcher did not stop on the requested signal")

    def api(self, route, **payload):
        request = Request(self.url + REGISTRY["ROUTES"][route], data=json.dumps(payload).encode(),
                          headers={"Content-Type": "application/json"})
        with urlopen(request, timeout=10) as response:
            return json.load(response)

    def test_fresh_shells_keep_state_after_interrupt_and_process_kill(self):
        seed = self.cli("seed", OWNER["username"], CYBERSYN_SEED_PASSWORD=OWNER["password"])
        self.assertEqual(seed.returncode, 0, seed.stdout)
        self.assertIn("Created admin", seed.stdout)
        self.assertNotIn("Running on", seed.stdout)
        key_file = self.project / REGISTRY["PATHS"]["KEY_FILE"]
        with self.running(signal.SIGINT):
            admin = self.api("ADMIN_LOGIN", **OWNER)
            self.assertTrue(admin["success"])
            pid = admin["Parent_id"]
            grant = self.api("ADMIN_APPROVE", **OWNER, scope="once")["admin_token"]
            saved = self.api("SETTINGS", Parent_id=pid, Employee_id=0, admin_token=grant,
                             API_KEY="synthetic-restart-key-1234", action_check1="warn")
            self.assertEqual(saved["API_KEY_MASK"], "****1234")
            before = key_file.read_bytes()
        for stop_with in (signal.SIGKILL, signal.SIGTERM):
            with self.running(stop_with):
                # Authenticate afresh and decrypt the original settings from disk.
                admin = self.api("ADMIN_LOGIN", **OWNER)
                self.assertEqual(admin["Parent_id"], pid)
                restored = self.api("SETTINGS", Parent_id=pid, Employee_id=0, token=admin["session_token"])
                self.assertEqual(restored["API_KEY_MASK"], "****1234")
                self.assertEqual(restored["action_check1"], "warn")
                self.assertTrue(before == key_file.read_bytes(), "Unexpected replacement of encryption key")

    def test_configuration_and_occupied_port_fail_with_a_useful_message(self):
        invalid = self.cli(CYBERSYN_PORT="not-a-port")
        self.assertNotEqual(invalid.returncode, 0)
        self.assertIn("set CYBERSYN_PORT", invalid.stdout)
        self.assertNotIn("Traceback", invalid.stdout)
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            conflict = self.cli(CYBERSYN_PORT=str(listener.getsockname()[1]))
        self.assertNotEqual(conflict.returncode, 0)
        self.assertIn("Address already in use", conflict.stdout)
        self.assertNotIn("Running on", conflict.stdout)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", action="store_true", help="check model warm-up after each restart")
    NativeRestart.verify_models = parser.parse_args().models
    unittest.main(argv=[sys.argv[0]], verbosity=2)
