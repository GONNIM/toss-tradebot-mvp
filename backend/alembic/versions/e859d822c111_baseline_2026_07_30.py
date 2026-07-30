"""baseline · 2026-07-30 · Alembic 활성화 시점 스키마 stamp

기존 create_all() 방식으로 만들어진 스키마를 baseline 으로 mark.
실 스키마 변경 없음 · `alembic stamp head` 로 이 revision 을 현재로 인식시킴.

참조: docs/plans/toss-tradebot-tobe/stage2-architecture.md §1.2 Alembic 활성화

Revision ID: e859d822c111
Revises:
Create Date: 2026-07-30 09:48:09.864282
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e859d822c111'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
