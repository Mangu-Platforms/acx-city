"""Add qc_policy_version to chapter_results (P1.1).

Chapters record which validation+QC profile they were built under, so books
built before a threshold change stay interpretable.
"""
from alembic import op
import sqlalchemy as sa

revision = "c4d5e6f7a8b2"
down_revision = "b2c3d4e5f6a1"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "chapter_results",
        sa.Column("qc_policy_version", sa.String(32), nullable=True),
    )


def downgrade():
    op.drop_column("chapter_results", "qc_policy_version")
