# ACX City Capability Matrix

This matrix is the release gate for ACX City. A feature cannot ship until its row reads all-Yes. Updated as each phase completes.

**Column definitions:**
- **UI** — a user-reachable control exists in `frontend/`
- **API** — an endpoint exists on the canonical Flask `/api` surface and returns a valid response
- **Exec** — the code path runs in the deployed production topology (Flask + `worker.py`). Celery/FastAPI paths score **No**
- **Durable** — result survives a container replacement (object storage or Postgres, not local disk)
- **Resume** — a worker kill mid-operation resumes without duplicate paid synthesis
- **E2E** — an automated test exercises the full path from API to persisted output
- **Ship** — all of the above are Yes

| Capability | UI | API | Exec | Durable | Resume | E2E | Ship | Evidence |
|---|---|---|---|---|---|---|---|---|
| Signup / login | Yes | Yes | Yes | Yes | n/a | Yes | **Yes** | `app.py:193-235`; `test_e2e_golden_path.py` |
| Upload manuscript | Yes | Yes | Yes | Yes | n/a | Partial | **No** | `app.py:252`; golden path uses inline text, file-upload path not E2E tested |
| Generate audiobook (single voice) | Yes | Yes | Yes | Yes | Yes | Yes | **Yes** | `jobs/pipeline.py`; P0.2 durable artifacts; P0.5+P0.6 resume; `test_e2e_golden_path.py` |
| Chapter progress / resume | — | Yes | Yes | Yes | Yes | Yes | **Yes** | P0.2 storage keys on `ChapterResult`; P0.5+P0.6 stage checkpoints |
| MP3 export | Yes | Yes | Yes | Yes | Yes | Yes | **Yes** | P0.6 idempotent billing; `test_jobs.py::test_worker_runs_job_end_to_end` |
| M4B export | Yes | Yes | Yes | Yes | Yes | Yes | **Yes** | P0.6 idempotent billing; `test_jobs.py::test_worker_runs_job_end_to_end` checks `output_m4b` |
| Job cancel | Yes | Yes | Yes | Yes | n/a | Yes | **Yes** | `app.py:409`; `test_e2e_golden_path.py::test_golden_path_cancel` |
| QC gate + human review | Partial | Yes | Yes | Yes | n/a | Yes | **Yes** | `app.py:433,446`; `tests/test_qc_gate.py`; stub exercised in golden path |
| Usage / quota ledger | Partial | Yes | Yes | Yes | Yes | Yes | **Yes** | P0.6 idempotent `record_usage(synthesis_id=…)`; `tests/test_billing.py` |
| Signed-URL download | Yes | Yes | Yes | Yes | n/a | Yes | **Yes** | `app.py:460`; `test_e2e_golden_path.py` asserts `url` non-empty |
| Character detection | Yes | `/api` | Yes | Yes | n/a | **No** | **No** | `api/voxengine.py:46-69`; no dedicated E2E test yet (P1.x) |
| Character voice assignment | Yes | `/api` | Yes | Yes | n/a | **No** | **No** | `api/voxengine.py:72-123`; `CharacterVoiceMap` in Postgres |
| Pronunciation lexicon | Yes | `/api` | Yes | Yes | n/a | **No** | **No** | `api/voxengine.py:127-241` |
| Multi-agent pipeline | Partial | `/api` | Flag-gated | Partial | No | **No** | **No** | `PIPELINE_ENABLED` default `false`; `api/voxengine.py:244-299` |
| Voice preview | Yes | **Broken** | **No** | No | No | **No** | **No** | Field mismatch: API returns `sample_audio_url`, frontend expects `sample_url`; `/api/voices/<id>/sample` route missing |
| Chapter streaming | Partial | **Broken** | **No** | No | No | **No** | **No** | `JobStatus.completed` does not exist; `ProviderRegistry` has no `first_available` |
| Waveform | Partial | Stub | Yes | No | n/a | **No** | **No** | `api/voxengine.py:420-437` returns 200 + `duration_s` + `peaks:[]`; peaks pre-computation deferred to P1.6 |
| Single-chapter rerender | Partial | 503 | **No** | No | No | **No** | **No** | `api/voxengine.py:403-417` returns 503 with explanation; Celery worker required (P1.5) |
| Voice cloning | Yes | **501** | **No** | No | No | **No** | **No** | `api/voxengine.py:367-371` raises `501`; implementation deferred to P2.1 |
| EPUB export (from job) | Partial | **Broken** | **No** | No | No | **No** | **No** | Wrong ORM attrs; no `text_content` column |
| EPUB export (client-supplied) | Partial | Partial | Yes | Yes | n/a | Yes | **Yes** | `app.py:618`; 5 tests passing |

## Phase tracker

| Phase | Scope | Status | Date |
|---|---|---|---|
| **P0.0** | Get `main` green | ✅ Complete | 2026-08-08 |
| **P0.1** | Freeze expansion + capability matrix + disable autonomous workflow | ✅ Complete | 2026-08-08 |
| **P0.2** | Durable chapter artifacts | ✅ Complete | 2026-08-08 |
| **P0.3** | One Flask `/api` surface (remove `/v1`) | ✅ Complete | 2026-08-08 |
| **P0.4** | Contract layer + generated TS types | ✅ Complete | 2026-08-08 |
| **P0.5** | Lease + heartbeat + orphan recovery | ✅ Complete | 2026-08-08 |
| **P0.6** | Stage checkpoints + idempotent synthesis | ✅ Complete | 2026-08-08 |
| **P0.7** | `FakeSpeechProvider` | ✅ Complete | 2026-08-08 |
| **P0.8** | Golden-path E2E test in CI | ✅ Complete | 2026-08-08 |
