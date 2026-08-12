# ACX City Capability Matrix

This matrix is the release gate for ACX City. A feature cannot ship until its row reads all-Yes. Updated as each phase completes.

**Re-audited 2026-08-12 (post-P1.0).** The original E2E column was soft: until P1.0, `FakeSpeechProvider` emitted 23 undecodable bytes and every audio-touching assertion ran against stubs, so no test ever verified that produced audio decodes. Rows whose E2E evidence turned out to be stubbed or fabricated bytes were demoted to Partial and their Ship flipped to **No**; rows re-earned their Yes only where `test_golden_path_real_audio_decodable` (real synthesis, real assembly, ffprobe on the exports) or an equivalent real-audio assertion now covers them. Separate caveat: GitHub Actions has been billing-locked since before 2026-08-07 — **all** E2E verification is local until the lock clears (see docs/remediation/FOUND.md).

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
| Generate audiobook (single voice) | Yes | Yes | Yes | Yes | Yes | Yes | **Yes** | `test_golden_path_real_audio_decodable`: real synthesis+assembly, ffprobe decode, duration plausibility (P1.0) |
| Chapter progress / resume | — | Yes | Yes | Yes | Yes | Yes | **Yes** | `test_resume_reuses_storage_audio_without_rebilling` (P1.1): real audio, task dir + cache wiped, zero new UsageEvents, re-assembled export decodes |
| MP3 export | Yes | Yes | Yes | Yes | Yes | Yes | **Yes** | `test_golden_path_real_audio_decodable`: export downloaded via signed URL, decodes via ffprobe (P1.0) |
| M4B export | Yes | Yes | Yes | Yes | Yes | Yes | **Yes** | `test_golden_path_real_audio_decodable`: M4B decodes; chapter atoms count+order verified (P1.0) |
| Job cancel | Yes | Yes | Yes | Yes | n/a | Yes | **Yes** | `app.py:409`; `test_e2e_golden_path.py::test_golden_path_cancel` |
| QC gate + human review | Partial | Yes | Yes | Yes | n/a | Yes | **Yes** | `test_qc_block_holds_job_on_real_gappy_audio` (P1.1): block policy holds real high-silence audio; warn passes it; approve/reject flow in `test_qc_gate.py` |
| Usage / quota ledger | Partial | Yes | Yes | Yes | Yes | Yes | **Yes** | P0.6 idempotent `record_usage(synthesis_id=…)`; `tests/test_billing.py` |
| Signed-URL download | Yes | Yes | Yes | Yes | n/a | Yes | **Yes** | `test_golden_path_real_audio_decodable` follows the signed URL and decodes the fetched bytes (P1.0) |
| Character detection | Yes | `/api` | Yes | Yes | n/a | Yes | **Yes** | `api/voxengine.py:46-69`; `test_e2e_voxengine.py::test_character_lifecycle` |
| Character voice assignment | Yes | `/api` | Yes | Yes | n/a | Yes | **Yes** | `api/voxengine.py:72-123`; `test_e2e_voxengine.py::test_character_update` |
| Pronunciation lexicon | Yes | `/api` | Yes | Yes | n/a | Yes | **Yes** | `api/voxengine.py:127-241`; `test_e2e_voxengine.py::test_lexicon_lifecycle` |
| Multi-agent pipeline | Partial | `/api` | Flag-gated | Partial | No | Yes | **No** | P1.2: typed fallbacks per stage, degradation surfaced (`test_pipeline_convergence.py`); Celery fabric deleted — runs inside worker only. Still flag-gated default off |
| Voice preview | Yes | `/api` | Yes | Yes | n/a | Yes | **Yes** | `test_voice_sample_synthesized_on_demand` asserts the sample decodes, is non-silent, and is deterministic (P1.0) |
| Chapter streaming | Partial | Yes | Yes | Yes | n/a | Partial | **No** | Streaming E2E serves stubbed chapter bytes; preview E2E asserts patched provider bytes verbatim. Re-earn in P1.4 |
| Waveform | Partial | Yes | Yes | No | n/a | Partial | **No** | E2E ran over stubbed audio; also Durable=No — the previous Ship=Yes violated the all-Yes rule outright |
| Single-chapter rerender | Partial | 503 | **No** | No | No | Yes | **No** | `api/voxengine.py:403-417`; `test_e2e_voxengine.py::test_rerender_not_implemented` |
| Voice cloning | Yes | 201/GET/DELETE | Yes | Yes | n/a | Partial | **No** | Lifecycle E2E only (CRUD round-trip of arbitrary bytes); nothing synthesizes with a cloned voice. Gated behind a real provider pipeline (P2.1) |
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
| **P0.8** | Golden-path E2E test in CI | ⚠️ Re-done 2026-08-12 | Original gate unmet: no decodability assertion existed and CI never ran (billing lock). Honest gate landed with P1.0 |
| **P1.0** | FakeSpeechProvider emits real decodable audio; live decodability assertion in the golden path; matrix re-audit | ✅ Complete | 2026-08-12 |
| **P1.1** | Media validation before QC (validate → upload → verify → done ordering), cache-hit validation + eviction, `qc_policy_version`, paid fake twin | ✅ Complete | 2026-08-12 |
| **P1.2** | Pipeline convergence: typed fallbacks, explicit stage checks, degradation surfaced; Celery/Redis task fabric deleted | ✅ Complete | 2026-08-12 |
