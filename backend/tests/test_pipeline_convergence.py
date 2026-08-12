"""P1.2: multi-agent pipeline convergence.

Gate: forced failure of each agent produces a typed fallback, not an
AttributeError. Required stages (structure parser, text normalizer) degrade
explicitly to basic preprocessing with the failure surfaced; optional stages
(character attribution, prosody planner, QA validator) continue with
deterministic fallback data and the degradation listed in metadata.
"""
import pytest
from sqlalchemy import select

from db.base import utcnow
from db.session import session_scope
from db import models as m
from db.voxengine_models import PipelineTrace
from pipeline.integration import preprocess_chapter_pipeline

CHAPTER_TEXT = (
    'The road stretched on. "We should rest," said Marla, eyeing the ridge. '
    '"Not yet," Tomas replied. "The pass closes at dusk." They walked on in '
    'silence, boots crunching the frost. ' * 6
)

AGENTS = [
    # (module, class name, stage key, required?)
    ("pipeline.agents.structure_parser", "StructureParser", "structure_parser", True),
    ("pipeline.agents.character_attribution", "CharacterAttribution", "character_attribution", False),
    ("pipeline.agents.text_normalizer", "TextNormalizer", "text_normalizer", True),
    ("pipeline.agents.prosody_planner", "ProsodyPlanner", "prosody_planner", False),
    ("pipeline.agents.qa_validator", "QAValidator", "qa_validator", False),
]


def _seed(session):
    org = m.Organization(name="Org")
    user = m.User(email=f"p{utcnow().timestamp()}@x.com", password_hash="h")
    session.add_all([org, user])
    session.flush()
    session.add(m.Membership(user_id=user.id, organization_id=org.id, role=m.Role.owner))
    proj = m.Project(organization_id=org.id, created_by=user.id, title="B",
                     source_text=CHAPTER_TEXT)
    session.add(proj)
    session.flush()
    job = m.Job(organization_id=org.id, project_id=proj.id, provider="fake",
                voice_id="fake-a", formats="mp3", status=m.JobStatus.running)
    session.add(job)
    session.flush()
    return job.id


def _trace_for(session, job_id):
    return session.execute(
        select(PipelineTrace).where(PipelineTrace.job_id == job_id)
        .order_by(PipelineTrace.created_at.desc())
    ).scalars().first()


def test_success_path_metadata_contract(engine):
    with session_scope() as s:
        jid = _seed(s)
        text, meta = preprocess_chapter_pipeline(s, jid, 1, CHAPTER_TEXT, "Ch 1")
        assert isinstance(text, str) and text.strip()
        assert meta["pipeline"] is True
        assert meta["degraded_stages"] == []
        assert meta["fallback_used"] is False
        for key in ("qa_passed", "total_cost_usd", "total_duration_ms",
                    "characters", "suggested_lexicon"):
            assert key in meta, f"metadata contract missing {key}"
        trace = _trace_for(s, jid)
        assert trace is not None and trace.status == "completed"


@pytest.mark.parametrize("module,cls,stage,required", AGENTS)
def test_forced_agent_failure_yields_typed_fallback(engine, monkeypatch,
                                                    module, cls, stage, required):
    import importlib
    agent_cls = getattr(importlib.import_module(module), cls)

    def exploding_run(self, input_data, context):
        raise RuntimeError(f"forced failure of {stage}")

    monkeypatch.setattr(agent_cls, "run", exploding_run)

    with session_scope() as s:
        jid = _seed(s)
        # The gate: this call must not raise (no AttributeError from reading
        # .data/.duration_ms/.cost_usd off an agent instance).
        text, meta = preprocess_chapter_pipeline(s, jid, 1, CHAPTER_TEXT, "Ch 1")

        assert isinstance(text, str) and text.strip(), (
            "pipeline must always return usable text"
        )
        assert stage in meta["degraded_stages"], (
            f"degradation of {stage} must be surfaced, got {meta}"
        )
        trace = _trace_for(s, jid)
        assert trace is not None

        if required:
            assert meta["pipeline"] is False, (
                "required-stage failure must be an explicit degrade, "
                "not a pretend success"
            )
            assert meta.get("error_code"), "error_code must be surfaced"
            assert trace.status == "failed"
        else:
            assert meta["pipeline"] is True
            assert meta["fallback_used"] is True
            assert trace.status == "completed_degraded"
            if stage == "qa_validator":
                assert meta["qa_passed"] is False, (
                    "a failed QA validator must never report qa_passed=True"
                )


def test_celery_fabric_is_gone():
    import importlib
    import pipeline
    assert not hasattr(pipeline, "celery_app")
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("pipeline.tasks")
