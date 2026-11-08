"""add password_hash to users table

Revision ID: 4bc2ea3562b2
Revises: 1683fbe0a5ad
Create Date: 2026-11-08 18:56:46.548011

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "4bc2ea3562b2"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = (
    "1683fbe0a5ad"  # pragma: allowlist secret
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "users",
        sa.Column("password_hash", sa.String(length=255), nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("users", "password_hash")
