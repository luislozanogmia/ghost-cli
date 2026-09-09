"""Bounded, page-indexed PDF text extraction for the Ghost extension bridge."""

from __future__ import annotations

import io
import threading
from collections.abc import Callable
from typing import Any

from pypdf import PdfReader


MAX_PDF_BYTES = 50 * 1024 * 1024
MAX_PDF_PAGES = 300
MAX_OUTPUT_CHARS = 1_000_000
DEFAULT_MAX_CHARS = 50_000


class PdfReadError(Exception):
    """A stable Ghost PDF error with a machine-readable code."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


_ocr_engine = None
_ocr_lock = threading.Lock()


def _default_ocr_page(pdf_bytes: bytes, page_number: int) -> tuple[str, float | None]:
    """Render one PDF page and OCR it. Imports and model loading are lazy."""
    global _ocr_engine
    try:
        import numpy as np
        import pypdfium2 as pdfium
        from rapidocr import RapidOCR
    except ImportError as exc:
        raise PdfReadError(
            "OCR_UNAVAILABLE",
            "Install pypdfium2, rapidocr, and onnxruntime to read scanned PDFs.",
        ) from exc

    try:
        document = pdfium.PdfDocument(pdf_bytes)
        page = document[page_number - 1]
        bitmap = page.render(scale=2.5)
        image = np.asarray(bitmap.to_pil().convert("RGB"))
        bitmap.close()
        page.close()
        document.close()

        with _ocr_lock:
            if _ocr_engine is None:
                _ocr_engine = RapidOCR()
            result = _ocr_engine(image)
    except PdfReadError:
        raise
    except Exception as exc:
        raise PdfReadError("OCR_FAILED", f"OCR failed on page {page_number}: {exc}") from exc

    lines = list(result.txts or ())
    scores = [float(score) for score in (result.scores or ())]
    confidence = round(sum(scores) / len(scores), 4) if scores else None
    return "\n".join(lines).strip(), confidence


def _extract_page_text(page: Any) -> str:
    try:
        try:
            text = page.extract_text(extraction_mode="layout")
        except TypeError:
            text = page.extract_text()
        return (text or "").strip()
    except Exception as exc:
        raise PdfReadError("PDF_PARSE_FAILED", f"Could not extract page text: {exc}") from exc


def extract_pdf(
    pdf_bytes: bytes,
    *,
    page_start: int = 1,
    page_end: int | None = None,
    mode: str = "auto",
    max_chars: int = DEFAULT_MAX_CHARS,
    password: str | None = None,
    ocr_page: Callable[[bytes, int], tuple[str, float | None]] | None = None,
) -> dict[str, Any]:
    """Return bounded text and provenance for a 1-based PDF page range."""
    if not isinstance(pdf_bytes, (bytes, bytearray)) or not bytes(pdf_bytes).lstrip().startswith(b"%PDF-"):
        raise PdfReadError("NOT_A_PDF", "Downloaded content does not have a PDF signature.")
    if len(pdf_bytes) > MAX_PDF_BYTES:
        raise PdfReadError("PDF_TOO_LARGE", f"PDF exceeds the {MAX_PDF_BYTES} byte limit.")
    if mode not in {"auto", "text", "ocr"}:
        raise PdfReadError("INVALID_MODE", "mode must be one of: auto, text, ocr.")
    if not isinstance(max_chars, int) or isinstance(max_chars, bool) or not 1 <= max_chars <= MAX_OUTPUT_CHARS:
        raise PdfReadError(
            "INVALID_MAX_CHARS", f"max_chars must be between 1 and {MAX_OUTPUT_CHARS}."
        )

    try:
        reader = PdfReader(io.BytesIO(pdf_bytes), strict=False)
        if reader.is_encrypted:
            if not password:
                raise PdfReadError("PDF_PASSWORD_REQUIRED", "The PDF is encrypted.")
            if not reader.decrypt(password):
                raise PdfReadError("PDF_PASSWORD_INVALID", "The PDF password is invalid.")
        page_count = len(reader.pages)
    except PdfReadError:
        raise
    except Exception as exc:
        raise PdfReadError("PDF_PARSE_FAILED", f"Could not parse PDF: {exc}") from exc

    if page_count > MAX_PDF_PAGES:
        raise PdfReadError(
            "PDF_TOO_MANY_PAGES", f"PDF has {page_count} pages; the limit is {MAX_PDF_PAGES}."
        )
    if page_count < 1:
        raise PdfReadError("PDF_PARSE_FAILED", "PDF has no pages.")

    if page_end is None:
        page_end = page_count
    if (
        not isinstance(page_start, int)
        or isinstance(page_start, bool)
        or not isinstance(page_end, int)
        or isinstance(page_end, bool)
        or page_start < 1
        or page_end < page_start
        or page_end > page_count
    ):
        raise PdfReadError(
            "INVALID_PAGE_RANGE",
            f"Requested pages {page_start}-{page_end}; PDF pages are 1-{page_count}.",
        )

    ocr = ocr_page or _default_ocr_page
    pages = []
    remaining = max_chars
    truncated = False
    ocr_used = False

    for page_number in range(page_start, page_end + 1):
        embedded = _extract_page_text(reader.pages[page_number - 1])
        should_ocr = mode == "ocr" or (mode == "auto" and not embedded)
        confidence = None
        if should_ocr:
            text, confidence = ocr(pdf_bytes, page_number)
            source = "ocr" if text else "none"
            ocr_used = True
        else:
            text = embedded
            source = "embedded_text" if text else "none"

        if len(text) > remaining:
            text = text[:remaining]
            truncated = True
        pages.append(
            {
                "page": page_number,
                "text": text,
                "source": source,
                "chars": len(text),
                "ocr_confidence": confidence,
            }
        )
        remaining -= len(text)
        if remaining == 0 and page_number < page_end:
            truncated = True
            break

    return {
        "page_count": page_count,
        "page_start": page_start,
        "page_end": page_end,
        "pages": pages,
        "ocr_used": ocr_used,
        "truncated": truncated,
        "characters": max_chars - remaining,
    }
