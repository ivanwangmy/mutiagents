"""add execution_logic to agent_skills

Revision ID: b7f1c2d3e4a5
Revises: 03dc691b90bc
Create Date: 2026-11-23 15:10:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'b7f1c2d3e4a5'
down_revision = '03dc691b90bc'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('agent_skills') as batch_op:
        batch_op.add_column(
            sa.Column(
                'execution_logic',
                sa.String(length=255),
                nullable=False,
                server_default='',
            )
        )


def downgrade() -> None:
    with op.batch_alter_table('agent_skills') as batch_op:
        batch_op.drop_column('execution_logic')
