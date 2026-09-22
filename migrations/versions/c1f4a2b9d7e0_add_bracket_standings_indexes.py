"""Add composite indexes for bracket standings queries

Revision ID: c1f4a2b9d7e0
Revises: 48d8250d19bd
Create Date: 2026-09-22 00:00:00.000000

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "c1f4a2b9d7e0"
down_revision = "48d8250d19bd"
branch_labels = None
depends_on = None


def upgrade():
    # Covers the standings lookup filtered by bracket plus the public
    # banned/hidden visibility predicates and the join/id ordering.
    op.create_index(
        "ix_teams_bracket_standings",
        "teams",
        ["bracket_id", "banned", "hidden", "id"],
        unique=False,
    )
    op.create_index(
        "ix_users_bracket_standings",
        "users",
        ["bracket_id", "banned", "hidden", "id"],
        unique=False,
    )


def downgrade():
    op.drop_index("ix_users_bracket_standings", table_name="users")
    op.drop_index("ix_teams_bracket_standings", table_name="teams")
