"""
EPUB generation service for ACX City.

Generates EPUB 3.0 ebooks from project chapters with:
- Proper EPUB structure and metadata
- Chapter detection from text
- Cover image support  
- Table of contents generation
- Styling and formatting
"""

import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, BinaryIO
from ebooklib import epub
from PIL import Image
import io
import re


class EPUBGenerator:
    """Generate EPUB files from project content."""

    def __init__(self, title: str, author: str, language: str = "en"):
        """
        Initialize EPUB generator.
        
        Args:
            title: Book title
            author: Author name  
            language: Language code (default: en)
        """
        self.title = title
        self.author = author
        self.language = language
        self.book = epub.EpubBook()
        self._setup_book()

    def _setup_book(self):
        """Setup basic book metadata."""
        self.book.set_identifier(f"acx-{uuid.uuid4()}")
        self.book.set_title(self.title)
        self.book.set_language(self.language)
        self.book.add_author(self.author)
        self.book.set_cover("cover.png", b"")  # Will be updated later

    def add_cover(self, image_path: Optional[str] = None, image_data: Optional[bytes] = None):
        """
        Add cover image to EPUB.
        
        Args:
            image_path: Path to image file
            image_data: Image data as bytes
        """
        if image_path and os.path.exists(image_path):
            with open(image_path, "rb") as f:
                image_data = f.read()
        elif not image_data:
            # Generate a simple cover if none provided
            image_data = self._generate_default_cover()

        self.book.set_cover("cover.png", image_data)

    def _generate_default_cover(self) -> bytes:
        """Generate a simple default cover image."""
        width, height = 600, 800
        img = Image.new("RGB", (width, height), color="steelblue")

        # Add title text (simple implementation)
        # In production, use PIL.ImageDraw to add text
        img_bytes = io.BytesIO()
        img.save(img_bytes, format="PNG")
        return img_bytes.getvalue()

    def add_chapter(
        self, title: str, content: str, chapter_num: int = None
    ) -> epub.EpubHtml:
        """
        Add chapter to EPUB.
        
        Args:
            title: Chapter title
            content: HTML content
            chapter_num: Chapter number for ordering
            
        Returns:
            EpubHtml chapter object
        """
        if chapter_num is None:
            html_chapters = [item for item in self.book.items if type(item) is epub.EpubHtml]
            chapter_num = len(html_chapters) + 1

        # Create chapter
        chapter = epub.EpubHtml(
            uid=f"chap_{chapter_num}",
            file_name=f"chap_{chapter_num:03d}.xhtml",
            lang=self.language,
        )
        chapter.title = title
        chapter.content = self._wrap_content(title, content)

        # Add to book
        self.book.add_item(chapter)
        return chapter

    def _wrap_content(self, title: str, content: str) -> str:
        """Wrap content in proper XHTML."""
        # Clean HTML entities
        content = content.replace("&", "&amp;")
        content = content.replace("<", "&lt;")
        content = content.replace(">", "&gt;")

        return f"""
        <html xmlns="http://www.w3.org/1999/xhtml">
            <head>
                <title>{title}</title>
                <style type="text/css">
                    body {{
                        font-family: "Georgia", serif;
                        font-size: 1.2em;
                        line-height: 1.6;
                        margin: 1em;
                    }}
                    h1 {{
                        font-size: 1.8em;
                        margin-top: 0.5em;
                        margin-bottom: 0.5em;
                        text-align: center;
                    }}
                    p {{
                        text-align: justify;
                        text-indent: 1em;
                        margin: 0;
                    }}
                    p:first-of-type {{
                        text-indent: 0;
                    }}
                </style>
            </head>
            <body>
                <h1>{title}</h1>
                {content}
            </body>
        </html>
        """

    def add_chapters_from_text(self, text: str, title_prefix: str = "Chapter"):
        """
        Auto-detect and add chapters from text.
        
        Looks for common chapter markers like:
        - Chapter 1
        - CHAPTER 1
        - Part 1
        - Section 1
        
        Args:
            text: Raw text content
            title_prefix: Prefix for auto-detected chapters
        """
        # Split by chapter markers
        chapter_pattern = r"(?:^|\n)(chapter|part|section|act)\s+(\d+)[:\s]+(.+?)(?=\n(?:chapter|part|section|act)\s+\d+|$)"
        matches = re.finditer(chapter_pattern, text, re.IGNORECASE | re.DOTALL)

        chapters = []
        for match in matches:
            marker_type = match.group(1).lower()
            num = match.group(2)
            content = match.group(3).strip()

            if content:
                title = f"{marker_type.capitalize()} {num}"
                chapters.append({"title": title, "content": content})

        # If no chapters found, treat whole text as single chapter
        if not chapters:
            chapters.append({"title": "Content", "content": text})

        # Add all chapters
        for i, chapter in enumerate(chapters, 1):
            self.add_chapter(chapter["title"], chapter["content"], i)

    def generate_toc(self):
        """Generate table of contents."""
        # Get all chapters
        chapters = [item for item in self.book.items if type(item) is epub.EpubHtml]

        if not chapters:
            return

        # Build TOC from Link objects (ebooklib 0.18 requires Link, not EpubHtml)
        # EpubHtml stores uid as .id (the constructor param 'uid' maps to self.id)
        self.book.toc = [epub.Link(c.file_name, c.title, c.id) for c in chapters]

        # Add spine
        self.book.spine = ["nav"] + chapters

        # Add navigation files (guard against duplicate items)
        existing_ids = {item.id for item in self.book.items}
        if "ncx" not in existing_ids:
            self.book.add_item(epub.EpubNcx())
        if "nav" not in existing_ids:
            self.book.add_item(epub.EpubNav())

    def save(self, output_path: str) -> str:
        """
        Save EPUB to file.
        
        Args:
            output_path: Path to save EPUB file
            
        Returns:
            Path to saved EPUB file
        """
        # Generate TOC before saving
        self.generate_toc()

        # Ensure output directory exists
        output_dir = os.path.dirname(output_path) or "."
        os.makedirs(output_dir, exist_ok=True)

        # Write EPUB
        epub.write_epub(output_path, self.book, {})
        return output_path

    def to_bytes(self) -> bytes:
        """
        Generate EPUB as bytes.
        
        Returns:
            EPUB file as bytes
        """
        # Generate TOC before saving
        self.generate_toc()

        # Write to bytes
        output = io.BytesIO()
        epub.write_epub(output, self.book, {})
        return output.getvalue()

    @staticmethod
    def from_chapters_list(
        title: str,
        author: str,
        chapters: list[dict],
        cover_path: Optional[str] = None,
    ) -> "EPUBGenerator":
        """
        Create EPUB from list of chapters.
        
        Args:
            title: Book title
            author: Author name
            chapters: List of {"title": str, "content": str} dicts
            cover_path: Optional path to cover image
            
        Returns:
            EPUBGenerator instance
        """
        gen = EPUBGenerator(title, author)

        if cover_path:
            gen.add_cover(cover_path)

        for i, ch in enumerate(chapters, 1):
            gen.add_chapter(ch["title"], ch["content"], i)

        return gen

    @staticmethod
    def from_text(
        title: str,
        author: str,
        text: str,
        cover_path: Optional[str] = None,
    ) -> "EPUBGenerator":
        """
        Create EPUB from raw text.
        
        Args:
            title: Book title
            author: Author name
            text: Raw text content
            cover_path: Optional path to cover image
            
        Returns:
            EPUBGenerator instance
        """
        gen = EPUBGenerator(title, author)

        if cover_path:
            gen.add_cover(cover_path)

        gen.add_chapters_from_text(text)
        return gen


def generate_epub_from_project(
    project_title: str,
    project_author: str,
    chapters_data: list[dict],
    output_path: str,
    cover_image: Optional[str] = None,
) -> str:
    """
    Convenience function to generate EPUB from project data.
    
    Args:
        project_title: Project/book title
        project_author: Author name
        chapters_data: List of {"title": str, "content": str}
        output_path: Path to save EPUB
        cover_image: Optional cover image path
        
    Returns:
        Path to generated EPUB
    """
    generator = EPUBGenerator.from_chapters_list(
        project_title, project_author, chapters_data, cover_image
    )
    return generator.save(output_path)
