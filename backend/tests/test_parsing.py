import unittest
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

from app.parsing import extract_lesson_features, extract_text


class LessonFeatureTests(unittest.TestCase):
    def test_text_lesson_detects_headings_lists_and_emphasis(self):
        features = extract_lesson_features(
            "lesson.txt",
            (
                "# Network Protocols\n"
                "**Packet switching** is a method that sends data in small units.\n"
                "- A router forwards data packets between networks.\n"
            ).encode("utf-8"),
        )

        self.assertIn("Network Protocols", features["heading_terms"])
        self.assertIn("Packet switching", features["emphasized_terms"])
        self.assertIn(
            "A router forwards data packets between networks.",
            features["list_terms"],
        )


class PdfOcrTests(unittest.TestCase):
    def test_text_pdf_with_blank_page_does_not_require_ocr(self):
        text_page = MagicMock()
        text_page.extract_text.return_value = (
            "This page contains enough readable text to avoid triggering OCR."
        )
        blank_page = MagicMock()
        blank_page.extract_text.return_value = ""
        pdf = MagicMock()
        pdf.__enter__.return_value.pages = [text_page, blank_page]

        with (
            patch("pdfplumber.open", return_value=pdf),
            patch("app.parsing._get_ocr_engine") as get_ocr_engine,
        ):
            text = extract_text("text-with-blank-page.pdf", b"pdf bytes")

        self.assertIn("This page contains enough readable text", text)
        self.assertEqual(text.count("\n"), 1)
        get_ocr_engine.assert_not_called()

    def test_scanned_pdf_page_uses_local_ocr_fallback(self):
        page = MagicMock()
        page.extract_text.return_value = ""
        pdf = MagicMock()
        pdf.__enter__.return_value.pages = [page]
        image = object()
        rendered_page = MagicMock()
        rendered_page.render.return_value.to_pil.return_value = image
        pdfium_document = MagicMock()
        pdfium_document.__getitem__.return_value = rendered_page
        ocr = MagicMock()
        ocr.image_to_string.return_value = (
            "Photosynthesis is the process by which plants convert light energy."
        )

        with (
            patch("pdfplumber.open", return_value=pdf),
            patch("pypdfium2.PdfDocument", return_value=pdfium_document),
            patch("app.parsing._get_ocr_engine", return_value=ocr),
        ):
            text = extract_text("scanned.pdf", b"pdf bytes")

        self.assertIn("Photosynthesis is the process", text)
        ocr.image_to_string.assert_called_once_with(image, lang="eng")
        pdfium_document.close.assert_called_once()

    def test_mostly_scanned_pdf_uses_ocr_only_for_sparse_pages(self):
        text_page = MagicMock()
        text_page.extract_text.return_value = (
            "This page contains enough readable text to avoid triggering OCR."
        )
        sparse_pages = [MagicMock(), MagicMock()]
        for page in sparse_pages:
            page.extract_text.return_value = ""
        pdf = MagicMock()
        pdf.__enter__.return_value.pages = [text_page, *sparse_pages]
        images = [object(), object()]
        rendered_pages = [MagicMock(), MagicMock()]
        for rendered_page, image in zip(rendered_pages, images):
            rendered_page.render.return_value.to_pil.return_value = image
        pdfium_document = MagicMock()
        pdfium_document.__getitem__.side_effect = rendered_pages
        ocr = MagicMock()
        ocr.image_to_string.side_effect = [
            "OCR extracted readable text from scanned page one.",
            "OCR extracted readable text from scanned page two.",
        ]

        with (
            patch("pdfplumber.open", return_value=pdf),
            patch("pypdfium2.PdfDocument", return_value=pdfium_document),
            patch("app.parsing._get_ocr_engine", return_value=ocr),
        ):
            text = extract_text("mostly-scanned.pdf", b"pdf bytes")

        self.assertIn("This page contains enough readable text", text)
        self.assertIn("OCR extracted readable text from scanned page one.", text)
        self.assertIn("OCR extracted readable text from scanned page two.", text)
        self.assertEqual(pdfium_document.__getitem__.call_count, 2)
        self.assertEqual(ocr.image_to_string.call_count, 2)
        pdfium_document.close.assert_called_once()

    def test_all_blank_pdf_without_tesseract_explains_required_setup(self):
        pages = [MagicMock(), MagicMock()]
        for page in pages:
            page.extract_text.return_value = ""
        pdf = MagicMock()
        pdf.__enter__.return_value.pages = pages

        with (
            patch("pdfplumber.open", return_value=pdf),
            patch("pypdfium2.PdfDocument"),
            patch("shutil.which", return_value=None),
        ):
            with self.assertRaises(HTTPException) as error:
                extract_text("scanned.pdf", b"pdf bytes")

        self.assertEqual(error.exception.status_code, 422)
        self.assertIn("Install Tesseract OCR", error.exception.detail)


if __name__ == "__main__":
    unittest.main()
