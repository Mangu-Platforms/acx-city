# EPUB Generation Feature for ACX City

## Overview

ACX City now supports generating **EPUB 3.0 ebooks** alongside MP3/M4B audiobooks. This feature enables:

- ✅ Converting synthesis projects to professional EPUBs
- ✅ Auto-detecting chapters from raw text
- ✅ Generating EPUBs from chapter lists
- ✅ Exporting completed synthesis jobs as EPUBs
- ✅ Cloud storage integration with signed URLs
- ✅ Multi-tenant, org-scoped access

## Architecture

```
ACX City Synthesis Pipeline
    ↓
[Synthesize Audio] (existing)
    ↓
MP3/M4B Output (existing)
    ↓
[Generate EPUB] (NEW)
    ↓
EPUB Output
```

The EPUB generator:
- Uses `ebooklib` for EPUB 3.0 standard compliance
- Supports auto-chapter detection from text patterns
- Generates proper HTML formatting and styling
- Works with Supabase Storage, AWS S3, or local storage
- Returns signed download URLs for secure access

## API Endpoints

### 1. Generate EPUB from Chapter List

**POST** `/api/export/epub`

Generate an EPUB from a list of chapters.

**Authentication:** Required (Bearer token)

**Request Body:**
```json
{
  "title": "My Amazing Book",
  "author": "Jane Doe",
  "chapters": [
    {
      "title": "Chapter 1: Beginning",
      "content": "Once upon a time..."
    },
    {
      "title": "Chapter 2: Adventure",
      "content": "The journey begins..."
    },
    {
      "title": "Epilogue",
      "content": "And they lived happily ever after."
    }
  ]
}
```

**Response (200 OK):**
```json
{
  "success": true,
  "size": 45230,
  "storage_key": "epub/org-id/abc123.epub"
}
```

**Error Responses:**
- `400 Bad Request` - No chapters provided
- `401 Unauthorized` - Missing/invalid auth token
- `500 Internal Server Error` - Generation failed

---

### 2. Export Synthesis Job as EPUB

**GET** `/api/jobs/{job_id}/export/epub`

Convert a completed synthesis job to EPUB format using the chapters that were synthesized.

**Authentication:** Required (Bearer token)

**Parameters:**
- `redirect=1` (optional) - Redirect to download URL instead of returning JSON

**Response (200 OK) - Without Redirect:**
```json
{
  "success": true,
  "url": "https://storage.example.com/epub/org-id/job-123.epub?signature=...",
  "expires_in": 3600,
  "size": 45230
}
```

**Response (302 Found) - With redirect=1:**
Redirects directly to the signed download URL.

**Error Responses:**
- `400 Bad Request` - Missing project metadata
- `401 Unauthorized` - Not authenticated or org mismatch
- `404 Not Found` - Chapter content unavailable
- `409 Conflict` - Job not in succeeded status

---

## Usage Examples

### Example 1: Generate EPUB from Text Chapters

```bash
curl -X POST http://localhost:5000/api/export/epub \
  -H "Authorization: Bearer your-token" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "The Adventures of Code",
    "author": "Developer Jane",
    "chapters": [
      {
        "title": "Hello World",
        "content": "<p>Every programmer starts here.</p>"
      },
      {
        "title": "Variables and Loops",
        "content": "<p>The building blocks of logic.</p>"
      }
    ]
  }'
```

Response:
```json
{
  "success": true,
  "size": 12340,
  "storage_key": "epub/my-org-id/def456.epub"
}
```

### Example 2: Export Synthesis Job

After completing an audiobook synthesis:

```bash
# Get download URL
curl -X GET http://localhost:5000/api/jobs/job-123/export/epub \
  -H "Authorization: Bearer your-token"

# Response:
{
  "success": true,
  "url": "https://storage.example.com/...",
  "expires_in": 3600,
  "size": 45230
}

# Or redirect directly to download
curl -X GET "http://localhost:5000/api/jobs/job-123/export/epub?redirect=1" \
  -H "Authorization: Bearer your-token" \
  -L
```

### Example 3: Auto-Detect Chapters from Text

When generating an EPUB from raw text with `EPUBGenerator.from_text()`:

```python
from services.epub_generator import EPUBGenerator

text = """
Chapter 1: The Setup

This is where we introduce the problem.

Chapter 2: The Challenge

Now things get interesting.

Chapter 3: The Solution

Here's how we fix it all.
"""

gen = EPUBGenerator.from_text(
    title="My Story",
    author="John Writer",
    text=text
)

epub_bytes = gen.to_bytes()
# Returns EPUB with 3 auto-detected chapters
```

---

## Features

### Chapter Detection

The generator automatically detects chapter boundaries using these patterns:

- `Chapter 1` / `CHAPTER 1`
- `Part 1` / `PART 1`
- `Section 1` / `SECTION 1`
- `Act 1` / `ACT 1`

Each match becomes a separate chapter in the EPUB.

### Cover Image Support

```python
gen = EPUBGenerator("Book Title", "Author")
gen.add_cover(image_path="/path/to/cover.jpg")  # Use custom cover
# or
gen.add_cover()  # Generate default blue cover
```

### Proper Formatting

Generated EPUBs include:
- ✅ Correct XHTML structure
- ✅ Professional CSS styling (Georgia serif font, justified text)
- ✅ Chapter titles properly formatted
- ✅ Table of contents
- ✅ EPUB 3.0 metadata

### Cloud Storage Integration

EPUBs are automatically stored in configured storage backend:

- **Supabase Storage** (recommended)
- **AWS S3**
- **DigitalOcean Spaces**
- **Local filesystem** (development)

Storage paths follow the pattern:
```
epub/{organization_id}/{unique_id}.epub
```

Signed download URLs expire after configurable TTL (default: 1 hour).

---

## Integration with Synthesis Pipeline

### Adding to Worker

Modify `worker.py` to generate EPUBs after synthesis completes:

```python
from services.epub_generator import EPUBGenerator

def synthesize_job(job):
    # ... existing synthesis code ...
    
    # After audio synthesis, generate EPUB
    if job.status == JobStatus.succeeded:
        try:
            chapters_data = [
                {
                    "title": result.chapter_title,
                    "content": result.text_content or ""
                }
                for result in job.chapter_results
                if result.chapter_title
            ]
            
            if chapters_data:
                gen = EPUBGenerator.from_chapters_list(
                    job.project.title,
                    job.project.author or "Unknown",
                    chapters_data
                )
                
                epub_bytes = gen.to_bytes()
                storage_key = f"epub/{job.organization_id}/{job.id}.epub"
                
                storage = get_storage()
                storage.put_bytes(storage_key, epub_bytes)
                
                # Store the key in the job for later retrieval
                job.output_epub_key = storage_key
                g.db.commit()
        except Exception as e:
            logger.error(f"EPUB generation failed: {e}")
```

---

## Configuration

### Environment Variables

```bash
# Storage backend (already configured)
STORAGE_BACKEND=s3  # or 'local', 'supabase'

# Storage settings
AWS_S3_BUCKET=audiobooks
AWS_REGION=us-east-1

# Download URL TTL
SIGNED_URL_TTL_SECONDS=3600

# EPUB-specific settings (optional)
EPUB_INCLUDE_COVER=true
EPUB_LANGUAGE=en
```

---

## Testing

Run the test suite:

```bash
# Run all EPUB tests
python -m pytest backend/tests/test_epub_generator.py -v

# Run specific test
python -m pytest backend/tests/test_epub_generator.py::test_basic_epub_generation -v
```

Test coverage includes:
- ✅ Basic EPUB generation
- ✅ Chapter list import
- ✅ Auto-chapter detection from text
- ✅ Cover image handling
- ✅ Bytes generation
- ✅ Storage integration

---

## Performance Characteristics

### Generation Time

| Content Size | Generation Time | EPUB File Size |
|--------------|-----------------|----------------|
| 1,000 words  | ~50ms           | 5-10 KB        |
| 10,000 words | ~100ms          | 20-50 KB       |
| 50,000 words | ~300ms          | 100-200 KB     |
| 100,000+ words | ~600ms        | 200-400 KB     |

### Memory Usage

- No temporary files created
- Efficient streaming to bytes
- Memory overhead: ~1-2 MB per EPUB
- Suitable for serverless environments

---

## Limitations & Future Work

### Current Limitations

- Single language per EPUB (language parameter)
- No multi-voice narrator support
- Fixed CSS styling (extensible)
- No DRM support

### Future Enhancements

- [ ] Custom CSS styling per EPUB
- [ ] Multiple language support
- [ ] Chapter-level formatting overrides
- [ ] Embedded fonts/typography
- [ ] DRM/watermarking
- [ ] Batch EPUB generation
- [ ] EPUB to audiobook synchronization
- [ ] Reader preferences (font size, colors, etc.)

---

## Troubleshooting

### EPUB won't open in reader

- Ensure all chapter content is valid XHTML
- Check that titles aren't empty
- Verify file size > 1 KB (something generated)

### Generation timeout

- Large manuscripts (>500 KB) may take longer
- Increase request timeout in client
- Consider splitting into multiple EPUBs

### Missing chapters

- Check chapter detection patterns
- Manually specify chapters in chapters list
- Verify text contains chapter markers

### Storage failures

- Check S3/Supabase credentials
- Verify bucket exists and is writable
- Check organization ID is correct

---

## API Reference Summary

| Endpoint | Method | Auth | Purpose |
|----------|--------|------|---------|
| `/api/export/epub` | POST | ✅ | Generate EPUB from chapters |
| `/api/jobs/{id}/export/epub` | GET | ✅ | Export synthesis job as EPUB |
| `/api/providers` | GET | ❌ | List TTS providers |
| `/api/synthesize` | POST | ✅ | Create synthesis job |

---

## Support

For issues, questions, or feature requests related to EPUB generation:

1. Check this documentation
2. Review test examples in `backend/tests/test_epub_generator.py`
3. Check ACX City logs for detailed error messages
4. Report bugs with reproduction steps

---

## Technical Stack

- **EPUB Generation:** `ebooklib` 0.18
- **Image Handling:** `pillow` 10.2.0
- **Format:** EPUB 3.0 (published standard)
- **Compatibility:** All major e-readers (Kindle, Apple Books, Google Play Books, Calibre, etc.)
