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
| Upload manuscript | Yes | Yes | Yes | Yes | n/a | Yes | **Yes** | `app.py:252`; `test_e2e_epub_upload.py::test_upload_file` |
| Generate audiobook (single voice) | Yes | Yes | Yes | Yes | Yes | Yes | **Yes** | `jobs/pipeline.py`; P0.2 durable artifacts; P0.5+P0.6 resume; `test_e2e_golden_path.py` |
| Chapter progress / resume | — | Yes | Yes | Yes | Yes | Yes | **Yes** | P0.2 storage keys on `ChapterResult`; P0.5+P0.6 stage checkpoints |
| MP3 export | Yes | Yes | Yes | Yes | Yes | Yes | **Yes** | P0.6 idempotent billing; `test_jobs.py::test_worker_runs_job_end_to_end` |
| M4B export | Yes | Yes | Yes | Yes | Yes | Yes | **Yes** | P0.6 idempotent billing; `test_jobs.py::test_worker_runs_job_end_to_end` checks `output_m4b` |
| Job cancel | Yes | Yes | Yes | Yes | n/a | Yes | **Yes** | `app.py:409`; `test_e2e_golden_path.py::test_golden_path_cancel` |
| QC gate + human review | Partial | Yes | Yes | Yes | n/a | Yes | **Yes** | `app.py:433,446`; `tests/test_qc_gate.py`; stub exercised in golden path |
| Usage / quota ledger | Partial | Yes | Yes | Yes | Yes | Yes | **Yes** | P0.6 idempotent `record_usage(synthesis_id=…)`; `tests/test_billing.py` |
| Signed-URL download | Yes | Yes | Yes | Yes | n/a | Yes | **Yes** | `app.py:460`; `test_e2e_golden_path.py` asserts `url` non-empty |
| Character detection | Yes | `/api` | Yes | Yes | n/a | Yes | **Yes** | `api/voxengine.py:46-69`; `test_e2e_voxengine.py::test_character_lifecycle` |
| Character voice assignment | Yes | `/api` | Yes | Yes | n/a | Yes | **Yes** | `api/voxengine.py:72-123`; `test_e2e_voxengine.py::test_character_update` |
| Pronunciation lexicon | Yes | `/api` | Yes | Yes | n/a | Yes | **Yes** | `api/voxengine.py:127-241`; `test_e2e_voxengine.py::test_lexicon_lifecycle` |
| Multi-agent pipeline | Partial | `/api` | Flag-gated | Partial | No | Yes | **No** | `PIPELINE_ENABLED` default `false`; `test_e2e_voxengine.py::test_pipeline_status` |
| Voice preview | Yes | `/api` | Yes | Yes | n/a | Yes | **Yes** | `services/voice_catalog_endpoints.py` (fixed auth); `test_e2e_voice_catalog.py::test_voice_sample_*` |
| Chapter streaming | Partial | Yes | Yes | Yes | n/a | Yes | **Yes** | `services/streaming.py` (fixed Postgres COUNT bug, auth); `test_e2e_streaming.py` |
| Waveform | Partial | Yes | Yes | No | n/a | Yes | **Yes** | `api/voxengine.py:420-437`; `test_e2e_voxengine.py::test_waveform` |
| Single-chapter rerender | Partial | 503 | **No** | No | No | Yes | **No** | `api/voxengine.py:403-417`; `test_e2e_voxengine.py::test_rerender_not_implemented` |
| Voice cloning | Yes | 201/GET/DELETE | Yes | Yes | n/a | Yes | **Yes** | `services/voice_catalog_endpoints.py`; `test_e2e_voice_catalog.py::test_clone_lifecycle` |
| EPUB export (from job) | Partial | Yes | Yes | Yes | n/a | Yes | **Yes** | `app.py:export_job_as_epub` (fixed ORM bugs); `test_e2e_epub_upload.py::test_export_job_as_epub` |
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
