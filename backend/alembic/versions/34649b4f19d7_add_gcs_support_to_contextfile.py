"""add_gcs_support_to_contextfile

Revision ID: 34649b4f19d7
Revises: b3021995a06b
Create Date: 2026-02-08 20:25:21.127225

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '34649b4f19d7'
down_revision: Union[str, Sequence[str], None] = 'b3021995a06b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
