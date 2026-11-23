"""add validation fields to agent_experiences

Revision ID: c8d9e0f1a2b3
Revises: b7f1c2d3e4a5
Create Date: 2026-11-23 18:30:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'c8d9e0f1a2b3'
down_revision = 'b7f1c2d3e4a5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('agent_experiences') as batch_op:
        batch_op.add_column(sa.Column('validation_note', sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column('keywords', sa.JSON(), nullable=False, server_default='[]')
        )
        batch_op.add_column(
            sa.Column('use_count', sa.Integer(), nullable=False, server_default='0')
        )
        batch_op.add_column(
            sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.create_index(
            'ix_experiences_agent_status',
            ['agent_id', 'validation_status'],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table('agent_experiences') as batch_op:
        batch_op.drop_index('ix_experiences_agent_status')
        batch_op.drop_column('last_used_at')
        batch_op.drop_column('use_count')
        batch_op.drop_column('keywords')
        batch_op.drop_column('validation_note')
