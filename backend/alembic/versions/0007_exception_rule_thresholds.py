"""Exception rule thresholds table (MEADOWOPS-DOMAIN-004).

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-02
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0007'
down_revision: Union[str, None] = '0006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'exception_rule_threshold',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('threshold_value', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('unit', sa.String(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint('threshold_value >= 0', name='ck_exception_rule_threshold_non_negative'),
        sa.PrimaryKeyConstraint('id'),
        schema='live',
    )


def downgrade() -> None:
    op.drop_table('exception_rule_threshold', schema='live')
