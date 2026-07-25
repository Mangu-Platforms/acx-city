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


def test_tools_are_registered():
    import asyncio

    tools = {t.name for t in asyncio.run(mcp_server.mcp.list_tools())}
    assert {"acx_health", "acx_list_jobs", "acx_get_job",
            "acx_list_organizations", "acx_usage"} <= tools
