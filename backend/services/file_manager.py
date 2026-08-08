import logging
import os
import uuid
from typing import Optional
from werkzeug.utils import secure_filename

from services.text_processor import CHAPTER_MARKER

log = logging.getLogger("audiobook.file_manager")


class FileManager:
    def __init__(self, upload_folder: str = 'uploads'):
        self.upload_folder = upload_folder
        os.makedirs(upload_folder, exist_ok=True)

    def save_uploaded_file(self, file) -> Optional[str]:
        if file:
            filename = secure_filename(file.filename)
            unique_filename = f"{uuid.uuid4()}_{filename}"
            file_path = os.path.join(self.upload_folder, unique_filename)
            file.save(file_path)
            return file_path
        return None

    def read_text_file(self, file_path: str) -> str:
        _, ext = os.path.splitext(file_path.lower())
        if ext == ".pdf":
            return self._read_pdf(file_path)
        if ext == ".docx":
            return self._read_docx(file_path)
        return self._read_plaintext(file_path)

    @staticmethod
    def _read_pdf(file_path: str) -> str:
        from pdfminer.high_level import extract_text

        return extract_text(file_path) or ""

    @staticmethod
    def _read_docx(file_path: str) -> str:
        """Extract DOCX text, turning Heading 1/2 paragraphs into explicit
        chapter markers so real document structure drives chapter splitting."""
        from docx import Document

        doc = Document(file_path)
        lines = []
        for para in doc.paragraphs:
            text = para.text.strip()
            if not text:
                lines.append("")
                continue
            style = (para.style.name or "").lower() if para.style else ""
            if style.startswith("heading 1") or style.startswith("heading 2") or style == "title":
                lines.append(f"\n{CHAPTER_MARKER} {text}\n")
            else:
                lines.append(text)
        return "\n".join(lines)

    @staticmethod
    def _read_plaintext(file_path: str) -> str:
        for enc in ("utf-8", "latin-1"):
            try:
                with open(file_path, "r", encoding=enc) as f:
                    return f.read()
            except UnicodeDecodeError:
                continue
        with open(file_path, "rb") as f:
            return f.read().decode(errors="ignore")

    def save_audio_file(self, audio_data: bytes, filename: str) -> str:
        file_path = os.path.join(self.upload_folder, filename)
        with open(file_path, 'wb') as f:
            f.write(audio_data)
        return file_path

    def get_file_size(self, file_path: str) -> int:
        return os.path.getsize(file_path)

    def cleanup_file(self, file_path: str):
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
        except Exception:
            log.exception("error cleaning up file %s", file_path)
