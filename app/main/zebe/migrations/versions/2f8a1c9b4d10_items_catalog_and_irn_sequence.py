"""items catalog and irn sequence

Revision ID: 2f8a1c9b4d10
Revises: 155227c01edc
Create Date: 2026-06-24 09:12:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "2f8a1c9b4d10"
down_revision: Union[str, Sequence[str], None] = "155227c01edc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "items",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("business_id", sa.String(), nullable=False),
        sa.Column("sku", sa.String(), nullable=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("hsn_code", sa.String(), nullable=True),
        sa.Column("hsn_category", sa.String(), nullable=True),
        sa.Column("isic_code", sa.String(), nullable=True),
        sa.Column("isic_category", sa.String(), nullable=True),
        sa.Column("unit_price", sa.Float(), nullable=False),
        sa.Column(
            "price_unit", sa.String(), nullable=False, server_default="C62"
        ),
        sa.Column(
            "base_quantity", sa.Float(), nullable=False, server_default="1"
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("business_id", "sku", name="uq_items_business_sku"),
    )
    op.create_index(
        op.f("ix_items_business_id"), "items", ["business_id"], unique=False
    )
    op.create_index(op.f("ix_items_sku"), "items", ["sku"], unique=False)

    op.create_table(
        "irn_sequence",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("business_id", sa.String(), nullable=False),
        sa.Column("date_segment", sa.String(), nullable=False),
        sa.Column(
            "last_sequence", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "business_id",
            "date_segment",
            name="uq_irn_sequence_business_date",
        ),
    )
    op.create_index(
        op.f("ix_irn_sequence_business_id"),
        "irn_sequence",
        ["business_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        op.f("ix_irn_sequence_business_id"), table_name="irn_sequence"
    )
    op.drop_table("irn_sequence")
    op.drop_index(op.f("ix_items_sku"), table_name="items")
    op.drop_index(op.f("ix_items_business_id"), table_name="items")
    op.drop_table("items")
