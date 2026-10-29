"""add payment_percent to accounts (revolving credit card payment)

Revision ID: 102
Revises: 101
Create Date: 2026-08-09

European (and many other) credit cards are revolving: the holder chooses to pay
only a portion of the statement each cycle and carries the rest. Store the
percentage of the outstanding balance the user plans to pay each cycle so the
app can show the real near-term cash impact (payment ≈ percent × owed) instead
of assuming the full balance is settled.

Additive and nullable: NULL means "pay in full" (the prior behavior). Only
meaningful for credit-card accounts. Value is 0–100 (percent).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "102"
down_revision: Union[str, None] = "101"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("accounts", sa.Column("payment_percent", sa.SmallInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column("accounts", "payment_percent")
