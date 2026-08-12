"""Chapter revisions + active revision pointer (P1.5).

chapter_revisions is the immutable audio history: source_text per revision,
artifact pointers, deterministic synthesis_id, QC verdict + policy version.
chapter_results.active_revision_id points at the live one (plain GUID — no
FK, avoiding the chapter↔revision cycle).
"""
from alembic import op
import sqlalchemy as sa

from db.base import GUID

revision = "d5e6f7a8b9c3"
down_revision = "c4d5e6f7a8b2"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "chapter_revisions",
        sa.Column("id", GUID, primary_key=True),
        sa.Column("chapter_result_id", GUID,
                  sa.ForeignKey("chapter_results.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("revision_number", sa.Integer, nullable=False),
        sa.Column("source_text", sa.Text, nullable=False),
        sa.Column("audio_key", sa.String(512)),
        sa.Column("audio_sha256", sa.String(64)),
        sa.Column("audio_bytes", sa.Integer),
        sa.Column("content_type", sa.String(100)),
        sa.Column("synthesis_id", sa.String(64)),
        sa.Column("qc_result", sa.JSON),
        sa.Column("qc_policy_version", sa.String(32)),
        sa.Column("status", sa.String(20), nullable=False,
                  server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("chapter_result_id", "revision_number",
                            name="uq_chapter_revision_number"),
    )
    op.create_index("ix_chapter_revisions_chapter", "chapter_revisions",
                    ["chapter_result_id"])
    op.create_index("ix_chapter_revisions_synthesis", "chapter_revisions",
                    ["synthesis_id"])
    op.add_column("chapter_results",
                  sa.Column("active_revision_id", GUID, nullable=True))


def downgrade():
    op.drop_column("chapter_results", "active_revision_id")
    op.drop_index("ix_chapter_revisions_synthesis", "chapter_revisions")
    op.drop_index("ix_chapter_revisions_chapter", "chapter_revisions")
    op.drop_table("chapter_revisions")
