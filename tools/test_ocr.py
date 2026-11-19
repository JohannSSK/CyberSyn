#!/usr/bin/env python3
"""Local OCR helper tests (no external dependencies required).

    python3 tools/test_ocr.py
"""
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import ocr  # noqa: E402


class OcrTests(unittest.TestCase):
    def test_normalise_text_trims_and_collapses_blank_lines(self):
        raw = "\r\n  Line one  \r\n\r\n\r\n  Line two \r\n\r\n"
        self.assertEqual(ocr._normalise_text(raw), "Line one\n\nLine two")
        self.assertEqual(ocr._normalise_text("   \n  \t "), "")

    def test_empty_and_oversized_images_rejected(self):
        with self.assertRaises(ocr.OcrInvalidImageError):
            ocr._decode_png_bytes(b"")
        with self.assertRaises(ocr.OcrTooLargeError):
            ocr._decode_png_bytes(b"x" * (ocr.MAX_PHOTO_BYTES + 1))

    def test_corrupt_png_raises_invalid_image_error(self):
        try:
            import PIL  # noqa: F401
        except ImportError:
            self.skipTest("Pillow not installed")
        bad_png = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x02\x00\x00\x00\x02"
            b"\x08\x02\x00\x00\x00\xfd\xd4\x9as\x00\x00\x00\x0eIDATx\x9cc\xfc\xff"
            b"\xff?\x03\x10\x00\x00\x1f\xf8\x03\xfd\x85w\xd5/\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        with self.assertRaises(ocr.OcrInvalidImageError):
            ocr._decode_png_bytes(bad_png)

    def test_composite_alpha_chooses_dark_bg_for_light_text(self):
        try:
            from PIL import Image, ImageDraw
        except ImportError:
            self.skipTest("Pillow not installed")
        img = Image.new("RGBA", (200, 60), (0, 0, 0, 0))
        ImageDraw.Draw(img).text((20, 20), "Light text", fill=(255, 255, 255, 255))
        flat = ocr._composite_alpha(img, Image)
        self.assertEqual(flat.getpixel((0, 0)), (16, 19, 24))

        img_dark = Image.new("RGBA", (200, 60), (0, 0, 0, 0))
        ImageDraw.Draw(img_dark).text((20, 20), "Dark text", fill=(0, 0, 0, 255))
        flat_dark = ocr._composite_alpha(img_dark, Image)
        self.assertEqual(flat_dark.getpixel((0, 0)), (255, 255, 255))

    def test_no_text_error_exact_message(self):
        for noisy in ("", "   ", "&", "...", "O"):
            with mock.patch.object(ocr, "_decode_png_bytes", return_value=b"png"), \
                 mock.patch.object(ocr, "_tesseract_extract", return_value=noisy), \
                 mock.patch.object(ocr, "_rapidocr_extract", return_value=noisy):
                with self.assertRaises(ocr.OcrNoTextError) as ctx:
                    ocr.extract_text(b"fake-image")
            self.assertEqual(str(ctx.exception), "There's no text to parse in this prompt.")
            self.assertEqual(ctx.exception.error_code, "no_photo_text")
            self.assertEqual(ctx.exception.status, 400)

    def test_parse_tesseract_tsv_filters_low_confidence(self):
        tsv = "\n".join([
            "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext",
            "5\t1\t1\t1\t1\t1\t0\t0\t10\t10\t20\t&",
            "5\t1\t1\t1\t1\t2\t15\t0\t30\t10\t92\tHello",
            "5\t1\t1\t1\t1\t3\t50\t0\t30\t10\t88\tworld",
            "5\t1\t2\t1\t1\t1\t0\t20\t30\t10\t90\tLine2",
        ])
        self.assertEqual(ocr._parse_tesseract_tsv(tsv), "Hello world\n\nLine2")

    def test_unavailable_when_no_ocr_engine_present(self):
        with mock.patch.object(ocr, "_decode_png_bytes", return_value=b"png"), \
             mock.patch.object(ocr, "_tesseract_extract", return_value=None), \
             mock.patch.object(ocr, "_rapidocr_extract", return_value=None):
            with self.assertRaises(ocr.OcrUnavailableError) as ctx:
                ocr.extract_text(b"fake-image")
        self.assertEqual(ctx.exception.status, 503)

    def test_uses_tesseract_then_rapidocr_fallback(self):
        with mock.patch.object(ocr, "_decode_png_bytes", return_value=b"png"), \
             mock.patch.object(ocr, "_tesseract_extract", return_value="Invoice #42"), \
             mock.patch.object(ocr, "_rapidocr_extract", return_value="Ignored"):
            self.assertEqual(ocr.extract_text(b"fake-image"), "Invoice #42")

        with mock.patch.object(ocr, "_decode_png_bytes", return_value=b"png"), \
             mock.patch.object(ocr, "_tesseract_extract", return_value=None), \
             mock.patch.object(ocr, "_rapidocr_extract", return_value="From RapidOCR"):
            self.assertEqual(ocr.extract_text(b"fake-image"), "From RapidOCR")

    def test_rapidocr_extract_handles_v3_and_v1_outputs(self):
        class FakeV3Result:
            txts = ("Hello", "Noise", "World")
            scores = (0.98, 0.30, 0.91)

        with mock.patch.object(ocr, "_get_rapidocr", return_value=lambda _b: FakeV3Result()):
            self.assertEqual(ocr._rapidocr_extract(b"png"), "Hello\nWorld")

        v1_result = ([[None, "Line A", 0.99], [None, "&", 0.25], [None, "Line B", 0.95]], [0.1])
        with mock.patch.object(ocr, "_get_rapidocr", return_value=lambda _b: v1_result):
            self.assertEqual(ocr._rapidocr_extract(b"png"), "Line A\nLine B")

        with mock.patch.object(ocr, "_get_rapidocr", return_value=lambda _b: None):
            self.assertEqual(ocr._rapidocr_extract(b"png"), "")

    def test_chat_photo_route_registered_in_constants(self):
        constants_path = Path(__file__).resolve().parents[1] / "includes" / "constants.json"
        data = json.loads(constants_path.read_text(encoding="utf-8"))
        self.assertEqual(data["ROUTES"]["CHAT_PHOTO"], "/api/admin/employee/chat/photo")


if __name__ == "__main__":
    unittest.main(verbosity=2)
