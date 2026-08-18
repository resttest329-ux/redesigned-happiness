"""customer active state

Revision ID: 3b7c2d5e8a90
Revises: 2f8a1c9b4d10
Create Date: 2026-06-24 10:12:00.000000

Adds the soft-delete flag and audit timestamp to ``customers`` so a customer
can be deactivated (hidden from the active directory and from new invoices)
without rewriting invoice history. Existing rows default to active.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "3b7c2d5e8a90"
down_revision: Union[str, Sequence[str], None] = "2f8a1c9b4d10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "customers",
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.add_column(
        "customers",
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.alter_column("customers", "is_active", server_default=None)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("customers", "updated_at")
    op.drop_column("customers", "is_active")
