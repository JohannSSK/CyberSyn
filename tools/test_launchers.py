#!/usr/bin/env python3
"""Exercise the real launchers in a disposable checkout, without downloading Python or models."""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
import venv
from pathlib import Path
from textwrap import dedent

ROOT = Path(__file__).resolve().parents[1]


class Launchers(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name).resolve()
        self.root = self.tmp / "project with spaces"
        for name in ("setup.sh", "run.sh", "tools/local_python.sh", "includes/constants.json", "requirements.txt"):
            dst = self.root / name
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, dst)
        self.venv = self.root / ".venv"
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        for cmd in ("bash", "cat", "dirname", "grep", "readlink", "uname"):
            (self.bin / cmd).symlink_to(shutil.which(cmd))
        (self.bin / "python3").symlink_to(sys.executable)

        # Use real venv prefixes and executables; simulate only the minor versions
        # seen by the launchers' -c probes. PATH has 3.14 unless a test adds another.
        stubs = self.tmp / "stubs"
        stubs.mkdir()
        (stubs / "sitecustomize.py").write_text(dedent('''\
            import os, sys
            from pathlib import Path
            if sys.argv[0] == '-c':
                exe = Path(sys.executable)
                minor = os.environ.get('FIXTURE_VENV_MINOR', '12')
                if exe.parent == Path(os.environ['PATH']):
                    minor = exe.name.partition('.')[2] or '14'
                sys.version_info = (3, int(minor), 0)
        '''))
        check_prefix = "import sys\nfrom pathlib import Path\nassert Path(sys.prefix).samefile('.venv')\n"
        (stubs / "pip.py").write_text(check_prefix)  # fail if setup tries to install outside the project
        (stubs / "torch.py").write_text("raise ImportError\n")
        src = self.root / "src"
        (src / "MLscripts").mkdir(parents=True)
        (src / "MLscripts/model_cache.py").write_text(check_prefix +
            "assert sys.argv[1:] == ['--download']\nprint('model check stub')\n")
        (src / "app.py").write_text("import json, sys\nprint(json.dumps([sys.executable, *sys.argv[1:]]))\n")
        self.env = dict(PATH=str(self.bin), PYTHONPATH=str(stubs), HOME=tmp.name, PIP_NO_INDEX="1",
                        PYTHONNOUSERSITE="1", FIXTURE_PYTHON=sys.executable)

    def launch(self, script, *args, success=True):
        p = subprocess.run([self.root / script, *args], cwd=self.tmp, env=self.env,
                           text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=45)
        self.assertEqual(p.returncode == 0, success, p.stdout)
        return p.stdout

    def test_arch_without_compatible_python_or_uv(self):
        self.assertIn("sudo pacman -S --needed uv", self.launch("setup.sh", success=False))
        self.assertIn("./setup.sh", self.launch("run.sh", success=False))
        self.assertFalse(self.venv.exists())

    def test_uv_fallback_then_reuse_without_any_python_on_path(self):
        uv = self.bin / "uv"
        uv.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > uv.args\n'
                      'exec "$FIXTURE_PYTHON" -m venv --without-pip .venv\n')
        uv.chmod(0o755)
        self.launch("run.sh", success=False)  # run never installs a runtime
        self.assertFalse((self.root / "uv.args").exists())
        self.assertIn("model check stub", self.launch("setup.sh"))
        args = (self.root / "uv.args").read_text().splitlines()
        self.assertEqual(args[0], "venv")
        self.assertIn("--seed", args)
        self.assertEqual(args[args.index("--python") + 1], "3.12")
        self.assertEqual(Path(args[-1]).name, ".venv")
        uv.unlink()
        (self.bin / "python3").unlink()
        self.assertIn("model check stub", self.launch("setup.sh"))
        launched = json.loads(self.launch("run.sh", "seed", "two words").splitlines()[-1])
        self.assertEqual(launched, [str(self.venv / "bin/python"), "seed", "two words"])

    def test_versioned_python_behind_unsupported_python3(self):
        alternate = self.bin / "python3.13"
        alternate.symlink_to(sys.executable)
        self.assertEqual(json.loads(self.launch("run.sh").splitlines()[-1]), [str(alternate)])
        setup = self.launch("setup.sh")
        self.assertIn(str(alternate), setup)
        self.assertIn("model check stub", setup)

    def test_unusable_existing_venv_is_not_overwritten_or_bypassed(self):
        (self.bin / "python3.11").symlink_to(sys.executable)
        venv.create(self.venv, with_pip=False, symlinks=True)
        marker = self.venv / "keep"
        marker.write_text("existing files")
        for problem in ("unsupported", "broken"):
            if problem == "unsupported":
                self.env["FIXTURE_VENV_MINOR"] = "14"
            else:
                del self.env["FIXTURE_VENV_MINOR"]
                (self.venv / "pyvenv.cfg").unlink()  # bin/python now refers to a system prefix
            for script in ("setup.sh", "run.sh"):
                with self.subTest(problem=problem, script=script):
                    self.assertIn("Move it aside", self.launch(script, success=False))
                    self.assertEqual(marker.read_text(), "existing files")


if __name__ == "__main__":
    unittest.main(verbosity=2)
