"""add items table

Revision ID: 8a3f21c4d901
Revises: 155227c01edc
Create Date: 2026-06-24 09:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "8a3f21c4d901"
down_revision: Union[str, Sequence[str], None] = "155227c01edc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "items",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("business_id", sa.String(), nullable=False),
        sa.Column("sku", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("hsn_code", sa.String(), nullable=True),
        sa.Column("hsn_category", sa.String(), nullable=True),
        sa.Column("isic_code", sa.String(), nullable=True),
        sa.Column("isic_category", sa.String(), nullable=True),
        sa.Column("unit_price", sa.Float(), nullable=True),
        sa.Column("price_unit", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("business_id", "sku", name="uq_items_business_sku"),
        sa.CheckConstraint(
            "(hsn_code IS NOT NULL AND isic_code IS NULL) OR "
            "(hsn_code IS NULL AND isic_code IS NOT NULL)",
            name="ck_items_exactly_one_code",
        ),
    )
    op.create_index(
        op.f("ix_items_business_id"), "items", ["business_id"], unique=False
    )
    op.create_index(op.f("ix_items_sku"), "items", ["sku"], unique=False)
    op.create_index(op.f("ix_items_name"), "items", ["name"], unique=False)
    op.create_index(
        op.f("ix_items_hsn_code"), "items", ["hsn_code"], unique=False
    )
    op.create_index(
        op.f("ix_items_isic_code"), "items", ["isic_code"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_items_isic_code"), table_name="items")
    op.drop_index(op.f("ix_items_hsn_code"), table_name="items")
    op.drop_index(op.f("ix_items_name"), table_name="items")
    op.drop_index(op.f("ix_items_sku"), table_name="items")
    op.drop_index(op.f("ix_items_business_id"), table_name="items")
    op.drop_table("items")
