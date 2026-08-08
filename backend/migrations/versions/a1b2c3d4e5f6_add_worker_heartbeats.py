"""Add worker_heartbeats table for P0.5 lease + heartbeat tracking.

Revision ID: a1b2c3d4e5f6
Revises: f1a2b3c4d5e6
Create Date: 2026-08-08 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'a1b2c3d4e5f6'
down_revision = 'f1a2b3c4d5e6'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'worker_heartbeats',
        sa.Column('worker_id', sa.String(100), primary_key=True),
        sa.Column('last_seen', sa.DateTime(timezone=True), nullable=False),
        sa.Column('current_job_id', sa.String(36), sa.ForeignKey('jobs.id', ondelete='SET NULL'), nullable=True),
    )


def downgrade():
    op.drop_table('worker_heartbeats')
