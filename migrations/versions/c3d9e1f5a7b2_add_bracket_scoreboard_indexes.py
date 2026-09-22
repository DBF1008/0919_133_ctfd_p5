"""Add composite indexes for scoreboard bracket filtering

Revision ID: c3d9e1f5a7b2
Revises: 48d8250d19bd
Create Date: 2026-09-22 00:00:00.000000

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "c3d9e1f5a7b2"
down_revision = "48d8250d19bd"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        "ix_users_bracket_id_banned_hidden",
        "users",
        ["bracket_id", "banned", "hidden"],
    )
    op.create_index(
        "ix_teams_bracket_id_banned_hidden",
        "teams",
        ["bracket_id", "banned", "hidden"],
    )


def downgrade():
    op.drop_index("ix_teams_bracket_id_banned_hidden", table_name="teams")
    op.drop_index("ix_users_bracket_id_banned_hidden", table_name="users")
