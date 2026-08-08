"""Stage checkpoints (job_stages) and idempotent billing (synthesis_id on usage_events).

Revision ID: b2c3d4e5f6a1
Revises: a1b2c3d4e5f6
Create Date: 2026-08-08 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'b2c3d4e5f6a1'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade():
    # Deduplication key on usage_events — nullable; populated going forward.
    op.add_column('usage_events', sa.Column('synthesis_id', sa.String(64), nullable=True))
    op.create_index('ix_usage_job_synthesis', 'usage_events', ['job_id', 'synthesis_id'])

    # Fine-grained stage checkpoints per chapter per job.
    op.create_table(
        'job_stages',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('job_id', sa.String(36), sa.ForeignKey('jobs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('chapter_index', sa.Integer, nullable=False),
        sa.Column('stage_name', sa.String(50), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('metadata_json', sa.Text, nullable=True),
        sa.UniqueConstraint('job_id', 'chapter_index', 'stage_name', name='uq_job_stage'),
    )
    op.create_index('ix_job_stages_job_id', 'job_stages', ['job_id'])


def downgrade():
    op.drop_index('ix_job_stages_job_id', table_name='job_stages')
    op.drop_table('job_stages')
    op.drop_index('ix_usage_job_synthesis', table_name='usage_events')
    op.drop_column('usage_events', 'synthesis_id')
