"""MCP server tools: direct-call tests against a fresh database."""
import uuid

import pytest

from db.base import Base
from db.models import Job, JobStatus, Organization, Project
from db.session import init_engine, session_scope

import mcp_server


@pytest.fixture()
def seeded(db_url):
    engine = init_engine(db_url)
    Base.metadata.create_all(engine)
    org_id = str(uuid.uuid4())
    with session_scope() as s:
        org = Organization(id=org_id, name="TestOrg")
        s.add(org)
        proj = Project(id=str(uuid.uuid4()), organization_id=org_id,
                       title="Book", source_text="hello")
        s.add(proj)
        job = Job(id=str(uuid.uuid4()), organization_id=org_id, project_id=proj.id,
                  provider="edge", voice_id="v", engine="neural", formats="mp3",
                  status=JobStatus.queued)
        s.add(job)
        s.flush()
        job_id = job.id
    yield {"org_id": org_id, "job_id": job_id}
    Base.metadata.drop_all(engine)


@pytest.fixture()
def writes_enabled(monkeypatch):
    monkeypatch.setenv("MCP_WRITE_ENABLED", "true")


def _make_job(org_id: str, status: JobStatus) -> str:
    """Seed one more job (with its own project) in the given state."""
    with session_scope() as s:
        proj = Project(id=str(uuid.uuid4()), organization_id=org_id,
                       title="Book", source_text="hello")
        s.add(proj)
        job = Job(id=str(uuid.uuid4()), organization_id=org_id, project_id=proj.id,
                  provider="edge", voice_id="v", engine="neural", formats="mp3",
                  status=status)
        s.add(job)
        s.flush()
        return job.id


def test_health(seeded):
    out = mcp_server.acx_health()
    assert out["database"] == "ok"
    assert any(p["name"] == "edge" for p in out["providers"])


def test_list_and_get_job(seeded):
    out = mcp_server.acx_list_jobs()
    assert out["count"] == 1
    assert out["jobs"][0]["job_id"] == seeded["job_id"]

    detail = mcp_server.acx_get_job(seeded["job_id"])
    assert detail["status"] == "queued"
    assert "chapters" in detail


def test_list_jobs_bad_status(seeded):
    out = mcp_server.acx_list_jobs(status="bogus")
    assert "error" in out and "Valid:" in out["error"]


def test_get_job_missing(seeded):
    out = mcp_server.acx_get_job("nope")
    assert "error" in out


def test_orgs_and_usage(seeded):
    orgs = mcp_server.acx_list_organizations()
    assert orgs["count"] == 1 and orgs["organizations"][0]["jobs"] == 1

    usage = mcp_server.acx_usage(seeded["org_id"])
    assert usage["characters"] == 0

    missing = mcp_server.acx_usage(str(uuid.uuid4()))
    assert "error" in missing


def test_write_tools_disabled_by_default(seeded, monkeypatch):
    monkeypatch.delenv("MCP_WRITE_ENABLED", raising=False)
    for call in (lambda: mcp_server.acx_cancel_job(seeded["job_id"]),
                 lambda: mcp_server.acx_approve_job(seeded["job_id"]),
                 lambda: mcp_server.acx_reject_job(seeded["job_id"], reason="x")):
        out = call()
        assert "error" in out and "MCP_WRITE_ENABLED" in out["error"]
    # Nothing was mutated while disabled.
    assert mcp_server.acx_get_job(seeded["job_id"])["status"] == "queued"


def test_cancel_queued_job(seeded, writes_enabled):
    out = mcp_server.acx_cancel_job(seeded["job_id"])
    assert out == {"job_id": seeded["job_id"], "status": "canceled",
                   "cancel_requested": True}
    assert mcp_server.acx_get_job(seeded["job_id"])["status"] == "canceled"


def test_cancel_running_job_is_cooperative(seeded, writes_enabled):
    jid = _make_job(seeded["org_id"], JobStatus.running)
    out = mcp_server.acx_cancel_job(jid)
    assert out["status"] == "running" and out["cancel_requested"] is True


def test_cancel_terminal_job(seeded, writes_enabled):
    jid = _make_job(seeded["org_id"], JobStatus.succeeded)
    out = mcp_server.acx_cancel_job(jid)
    assert "error" in out and "already succeeded" in out["error"]


def test_cancel_bad_and_missing_ids(seeded, writes_enabled):
    assert "error" in mcp_server.acx_cancel_job("nope")
    assert "error" in mcp_server.acx_cancel_job(str(uuid.uuid4()))


def test_approve_needs_review_job(seeded, writes_enabled):
    jid = _make_job(seeded["org_id"], JobStatus.needs_review)
    out = mcp_server.acx_approve_job(jid)
    assert out == {"job_id": jid, "status": "succeeded"}
    again = mcp_server.acx_approve_job(jid)
    assert "error" in again and "not awaiting review" in again["error"]


def test_approve_wrong_state(seeded, writes_enabled):
    out = mcp_server.acx_approve_job(seeded["job_id"])  # still queued
    assert "error" in out and "queued" in out["error"]


def test_reject_records_reason(seeded, writes_enabled):
    jid = _make_job(seeded["org_id"], JobStatus.needs_review)
    out = mcp_server.acx_reject_job(jid, reason="bad audio")
    assert out["status"] == "failed" and out["reason_recorded"] == "bad audio"

    jid2 = _make_job(seeded["org_id"], JobStatus.needs_review)
    out2 = mcp_server.acx_reject_job(jid2)
    assert out2["status"] == "failed"
    assert out2["reason_recorded"] == "rejected after QC review"


def test_tools_are_registered():
    import asyncio

    tools = {t.name: t for t in asyncio.run(mcp_server.mcp.list_tools())}
    assert {"acx_health", "acx_list_jobs", "acx_get_job",
            "acx_list_organizations", "acx_usage",
            "acx_cancel_job", "acx_approve_job", "acx_reject_job"} <= set(tools)
    # Read tools advertise readOnlyHint; write tools must not.
    assert tools["acx_health"].annotations.readOnlyHint is True
    assert not tools["acx_cancel_job"].annotations.readOnlyHint
    assert not tools["acx_approve_job"].annotations.readOnlyHint
    assert not tools["acx_reject_job"].annotations.readOnlyHint
