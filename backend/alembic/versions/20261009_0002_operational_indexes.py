"""Add partial indexes for operational background queries."""

from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_users_active_locked_until", "users", ["locked_until"], postgresql_where=sa.text("is_active = true"))
    op.create_index("ix_sessions_active_expires_at", "sessions", ["expires_at"], postgresql_where=sa.text("revoked_at IS NULL"))
    op.create_index("ix_connected_accounts_refresh_due", "connected_accounts", ["access_expires_at"], postgresql_where=sa.text("status = 'active' AND refresh_token_enc IS NOT NULL"))
    op.create_index("ix_oauth_states_unconsumed_expiry", "oauth_states", ["expires_at"], postgresql_where=sa.text("consumed_at IS NULL"))
    op.create_index("ix_publications_poll_due", "publications", ["next_poll_at"], postgresql_where=sa.text("status = 'PROCESSING'"))


def downgrade() -> None:
    op.drop_index("ix_publications_poll_due", table_name="publications")
    op.drop_index("ix_oauth_states_unconsumed_expiry", table_name="oauth_states")
    op.drop_index("ix_connected_accounts_refresh_due", table_name="connected_accounts")
    op.drop_index("ix_sessions_active_expires_at", table_name="sessions")
    op.drop_index("ix_users_active_locked_until", table_name="users")
