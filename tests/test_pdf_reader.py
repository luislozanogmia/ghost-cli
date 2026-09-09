import io
import unittest

from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

from pdf_reader import PdfReadError, extract_pdf


def make_text_pdf(text="Ghost can read this PDF"):
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    })
    resources = DictionaryObject({
        NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})
    })
    page[NameObject("/Resources")] = resources
    safe_text = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = DecodedStreamObject()
    stream.set_data(f"BT /F1 18 Tf 72 720 Td ({safe_text}) Tj ET".encode("latin-1"))
    page[NameObject("/Contents")] = writer._add_object(stream)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


class PdfReaderTests(unittest.TestCase):
    def test_extracts_embedded_text_with_page_metadata(self):
        result = extract_pdf(make_text_pdf(), mode="auto", max_chars=10_000)

        self.assertEqual(result["page_count"], 1)
        self.assertFalse(result["ocr_used"])
        self.assertEqual(result["pages"][0]["page"], 1)
        self.assertEqual(result["pages"][0]["source"], "embedded_text")
        self.assertIn("Ghost can read this PDF", result["pages"][0]["text"])

    def test_auto_mode_uses_ocr_only_for_empty_pages(self):
        calls = []

        def fake_ocr(pdf_bytes, page_number):
            calls.append(page_number)
            return "Scanned page text", 0.94

        result = extract_pdf(
            make_text_pdf(""), mode="auto", max_chars=10_000, ocr_page=fake_ocr
        )

        self.assertEqual(calls, [1])
        self.assertTrue(result["ocr_used"])
        self.assertEqual(result["pages"][0]["source"], "ocr")
        self.assertEqual(result["pages"][0]["ocr_confidence"], 0.94)

    def test_text_mode_does_not_invoke_ocr(self):
        def fail_ocr(*_args):
            self.fail("OCR should not run in text mode")

        result = extract_pdf(make_text_pdf(""), mode="text", ocr_page=fail_ocr)
        self.assertEqual(result["pages"][0]["source"], "none")

    def test_applies_global_character_limit(self):
        result = extract_pdf(make_text_pdf("abcdefghij"), max_chars=5)
        self.assertTrue(result["truncated"])
        self.assertEqual(result["pages"][0]["text"], "abcde")

    def test_rejects_non_pdf_bytes(self):
        with self.assertRaisesRegex(PdfReadError, "NOT_A_PDF"):
            extract_pdf(b"not a pdf")

    def test_rejects_invalid_page_range(self):
        with self.assertRaisesRegex(PdfReadError, "INVALID_PAGE_RANGE"):
            extract_pdf(make_text_pdf(), page_start=2)


if __name__ == "__main__":
    unittest.main()
