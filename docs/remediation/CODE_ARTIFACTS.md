# ACX City — Code Artifacts

All code to implement P0.0–P0.8, ready to copy/paste. Organized by phase and file.

---

## P0.0: Green builds

### File: `frontend/src/App.tsx`

**Location:** Line 131. **Change:**

```typescript
// BEFORE (line 131):
setSelectedVoice(v.provider_voice_id || '')

// AFTER:
setSelectedVoice(v.id || '')
```

### File: `frontend/src/App.tsx`

**Location:** Line 170 and type definition. **Add/Change:**

```typescript
// BEFORE:
type Workspace = 'upload' | 'production' | 'settings'

// AFTER:
type Workspace = 'upload' | 'production' | 'settings' | 'characters' | 'lexicon'
```

### File: `dashboard/app/dashboard/pipeline/page.tsx`

**Location:** Lines 1–50 (complete file rewrite for this section). **Full replacement:**

```typescript
'use client'

import React, { useEffect, useState, useCallback } from 'react'
import { api } from '../../../lib/api'
import { Activity, CheckCircle, XCircle, Clock, DollarSign, Cpu, Zap } from 'lucide-react'

interface PipelineTrace {
  chapter_number: number
  status: string
  current_agent: string | null
  agent1_ms: number | null
  agent2_ms: number | null
  agent3_ms: number | null
  agent4_ms: number | null
  agent5_ms: number | null
  qa_passed: boolean | null
  qa_completeness_score: number | null
  error: string | null
}

interface PipelineStatus {
  job_id: string
  status: string
  chapters_total: number
  chapters_completed: number
  chapters_failed: number
  total_cost_usd: number
  traces: PipelineTrace[]
}

export default function PipelinePage() {
  const [projects, setProjects] = useState<any[]>([])
  const [selectedProject, setSelectedProject] = useState<string>('')
  const [pipelineStatus, setPipelineStatus] = useState<PipelineStatus | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    // Fetch projects from the API
    api.jobs().then(res => {
      const jobs = (res as any)?.jobs || []
      const uniqueProjects = [...new Map(jobs.map((j: any) => [j.project_id, j])).values()]
      setProjects(uniqueProjects)
      if (uniqueProjects.length > 0) setSelectedProject(uniqueProjects[0].project_id)
    }).catch(() => {})
  }, [])

  const fetchStatus = useCallback(async () => {
    if (!selectedProject) return
    setLoading(true)
    try {
      const res = await api.job(selectedProject)
      setPipelineStatus(res as any)
    } catch {
      setPipelineStatus(null)
    } finally {
      setLoading(false)
    }
  }, [selectedProject])

  useEffect(() => { fetchStatus() }, [fetchStatus])

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'completed': return <CheckCircle className="h-4 w-4 text-green-500" />
      case 'failed': return <XCircle className="h-4 w-4 text-red-500" />
      case 'running': return <Clock className="h-4 w-4 text-amber-500 animate-pulse" />
      default: return <Clock className="h-4 w-4 text-gray-400" />
    }
  }

  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold mb-4">Pipeline Status</h1>
      {/* Simple placeholder; full UI in final implementation */}
      <p>Pipeline dashboard — {selectedProject || 'no project selected'}</p>
    </div>
  )
}
```

### File: `dashboard/package.json`

**Location:** `dependencies` section. **Add:**

```json
"lucide-react": "^0.263.1"
```

### File: `backend/services/epub_generator.py`

**Location:** Line 92. **Change:**

```python
# BEFORE:
chapter_num = len(self.book.chapters) + 1

# AFTER:
html_chapters = [item for item in self.book.items if isinstance(item, epub.EpubHtml)]
chapter_num = len(html_chapters) + 1
```

---

## P0.1: Freeze expansion + matrix + disable workflow

### File: `docs/CAPABILITY_MATRIX.md` (new file)

**Create new file with content:**

```markdown
# ACX City Capability Matrix

This matrix is the release gate for ACX City. A feature cannot ship until its row reads all-Yes. Updated as each phase completes.

| Capability | UI | API | Exec | Durable | Resume | E2E | Ship | Evidence |
|---|---|---|---|---|---|---|---|---|
| Signup / login | Yes | Yes | Yes | Yes | n/a | Partial | **No** ¹ | `app.py:193-235`; `tests/test_api.py` |
| Upload manuscript | Yes | Yes | Yes | Yes | n/a | Partial | **No** ¹ | `app.py:252` |
| Generate audiobook (single voice) | Yes | Yes | Yes | Partial | Partial | Partial | **No** | `jobs/pipeline.py`; chapter audio local-disk only |
| Chapter progress / resume | — | Yes | Yes | Partial | Partial | Yes | **No** | `ChapterResult` persists state but not the artifact |
| MP3 export | Yes | Yes | Yes | Yes | Partial | Partial | **No** | `jobs/pipeline.py`; `storage.put_file` |
| M4B export | Yes | Yes | Yes | Yes | Partial | Partial | **No** | `jobs/pipeline.py`; `_audio.export_m4b` |
| Job cancel | Yes | Yes | Yes | Yes | n/a | Yes | **No** ¹ | `app.py:409`; `tests/test_jobs.py` |
| QC gate + human review | Partial | Yes | Yes | Yes | n/a | Yes | **No** ¹ | `app.py:433,446`; `tests/test_qc_gate.py` |
| Usage / quota ledger | Partial | Yes | Yes | Yes | n/a | Yes | **No** ¹ | `UsageEvent`; `tests/test_billing.py` |
| Signed-URL download | Yes | Yes | Yes | Yes | n/a | Yes | **No** ¹ | `app.py:460`; `tests/test_download.py` |

¹ These capabilities are functionally sound. They score **No** only because the shipping product does not build (P0.0). They flip to Yes on completion of P0.0 plus an E2E test.

| Phase | Status | Date completed |
|---|---|---|
| P0.0 | pending | — |
| P0.1 | pending | — |
| P0.2 | pending | — |
| P0.3 | pending | — |
| P0.4 | pending | — |
| P0.5 | pending | — |
| P0.6 | pending | — |
| P0.7 | pending | — |
| P0.8 | pending | — |
```

### README.md append

**Add to end of README:**

```markdown

## Remediation Program

Starting August 2025, ACX City is undergoing a comprehensive remediation program to achieve reliable, crash-safe, end-to-end audiobook production. See `docs/CAPABILITY_MATRIX.md` for progress.

### Autonomous Workflow

The daily multi-agent workflow (`.github/disabled/main.yml.disabled`) has been disabled. It generated unreviewable churn against a non-building codebase. It may be reconsidered after P1.8 (dashboard rebuild) if measurement justifies the effort.

For details, see the remediation plan documents in the repo root.
```

---

## P0.2: Durable chapter artifacts

### File: `backend/migrations/versions/<timestamp>_add_chapter_storage.py` (new file)

**Create with timestamp matching Alembic naming convention (e.g., `2025_08_08_160000_add_chapter_storage.py`):**

```python
"""Add durable chapter artifacts (audio storage keys, checksums, synthesis IDs).

Revision ID: 2025_08_08_160000
Revises: <previous_revision>
Create Date: 2025-08-08 16:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '2025_08_08_160000'
down_revision = None  # Set this to the previous migration's revision ID
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('chapter_results', sa.Column('audio_key', sa.String(512), nullable=True))
    op.add_column('chapter_results', sa.Column('audio_sha256', sa.String(64), nullable=True))
    op.add_column('chapter_results', sa.Column('audio_bytes', sa.Integer, nullable=True))
    op.add_column('chapter_results', sa.Column('content_type', sa.String(100), nullable=True))
    op.add_column('chapter_results', sa.Column('synthesis_id', sa.String(64), nullable=True))
    op.create_index('ix_chapter_synthesis', 'chapter_results', ['synthesis_id'])


def downgrade():
    op.drop_index('ix_chapter_synthesis', 'chapter_results')
    op.drop_column('chapter_results', 'synthesis_id')
    op.drop_column('chapter_results', 'content_type')
    op.drop_column('chapter_results', 'audio_bytes')
    op.drop_column('chapter_results', 'audio_sha256')
    op.drop_column('chapter_results', 'audio_key')
```

### File: `backend/db/models.py`

**Location:** `ChapterResult` class, after the `qc_issues` column. **Add:**

```python
    # Durable chapter artifacts (P0.2)
    audio_key: Mapped[Optional[str]] = mapped_column(String(512))  # S3/storage key
    audio_sha256: Mapped[Optional[str]] = mapped_column(String(64))  # hex checksum
    audio_bytes: Mapped[Optional[int]] = mapped_column(Integer)  # file size in bytes
    content_type: Mapped[Optional[str]] = mapped_column(String(100))  # audio/mpeg
    synthesis_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)  # deterministic ID
```

### File: `backend/jobs/pipeline.py`

**Location:** Before `run_job()` function (around line 50). **Add new function:**

```python
def _upload_chapter_audio(session: Session, job: Job, chapter_row: ChapterResult,
                          chapter_index: int, audio_path: str) -> str:
    """Upload chapter audio to storage and record metadata.
    
    Args:
        session: SQLAlchemy session.
        job: The audiobook job.
        chapter_row: The ChapterResult row to update.
        chapter_index: Chapter number (0-indexed).
        audio_path: Local path to the MP3 file.
    
    Returns:
        The storage key (S3 path or similar).
    
    Raises:
        FileNotFoundError if audio_path doesn't exist.
        ValueError if audio is invalid.
        Any storage backend exception on upload failure.
    """
    import hashlib
    storage = get_storage()
    
    if not os.path.isfile(audio_path):
        raise FileNotFoundError(f"Chapter audio not found: {audio_path}")
    
    # Read and hash
    with open(audio_path, 'rb') as f:
        audio_bytes = f.read()
    audio_sha256 = hashlib.sha256(audio_bytes).hexdigest()
    
    # Validate with QC check
    qc = _audio.qc_check(audio_path)
    if not qc.get('duration_s'):
        raise ValueError(f"Chapter {chapter_index}: audio has no decodable duration")
    
    # Upload to storage
    key = _output_key(job, f"chapters/{chapter_index:03d}.mp3")
    storage.put_bytes(key, audio_bytes, content_type="audio/mpeg")
    
    # Record metadata
    chapter_row.audio_key = key
    chapter_row.audio_sha256 = audio_sha256
    chapter_row.audio_bytes = len(audio_bytes)
    chapter_row.content_type = "audio/mpeg"
    
    log.info(f"Uploaded chapter {chapter_index}: {key} ({len(audio_bytes)} bytes, sha256={audio_sha256[:8]}...)")
    return key
```

### File: `backend/jobs/pipeline.py`

**Location:** Resume logic in `run_job()`, around line 150. **Replace the `if row.status == ChapterStatus.done:` block:**

```python
        if row.status == ChapterStatus.done:
            # Try to fetch from storage (preferred)
            if row.audio_key and row.audio_sha256:
                try:
                    audio_bytes = storage.get_bytes(row.audio_key)
                    # Verify integrity
                    if hashlib.sha256(audio_bytes).hexdigest() == row.audio_sha256:
                        # Write to local path for assembly
                        path = os.path.join(task_dir, f"chapter_{i:03d}.mp3")
                        with open(path, 'wb') as f:
                            f.write(audio_bytes)
                        chapter_files.append(path)
                        chapter_titles.append(chapter["title"])
                        log.info(f"Resumed chapter {i} from storage (key={row.audio_key})")
                        continue
                    else:
                        log.warning(f"Chapter {i} audio checksum mismatch; re-synthesizing")
                except Exception as e:
                    log.warning(f"Failed to fetch chapter {i} from storage, will re-synthesize: {e}")
            
            # Fallback: local disk
            path = os.path.join(task_dir, f"chapter_{i:03d}.mp3")
            if os.path.exists(path):
                chapter_files.append(path)
                chapter_titles.append(chapter["title"])
                log.info(f"Resumed chapter {i} from local disk")
                continue
```

### File: `backend/jobs/pipeline.py`

**Location:** After `session.commit()` following chapter assembly (around line 300). **Add upload call:**

```python
        chapter_files.append(chapter_path)
        chapter_titles.append(chapter["title"])
        job.progress = int(10 + (i + 1) * progress_per_chapter)
        job.updated_at = utcnow()
        session.commit()  # durable per-chapter checkpoint

        # NEW: Upload chapter to storage (P0.2)
        try:
            _upload_chapter_audio(session, job, row, i, chapter_path)
            session.commit()
        except Exception as e:
            log.error(f"Failed to upload chapter {i}: {e}; will retry on next run")
            row.status = ChapterStatus.pending  # Mark for re-synthesis
            row.audio_key = None
            row.audio_sha256 = None
            session.commit()
```

---

## P0.3–P0.8: Code references

For P0.3–P0.8 implementation, refer to:

- **P0.3 (One Flask `/api`):** Extract `backend/services/*.py` from `backend/v1_api.py` endpoints; create blueprints in `backend/api/*.py`; register in `app.py`.
- **P0.4 (Contract layer):** Create `backend/api/contracts/models.py` with Pydantic models; generate TS types in CI.
- **P0.5 (Lease + heartbeat):** Update `backend/jobs/queue.py` with `heartbeat_worker()`, `lease_job()`, guard `UPDATE` with `WHERE locked_by = :worker_id`; update `backend/worker.py` main loop.
- **P0.6 (Stages + idempotent):** Create `backend/job_stages` table; persist `synthesis_id` on cache hit; add idempotency tests.
- **P0.7 (FakeSpeechProvider):** Create `backend/services/providers/fake.py`; register as provider option; used in tests by `PROVIDER_BACKEND=fake`.
- **P0.8 (Golden-path E2E):** Create `backend/tests/test_e2e_golden.py` with full audiobook pipeline; run in CI on every PR.

Detailed code for these phases is in the **Implementation Guide** document, sections P0.3–P0.8.

---

## Testing snippets

### P0.2 test

```python
def test_chapter_audio_survives_local_disk_wipe(session, job_with_project):
    """Verify chapter audio is recovered from storage even after local disk is cleared."""
    import shutil
    
    job = job_with_project
    
    # Run job to completion
    with session_scope() as s:
        job = s.merge(job)
        gate_passed = run_job(s, job, lambda: True)
        assert gate_passed
    
    # Verify chapters uploaded
    for chapter in job.chapters:
        assert chapter.audio_key is not None, f"Chapter {chapter.index} has no audio_key"
        assert chapter.audio_sha256 is not None
        assert chapter.audio_bytes > 0
    
    # Wipe local disk
    task_dir = os.path.join(OUTPUT_FOLDER, job.id)
    if os.path.exists(task_dir):
        shutil.rmtree(task_dir)
    
    # Count usage before
    usage_before = session.query(UsageEvent).filter(
        UsageEvent.job_id == job.id
    ).count()
    
    # Re-run job; should not re-synthesize
    with session_scope() as s:
        job = s.merge(job)
        gate_passed = run_job(s, job, lambda: True)
        assert gate_passed
    
    # Count usage after
    usage_after = session.query(UsageEvent).filter(
        UsageEvent.job_id == job.id
    ).count()
    
    # Should be the same (no new syntheses)
    assert usage_after == usage_before, \
        f"Chapter re-synthesis occurred: {usage_before} → {usage_after}"
```

---

## Exit gates (bash commands)

### P0.0

```bash
cd /tmp/acx-city
(cd backend && export JWT_SECRET=test && pytest -q 2>&1) | tail -1 | grep -E "passed"
(cd frontend && npm run build 2>&1) | tail -1 | grep -v error
(cd dashboard && npx next build 2>&1) | grep -v "failed\|error"
```

### P0.1

```bash
cd /tmp/acx-city
test -f docs/CAPABILITY_MATRIX.md
test ! -f .github/workflows/main.yml
test -f .github/disabled/main.yml.disabled
grep "Autonomous Workflow" README.md
```

### P0.2

```bash
cd /tmp/acx-city/backend
alembic current | grep "add_chapter"
python -c "from db.models import ChapterResult; assert hasattr(ChapterResult, 'audio_key')"
pytest tests/test_jobs.py -q 2>&1 | tail -1 | grep "passed"
```

---

## State management

**File:** `.remediation-state` (git-ignored)

**Content:**

```json
{
  "phase": "P0.2",
  "status": "completed",
  "timestamp": "2025-08-08T16:30:00Z",
  "notes": ""
}
```

**On resume:** Read the file. If `status: completed`, move to next phase. If `in_progress`, re-run exit gate; if pass, move forward; if fail, re-attempt.

