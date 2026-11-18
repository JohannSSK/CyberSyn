#!/usr/bin/env python3
"""Check the model cache contract without downloading or running any models."""

import os
import sys
import tempfile
import unittest
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
