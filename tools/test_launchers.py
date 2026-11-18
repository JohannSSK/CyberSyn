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
        self.root = self.tmp / "project with 'spaces' & $"
        for name in ("setup.sh", "run.sh", "tools/local_python.sh", "tools/cybersyn.sh",
                     "includes/constants.json", "requirements.txt"):
            dst = self.root / name
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, dst)
        self.venv = self.root / ".venv"
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        for cmd in ("bash", "cat", "dirname", "grep", "install", "mkdir", "mktemp", "readlink", "rm", "uname"):
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
        check_prefix = "import os, sys\nfrom pathlib import Path\nassert Path(sys.prefix).samefile('.venv')\n"
        # Fail if pip or the model check ever runs outside the project env.
        (stubs / "pip.py").write_text(check_prefix + dedent('''\
            if sys.argv[1:] == ['check']:
                print('pip check stub')
                sys.exit(int(os.environ.get('FIXTURE_PIP_FAIL', '0')))
        '''))
        (stubs / "torch.py").write_text("raise ImportError\n")
        src = self.root / "src"
        (src / "MLscripts").mkdir(parents=True)
        (src / "MLscripts/model_cache.py").write_text(check_prefix + dedent('''\
            assert sys.argv[1:] in (['--download'], ['--verify'])
            mode = sys.argv[1]
            print(f'model check stub {mode}')
            sys.exit(int(os.environ.get('FIXTURE_MODEL_FAIL') == mode))
        '''))
        (src / "app.py").write_text(dedent('''\
            import json, os, sys
            print('app stub')
            print(json.dumps([os.environ.get('CYBERSYN_PORT'), os.environ.get('CYBERSYN_HOST')]))
            print(json.dumps([sys.executable, *sys.argv[1:]]))
        '''))
        self.env = dict(PATH=str(self.bin), PYTHONPATH=str(stubs), HOME=tmp.name, PIP_NO_INDEX="1",
                        PYTHONNOUSERSITE="1", FIXTURE_PYTHON=sys.executable)
        self.user_launcher = self.tmp / ".local/bin/cybersyn"
        self.system_launcher = self.tmp / "system bin/cybersyn"

    def launch(self, script, *args, success=True):
        p = subprocess.run([self.root / script, *args], cwd=self.tmp, env=self.env,
                           text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=45)
        self.assertEqual(p.returncode == 0, success, p.stdout)
        return p.stdout

    def make_venv(self):
        venv.create(self.venv, with_pip=False, symlinks=True)

    def fake_sudo(self, allowed):
        sudo = self.bin / "sudo"
        sudo.write_text(dedent('''\
            #!/usr/bin/env bash
            printf '%s\\n' "$@" > "$FIXTURE_SUDO_ARGS"
            [[ "$#" = 6 && "$1" = -n && "$2" = install && "$3" = -m && "$4" = 0755 &&
               "$6" = /usr/local/bin/cybersyn && "$FIXTURE_SUDO_ALLOWED" = 1 ]] || exit 1
            exec install -m 0755 "$5" "$FIXTURE_SYSTEM_LAUNCHER"
        '''))
        sudo.chmod(0o755)
        self.system_launcher.parent.mkdir()
        self.env.update(FIXTURE_SUDO_ALLOWED=str(int(allowed)), FIXTURE_SUDO_ARGS=str(self.tmp / "sudo.args"),
                        FIXTURE_SYSTEM_LAUNCHER=str(self.system_launcher))

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
        failure = self.launch("run.sh", success=False)
        self.assertIn("No project .venv found", failure)
        self.assertIn("./setup.sh", failure)
        self.assertIn("CYBERSYN_SKIP_VERIFY=1", failure)
        self.assertNotIn("app stub", failure)
        self.env["CYBERSYN_SKIP_VERIFY"] = "1"
        self.assertEqual(json.loads(self.launch("run.sh").splitlines()[-1]), [str(alternate)])
        setup = self.launch("setup.sh")
        self.assertIn(str(alternate), setup)
        self.assertIn("model check stub", setup)

    def test_unusable_existing_venv_is_not_overwritten_or_bypassed(self):
        (self.bin / "python3.11").symlink_to(sys.executable)
        self.make_venv()
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

    def test_run_checks_dependencies_before_starting(self):
        self.make_venv()
        out = self.launch("run.sh")
        self.assertLess(out.index("pip check stub"), out.index("model check stub --verify"))
        self.assertLess(out.index("model check stub --verify"), out.index("app stub"))
        self.assertNotIn("--download", out)

    def test_run_fails_without_starting_on_a_failed_probe(self):
        self.make_venv()
        for env, value, reason in (("FIXTURE_PIP_FAIL", "1", "pip check failed"),
                                   ("FIXTURE_MODEL_FAIL", "--verify", "Offline model verification failed")):
            with self.subTest(reason=reason):
                self.env[env] = value
                out = self.launch("run.sh", success=False)
                del self.env[env]
                self.assertIn("CyberSyn cannot start: the local screeners are not ready", out)
                self.assertIn(reason, out)
                self.assertIn("run ./setup.sh (or cybersyn --setup)", out.lower())
                self.assertNotIn("app stub", out)
                if env == "FIXTURE_PIP_FAIL":
                    self.assertNotIn("model check stub", out)

    def test_setup_installs_system_launcher_and_overwrites_existing_file(self):
        self.make_venv()
        self.fake_sudo(allowed=True)
        self.system_launcher.write_text("obsolete launcher")
        out = self.launch("setup.sh")
        self.assertIn("Installed the cybersyn launcher at /usr/local/bin/cybersyn", out)
        self.assertEqual(out.splitlines()[-1].strip(), "cybersyn -p 8000")
        self.assertEqual(self.system_launcher.stat().st_mode & 0o777, 0o755)
        self.assertFalse(self.user_launcher.exists())
        self.assertIn("app stub", self.launch(self.system_launcher))

    def test_setup_uses_user_bin_when_sudo_is_denied_but_skips_it_in_ci(self):
        self.make_venv()
        self.fake_sudo(allowed=False)
        self.user_launcher.parent.mkdir(parents=True)
        self.user_launcher.write_text("obsolete user launcher")
        out = self.launch("setup.sh")
        self.assertIn(f"Installed the cybersyn launcher at {self.user_launcher}", out)
        self.assertIn('export PATH="$HOME/.local/bin:$PATH"', out)
        self.assertEqual(self.user_launcher.stat().st_mode & 0o777, 0o755)
        self.assertIn("app stub", self.launch(self.user_launcher))
        self.assertFalse(self.system_launcher.exists())

        self.user_launcher.unlink()
        self.env["CI"] = "true"
        out = self.launch("setup.sh")
        self.assertIn("skipping the cybersyn launcher in unattended setup", out)
        self.assertFalse(self.user_launcher.exists())

    def test_setup_does_not_install_the_launcher_if_models_do_not_verify(self):
        self.make_venv()
        self.fake_sudo(allowed=True)
        self.env["FIXTURE_MODEL_FAIL"] = "--download"
        self.launch("setup.sh", success=False)
        self.assertFalse(self.system_launcher.exists())
        self.assertFalse(self.user_launcher.exists())
        self.assertFalse((self.tmp / "sudo.args").exists())

    def test_launcher_maps_flags_and_preserves_arguments(self):
        self.make_venv()
        self.launch("setup.sh")
        self.env.update(CYBERSYN_PORT="5000", CYBERSYN_HOST="127.0.0.1")
        for flags, port in ((("-p", "8123"), "8123"), (("--port", "0"), "0"),
                            (("--port=065535",), "65535")):
            with self.subTest(flags=flags):
                out = self.launch(self.user_launcher, *flags, "--host", "0.0.0.0", "--unknown", "two words")
                self.assertIn("model check stub --verify", out)
                env, args = map(json.loads, out.splitlines()[-2:])
                self.assertEqual(env, [port, "0.0.0.0"])
                self.assertEqual(args, [str(self.venv / "bin/python"), "--unknown", "two words"])
        for password in ("two words", "--help", "--port=bad"):
            with self.subTest(password=password):
                seed = ("seed", "owner", password)
                out = self.launch(self.user_launcher, *seed)
                self.assertEqual(out, self.launch("run.sh", *seed))
                self.assertNotIn("pip check stub", out)
                self.assertNotIn("model check stub", out)
                self.assertEqual(json.loads(out.splitlines()[-1]), [str(self.venv / "bin/python"), *seed])

    def test_launcher_rejects_bad_ports_before_running_anything(self):
        self.make_venv()
        self.launch("setup.sh")
        for args in (("-p",), ("--port=",), ("--port", "-1"), ("-p", "word"), ("--port=65536",),
                     ("--port=18446744073709551616",), ("-p", "1+2")):
            with self.subTest(args=args):
                out = self.launch(self.user_launcher, "--setup", *args, success=False)
                self.assertIn("Usage: cybersyn", out)
                self.assertNotIn("pip check stub", out)
                self.assertNotIn("app stub", out)

    def test_launcher_help_and_relocated_checkout(self):
        self.make_venv()
        self.launch("setup.sh")
        moved = self.tmp / "moved checkout"
        self.root.rename(moved)
        for flag in ("-h", "--help"):
            out = self.launch(self.user_launcher, "--setup", flag)
            self.assertIn("Usage: cybersyn", out)
            self.assertNotIn("app stub", out)
        out = self.launch(self.user_launcher, success=False)
        self.assertIn("checkout not found", out)
        self.assertIn(str(self.root), out)
        self.assertIn("CYBERSYN_HOME", out)
        self.env["CYBERSYN_HOME"] = str(moved)
        self.assertIn("app stub", self.launch(self.user_launcher))

    def test_launcher_repairs_then_starts_only_on_success(self):
        self.make_venv()
        self.launch("setup.sh")
        self.env["FIXTURE_MODEL_FAIL"] = "--verify"
        out = self.launch(self.user_launcher, success=False)
        self.assertIn("Offline model verification failed", out)
        self.assertNotIn("app stub", out)
        self.env["FIXTURE_MODEL_FAIL"] = "--download"
        out = self.launch(self.user_launcher, "--setup", success=False)
        self.assertIn("model check stub --download", out)
        self.assertNotIn("app stub", out)
        del self.env["FIXTURE_MODEL_FAIL"]
        out = self.launch(self.user_launcher, "--setup", "-p", "8123")
        self.assertLess(out.index("model check stub --download"), out.index("model check stub --verify"))
        self.assertLess(out.index("model check stub --verify"), out.index("app stub"))
        self.assertEqual(json.loads(out.splitlines()[-2]), ["8123", None])


if __name__ == "__main__":
    unittest.main(verbosity=2)
