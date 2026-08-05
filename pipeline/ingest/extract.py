"""Text extraction from docx, txt, and pdf manuscripts."""

from __future__ import annotations

from pathlib import Path


class ExtractionError(Exception):
    """Raised when a manuscript cannot be extracted."""

    def __init__(self, path: str, reason: str):
        self.path = path
        self.reason = reason
        super().__init__(f"Failed to extract {path}: {reason}")


def extract_text(manuscript_path: str | Path) -> str:
    """Extract plain text from a manuscript file.

    Supported formats: .txt, .docx, .pdf
    Raises ExtractionError on failure.
    """
    path = Path(manuscript_path)
    if not path.exists():
        raise ExtractionError(str(path), "File not found")

    suffix = path.suffix.lower()

    if suffix == ".txt":
        return _extract_txt(path)
    elif suffix == ".docx":
        return _extract_docx(path)
    elif suffix == ".pdf":
        return _extract_pdf(path)
    else:
        raise ExtractionError(str(path), f"Unsupported format: {suffix}")


def _extract_txt(path: Path) -> str:
    """Plain text extraction with encoding detection."""
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            return path.read_text(encoding="latin-1")
        except Exception as e:
            raise ExtractionError(str(path), f"Cannot decode: {e}")


def _extract_docx(path: Path) -> str:
    """Extract text from .docx using python-docx."""
    try:
        from docx import Document
    except ImportError:
        raise ExtractionError(
            str(path),
            "python-docx is not installed. Run: pip install python-docx"
        )

    try:
        doc = Document(str(path))
        paragraphs = []
        for para in doc.paragraphs:
            text = para.text.strip()
            if text:
                paragraphs.append(text)
        return "\n\n".join(paragraphs)
    except Exception as e:
        raise ExtractionError(str(path), f"docx parsing failed: {e}")


def _extract_pdf(path: Path) -> str:
    """Extract text from .pdf using pdfminer.six."""
    try:
        from pdfminer.high_level import extract_text
    except ImportError:
        raise ExtractionError(
            str(path),
            "pdfminer.six is not installed. Run: pip install pdfminer.six"
        )

    try:
        text = extract_text(str(path))
        if not text or not text.strip():
            raise ExtractionError(str(path), "PDF extracted zero text (may be image-only)")
        return text
    except ExtractionError:
        raise
    except Exception as e:
        raise ExtractionError(str(path), f"PDF extraction failed: {e}")
