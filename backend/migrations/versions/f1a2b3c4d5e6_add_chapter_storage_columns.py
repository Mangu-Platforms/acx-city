"""Add durable chapter artifact columns (audio_key, audio_sha256, audio_bytes, content_type, synthesis_id).

Revision ID: f1a2b3c4d5e6
Revises: b3a1f8e2c9d0
Create Date: 2026-08-08 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'f1a2b3c4d5e6'
down_revision = 'b3a1f8e2c9d0'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('chapter_results', sa.Column('audio_key', sa.String(512), nullable=True))
    op.add_column('chapter_results', sa.Column('audio_sha256', sa.String(64), nullable=True))
    op.add_column('chapter_results', sa.Column('audio_bytes', sa.Integer, nullable=True))
    op.add_column('chapter_results', sa.Column('content_type', sa.String(100), nullable=True))
    op.add_column('chapter_results', sa.Column('synthesis_id', sa.String(64), nullable=True))
    op.create_index('ix_chapter_results_synthesis_id', 'chapter_results', ['synthesis_id'])


def downgrade():
    op.drop_index('ix_chapter_results_synthesis_id', table_name='chapter_results')
    op.drop_column('chapter_results', 'synthesis_id')
    op.drop_column('chapter_results', 'content_type')
    op.drop_column('chapter_results', 'audio_bytes')
    op.drop_column('chapter_results', 'audio_sha256')
    op.drop_column('chapter_results', 'audio_key')
