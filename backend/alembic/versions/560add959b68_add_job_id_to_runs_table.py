"""add job_id to runs table

Revision ID: 560add959b68
Revises: 4bc2ea3562b2
Create Date: 2026-11-09 16:06:07.973715

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "560add959b68"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = (
    "4bc2ea3562b2"  # pragma: allowlist secret
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("runs", sa.Column("job_id", sa.String(length=128), nullable=True))
    op.create_index("ix_runs_job_id", "runs", ["job_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_runs_job_id", table_name="runs")
    op.drop_column("runs", "job_id")
