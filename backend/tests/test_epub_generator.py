"""
EPUB Generator Integration Tests and Examples

Quick start:
    python -m pytest tests/test_epub_generator.py -v
"""

from services.epub_generator import EPUBGenerator, generate_epub_from_project
import tempfile
import os


def test_basic_epub_generation():
    """Test basic EPUB generation with title and author."""
    gen = EPUBGenerator("Test Book", "Test Author")
    gen.add_chapter("Chapter 1", "<p>This is chapter 1.</p>")
    gen.add_chapter("Chapter 2", "<p>This is chapter 2.</p>")

    with tempfile.NamedTemporaryFile(suffix=".epub", delete=False) as f:
        path = gen.save(f.name)
        assert os.path.exists(path)
        assert os.path.getsize(path) > 0
        os.unlink(path)


def test_epub_from_chapters_list():
    """Test EPUB generation from chapters list."""
    chapters = [
        {"title": "Introduction", "content": "<p>Welcome to the book.</p>"},
        {"title": "Chapter 1", "content": "<p>The story begins...</p>"},
        {"title": "Conclusion", "content": "<p>And they lived happily.</p>"},
    ]

    gen = EPUBGenerator.from_chapters_list(
        "My Story",
        "John Doe",
        chapters
    )

    epub_bytes = gen.to_bytes()
    assert len(epub_bytes) > 0


def test_epub_from_text_auto_chapter_detection():
    """Test EPUB generation with auto-detected chapters."""
    text = """
    Chapter 1: The Beginning

    This is the first chapter. It introduces the protagonist and the setting.
    The story unfolds as we read more.

    Chapter 2: The Conflict

    The conflict arises when unexpected events occur. The protagonist must
    face challenges and overcome obstacles.

    Chapter 3: The Resolution

    Finally, the protagonist finds peace and the story concludes with
    a satisfying ending.
    """

    gen = EPUBGenerator.from_text(
        "Auto-Detected Book",
        "Anonymous",
        text
    )

    epub_bytes = gen.to_bytes()
    assert len(epub_bytes) > 0
    # Should detect 3 chapters
    assert len([item for item in gen.book.items if hasattr(item, 'content')]) >= 3


def test_epub_with_cover():
    """Test EPUB generation with cover image."""
    # Generate default cover
    gen = EPUBGenerator("Covered Book", "Artist Author")
    gen.add_cover()  # Uses default cover
    gen.add_chapter("Content", "<p>Book content here.</p>")

    epub_bytes = gen.to_bytes()
    assert len(epub_bytes) > 0


def test_convenience_function():
    """Test the convenience function for quick EPUB generation."""
    chapters = [
        {"title": "Part 1", "content": "<p>Content 1</p>"},
        {"title": "Part 2", "content": "<p>Content 2</p>"},
    ]

    with tempfile.NamedTemporaryFile(suffix=".epub", delete=False) as f:
        path = generate_epub_from_project(
            "Convenience Book",
            "Quick Author",
            chapters,
            f.name
        )
        assert os.path.exists(path)
        assert os.path.getsize(path) > 0
        os.unlink(path)


if __name__ == "__main__":
    print("Running EPUB Generator Tests...")
    test_basic_epub_generation()
    print("✓ Basic EPUB generation")

    test_epub_from_chapters_list()
    print("✓ EPUB from chapters list")

    test_epub_from_text_auto_chapter_detection()
    print("✓ EPUB with auto-detected chapters")

    test_epub_with_cover()
    print("✓ EPUB with cover image")

    test_convenience_function()
    print("✓ Convenience function")

    print("\nAll tests passed! ✅")


# API Usage Examples
# ==================

"""
1. Generate EPUB from chapters:

    POST /api/export/epub
    {
        "title": "My Book",
        "author": "Author Name",
        "chapters": [
            {
                "title": "Chapter 1",
                "content": "Chapter content here..."
            },
            {
                "title": "Chapter 2",
                "content": "More chapter content..."
            }
        ]
    }

    Response:
    {
        "success": true,
        "size": 45230,
        "storage_key": "epub/org-id/uuid.epub"
    }


2. Export synthesis job as EPUB:

    GET /api/jobs/{job_id}/export/epub?redirect=1

    This converts an existing synthesis job (with chapters) into an EPUB file
    and returns a signed download URL.

    Parameters:
    - redirect=1: Redirect to download URL instead of returning JSON

    Response:
    {
        "success": true,
        "url": "https://storage.example.com/epub/...",
        "expires_in": 3600,
        "size": 45230
    }


3. Integration with synthesis pipeline:

    The EPUB generator can be called from worker.py to produce EPUBs
    alongside MP3/M4B output after synthesis completes.

    Example in worker.py:

        from services.epub_generator import EPUBGenerator

        # After synthesis completes, generate EPUB
        chapters_data = [
            {
                "title": result.chapter_title,
                "content": result.text_content
            }
            for result in job.chapter_results
        ]

        gen = EPUBGenerator.from_chapters_list(
            job.project.title,
            job.project.author,
            chapters_data
        )
        epub_bytes = gen.to_bytes()

        # Store in object storage
        storage_key = f"epub/{job.organization_id}/{job.id}.epub"
        storage.put_bytes(storage_key, epub_bytes)

        # Update job record
        job.output_epub_key = storage_key


Features:
---------
- EPUB 3.0 compliant
- Auto-detection of chapters from text
- Support for cover images
- Proper formatting and styling
- Signed download URLs for cloud storage
- Multi-tenant support (organization-scoped)
- Efficient bytes generation (no temp files)
- Table of contents generation
"""
