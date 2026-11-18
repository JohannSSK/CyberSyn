#!/usr/bin/env python3
"""Check the model cache contract without downloading or running any models."""

import os
import runpy
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from MLscripts import model_cache


class ModelCache(unittest.TestCase):
    def setUp(self):
        tmp = self.enterContext(tempfile.TemporaryDirectory())
        self.cache = str(Path(tmp) / "project-cache")
        self.snapshot = str(Path(self.cache) / "snapshot")
        self.enterContext(patch.dict(os.environ, {"HF_HUB_CACHE": str(Path(tmp) / "other-hub")}))
        os.environ.pop("CYBERSYN_MODEL_CACHE", None)
        self.enterContext(patch.object(model_cache, "_configured_cache", return_value=self.cache))
        self.enterContext(patch.object(model_cache, "_zero_shot", None))
        self.download = Mock(return_value=self.snapshot)
        self.pipeline = Mock()
        self.enterContext(patch.dict(sys.modules, {
            "huggingface_hub": SimpleNamespace(snapshot_download=self.download),
            "transformers": SimpleNamespace(logging=Mock(), pipeline=self.pipeline),
        }))

    def test_runtime_prefers_project_cache_and_reuses_pipeline(self):
        self.assertIs(model_cache.get_zero_shot(), model_cache.get_zero_shot())
        self.download.assert_called_once_with(model_cache.ZERO_SHOT_MODEL,
                                              cache_dir=self.cache, local_files_only=True)
        self.pipeline.assert_called_once_with("zero-shot-classification", model=self.snapshot,
                                              device=-1, model_kwargs={"local_files_only": True})

    def test_missing_weights_do_not_trigger_download_on_warm_or_send(self):
        self.download.side_effect = FileNotFoundError
        self.assertEqual(model_cache.warm(("zero-shot",)), {"loaded": [], "skipped": ["zero-shot"]})
        with self.assertRaisesRegex(OSError, r"run \./setup\.sh"):
            model_cache.get_zero_shot()
        self.pipeline.assert_not_called()
        calls = self.download.call_args_list
        self.assertEqual([call.kwargs["cache_dir"] for call in calls], [self.cache, None] * 2)
        self.assertTrue(all(call.kwargs["local_files_only"] for call in calls))

    def test_older_install_can_use_its_existing_hf_cache_offline(self):
        self.download.side_effect = [FileNotFoundError, "/existing/snapshot"]
        model_cache.get_zero_shot()
        self.assertIsNone(self.download.call_args.kwargs["cache_dir"])
        self.assertTrue(self.download.call_args.kwargs["local_files_only"])
        self.assertEqual(self.pipeline.call_args.kwargs["model"], "/existing/snapshot")

    def test_explicit_override_does_not_fall_back_to_another_cache(self):
        os.environ["CYBERSYN_MODEL_CACHE"] = self.cache
        self.download.side_effect = FileNotFoundError
        with self.assertRaises(OSError):
            model_cache.get_zero_shot()
        self.assertEqual(self.download.call_count, 1)

    def test_only_setup_repairs_incomplete_snapshot(self):
        # A cached ref can exist even if the previous download was interrupted.
        self.pipeline.side_effect = [ValueError("model files incomplete"), Mock()]
        model_cache._load_zero_shot(download=True)
        calls = self.download.call_args_list
        self.assertEqual(len(calls), 3)
        self.assertTrue(all(call.kwargs["cache_dir"] == self.cache for call in calls))
        self.assertTrue(calls[0].kwargs["local_files_only"])
        self.assertFalse(calls[1].kwargs.get("local_files_only", False))
        self.assertIn("pytorch_model*.bin", calls[1].kwargs["allow_patterns"])
        self.assertTrue(calls[2].kwargs["local_files_only"])

    def cli(self, *args):
        stdout, stderr = StringIO(), StringIO()
        self.taggers = [Mock(pipe_names=["ner"]), Mock(pipe_names=["ner"])]
        self.load_spacy = Mock(side_effect=self.taggers)
        with (patch.dict(sys.modules, {
            "config": SimpleNamespace(MODEL_CACHE=self.cache),
            "spacy": SimpleNamespace(load=self.load_spacy),
            "torch": SimpleNamespace(version=SimpleNamespace(cuda=None)),
        }), patch.object(sys, "argv", [model_cache.__file__, *args]),
              redirect_stdout(stdout), redirect_stderr(stderr), self.assertRaises(SystemExit) as stopped):
            runpy.run_path(model_cache.__file__, run_name="__main__")
        return stopped.exception.code, stdout.getvalue(), stderr.getvalue()

    def test_verify_runs_one_inference_per_model_offline(self):
        def offline_download(*args, **kwargs):
            self.assertEqual(os.environ["HF_HUB_OFFLINE"], "1")
            return self.snapshot

        self.download.side_effect = offline_download
        self.pipeline.return_value.return_value = {"scores": [0.9, 0.1]}
        status, stdout, stderr = self.cli("--verify")
        self.assertEqual(status, 0, stderr)
        self.assertIn("Verified CPU inference", stdout)
        self.assertEqual([call.args[0] for call in self.load_spacy.call_args_list],
                         ["en_core_web_sm", "el_core_news_sm"])
        self.assertTrue(all(tagger.call_count == 1 for tagger in self.taggers))
        self.download.assert_called_once_with(model_cache.ZERO_SHOT_MODEL, cache_dir=self.cache, local_files_only=True)
        self.pipeline.return_value.assert_called_once()

    def test_verify_exits_nonzero_when_project_weights_are_missing(self):
        # A legacy snapshot does not make this checkout ready to start.
        self.download.side_effect = [FileNotFoundError, "/legacy/snapshot"]
        status, stdout, stderr = self.cli("--verify")
        self.assertEqual(status, 1)
        self.assertFalse(stdout)
        self.assertIn("Local DistilBART model unavailable", stderr)
        self.assertIn(self.cache, stderr)
        self.assertEqual(len(stderr.splitlines()), 1)
        self.download.assert_called_once_with(model_cache.ZERO_SHOT_MODEL, cache_dir=self.cache, local_files_only=True)
        self.pipeline.assert_not_called()

    def test_verify_and_download_are_mutually_exclusive(self):
        status, _, stderr = self.cli("--verify", "--download")
        self.assertEqual(status, 2)
        self.assertIn("not allowed with", stderr)
        self.load_spacy.assert_not_called()
        self.download.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
