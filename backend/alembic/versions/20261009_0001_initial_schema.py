"""initial schema

Revision ID: 0001
Revises: 
Create Date: 2026-10-09 00:42:24.700894
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:

    op.create_table('users',
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('password_hash', sa.Text(), nullable=False),
    sa.Column('display_name', sa.String(length=120), nullable=False),
    sa.Column('role', sa.String(length=16), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('failed_login_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("role IN ('admin', 'member')", name=op.f('ck_users_role_valid')),
    sa.CheckConstraint('email = lower(email)', name=op.f('ck_users_email_lowercase')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_users')),
    sa.UniqueConstraint('email', name=op.f('uq_users_email'))
    )
    op.create_table('audit_logs',
    sa.Column('user_id', sa.UUID(), nullable=True),
    sa.Column('action', sa.String(length=64), nullable=False),
    sa.Column('entity_type', sa.String(length=32), nullable=True),
    sa.Column('entity_id', sa.String(length=64), nullable=True),
    sa.Column('ip_address', sa.String(length=64), nullable=True),
    sa.Column('user_agent', sa.String(length=512), nullable=True),
    sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_audit_logs_user_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_logs'))
    )
    op.create_index('ix_audit_logs_action_created_at', 'audit_logs', ['action', 'created_at'], unique=False)
    op.create_index('ix_audit_logs_user_id_created_at', 'audit_logs', ['user_id', 'created_at'], unique=False)
    op.create_table('connected_accounts',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('provider', sa.String(length=32), nullable=False),
    sa.Column('provider_account_id', sa.String(length=128), nullable=False),
    sa.Column('username', sa.String(length=128), nullable=True),
    sa.Column('display_name', sa.String(length=256), nullable=True),
    sa.Column('avatar_url', sa.Text(), nullable=True),
    sa.Column('scopes', postgresql.ARRAY(sa.String(length=64)), nullable=False),
    sa.Column('access_token_enc', sa.Text(), nullable=True),
    sa.Column('refresh_token_enc', sa.Text(), nullable=True),
    sa.Column('access_expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('refresh_expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('connected_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_refreshed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('disconnected_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("provider IN ('tiktok')", name=op.f('ck_connected_accounts_provider_valid')),
    sa.CheckConstraint("status IN ('active', 'needs_reauth', 'revoked')", name=op.f('ck_connected_accounts_status_valid')),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_connected_accounts_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_connected_accounts')),
    sa.UniqueConstraint('user_id', 'provider', 'provider_account_id', name='uq_connected_accounts_identity')
    )
    op.create_index('ix_connected_accounts_access_expires_at', 'connected_accounts', ['access_expires_at'], unique=False)
    op.create_index('ix_connected_accounts_user_id_status', 'connected_accounts', ['user_id', 'status'], unique=False)
    op.create_table('media_assets',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('original_filename', sa.String(length=255), nullable=False),
    sa.Column('storage_name', sa.String(length=64), nullable=False),
    sa.Column('content_type', sa.String(length=64), nullable=False),
    sa.Column('size_bytes', sa.BigInteger(), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('duration_seconds', sa.Float(), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('ready', 'deleted')", name=op.f('ck_media_assets_status_valid')),
    sa.CheckConstraint('size_bytes > 0', name=op.f('ck_media_assets_size_positive')),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_media_assets_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_media_assets')),
    sa.UniqueConstraint('storage_name', name=op.f('uq_media_assets_storage_name'))
    )
    op.create_index('ix_media_assets_status_created_at', 'media_assets', ['status', 'created_at'], unique=False)
    op.create_index('ix_media_assets_user_id_created_at', 'media_assets', ['user_id', 'created_at'], unique=False)
    op.create_table('oauth_states',
    sa.Column('state_hash', sa.String(length=64), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('provider', sa.String(length=32), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('consumed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_oauth_states_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_oauth_states')),
    sa.UniqueConstraint('state_hash', name=op.f('uq_oauth_states_state_hash'))
    )
    op.create_index('ix_oauth_states_expires_at', 'oauth_states', ['expires_at'], unique=False)
    op.create_index('ix_oauth_states_user_id', 'oauth_states', ['user_id'], unique=False)
    op.create_table('sessions',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('ip_address', sa.String(length=64), nullable=True),
    sa.Column('user_agent', sa.String(length=512), nullable=True),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_sessions_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_sessions')),
    sa.UniqueConstraint('token_hash', name=op.f('uq_sessions_token_hash'))
    )
    op.create_index('ix_sessions_user_id_expires_at', 'sessions', ['user_id', 'expires_at'], unique=False)
    op.create_table('publications',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('account_id', sa.UUID(), nullable=False),
    sa.Column('media_id', sa.UUID(), nullable=False),
    sa.Column('idempotency_key', sa.String(length=128), nullable=False),
    sa.Column('mode', sa.String(length=24), nullable=False),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('title', sa.Text(), nullable=False),
    sa.Column('privacy_level', sa.String(length=32), nullable=False),
    sa.Column('disable_comment', sa.Boolean(), nullable=False),
    sa.Column('disable_duet', sa.Boolean(), nullable=False),
    sa.Column('disable_stitch', sa.Boolean(), nullable=False),
    sa.Column('brand_content_toggle', sa.Boolean(), nullable=False),
    sa.Column('brand_organic_toggle', sa.Boolean(), nullable=False),
    sa.Column('is_aigc', sa.Boolean(), nullable=False),
    sa.Column('cover_timestamp_ms', sa.Integer(), nullable=False),
    sa.Column('tiktok_publish_id', sa.String(length=128), nullable=True),
    sa.Column('upload_url_enc', sa.Text(), nullable=True),
    sa.Column('chunk_size', sa.BigInteger(), nullable=True),
    sa.Column('total_chunks', sa.Integer(), nullable=True),
    sa.Column('uploaded_bytes', sa.BigInteger(), server_default='0', nullable=False),
    sa.Column('tiktok_post_ids', postgresql.ARRAY(sa.String(length=64)), nullable=True),
    sa.Column('attempts', sa.Integer(), server_default='0', nullable=False),
    sa.Column('poll_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('next_poll_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('lease_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('fail_reason', sa.String(length=64), nullable=True),
    sa.Column('fail_message', sa.Text(), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("mode IN ('DIRECT_POST', 'UPLOAD_TO_INBOX')", name=op.f('ck_publications_mode_valid')),
    sa.CheckConstraint("privacy_level IN ('PUBLIC_TO_EVERYONE', 'MUTUAL_FOLLOW_FRIENDS', 'FOLLOWER_OF_CREATOR', 'SELF_ONLY')", name=op.f('ck_publications_privacy_valid')),
    sa.CheckConstraint("status IN ('QUEUED', 'INITIATING', 'UPLOADING', 'PROCESSING', 'PUBLISHED', 'INBOX_DELIVERED', 'FAILED', 'NEEDS_REVIEW', 'CANCELLED')", name=op.f('ck_publications_status_valid')),
    sa.CheckConstraint('char_length(title) <= 2200', name=op.f('ck_publications_title_length')),
    sa.ForeignKeyConstraint(['account_id'], ['connected_accounts.id'], name=op.f('fk_publications_account_id_connected_accounts'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['media_id'], ['media_assets.id'], name=op.f('fk_publications_media_id_media_assets'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_publications_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_publications')),
    sa.UniqueConstraint('user_id', 'idempotency_key', name='uq_publications_idempotency')
    )
    op.create_index('ix_publications_account_id_status', 'publications', ['account_id', 'status'], unique=False)
    op.create_index('ix_publications_media_id', 'publications', ['media_id'], unique=False)
    op.create_index('ix_publications_status_updated_at', 'publications', ['status', 'updated_at'], unique=False)
    op.create_index('ix_publications_user_id_created_at', 'publications', ['user_id', 'created_at'], unique=False)
    op.create_index('uq_publications_tiktok_publish_id', 'publications', ['tiktok_publish_id'], unique=True, postgresql_where='tiktok_publish_id IS NOT NULL')
    op.create_table('publication_events',
    sa.Column('publication_id', sa.UUID(), nullable=False),
    sa.Column('type', sa.String(length=32), nullable=False),
    sa.Column('from_status', sa.String(length=24), nullable=True),
    sa.Column('to_status', sa.String(length=24), nullable=True),
    sa.Column('message', sa.Text(), nullable=False),
    sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['publication_id'], ['publications.id'], name=op.f('fk_publication_events_publication_id_publications'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_publication_events'))
    )
    op.create_index('ix_publication_events_publication_id_created_at', 'publication_events', ['publication_id', 'created_at'], unique=False)



def downgrade() -> None:

    op.drop_index('ix_publication_events_publication_id_created_at', table_name='publication_events')
    op.drop_table('publication_events')
    op.drop_index('uq_publications_tiktok_publish_id', table_name='publications', postgresql_where='tiktok_publish_id IS NOT NULL')
    op.drop_index('ix_publications_user_id_created_at', table_name='publications')
    op.drop_index('ix_publications_status_updated_at', table_name='publications')
    op.drop_index('ix_publications_media_id', table_name='publications')
    op.drop_index('ix_publications_account_id_status', table_name='publications')
    op.drop_table('publications')
    op.drop_index('ix_sessions_user_id_expires_at', table_name='sessions')
    op.drop_table('sessions')
    op.drop_index('ix_oauth_states_user_id', table_name='oauth_states')
    op.drop_index('ix_oauth_states_expires_at', table_name='oauth_states')
    op.drop_table('oauth_states')
    op.drop_index('ix_media_assets_user_id_created_at', table_name='media_assets')
    op.drop_index('ix_media_assets_status_created_at', table_name='media_assets')
    op.drop_table('media_assets')
    op.drop_index('ix_connected_accounts_user_id_status', table_name='connected_accounts')
    op.drop_index('ix_connected_accounts_access_expires_at', table_name='connected_accounts')
    op.drop_table('connected_accounts')
    op.drop_index('ix_audit_logs_user_id_created_at', table_name='audit_logs')
    op.drop_index('ix_audit_logs_action_created_at', table_name='audit_logs')
    op.drop_table('audit_logs')
    op.drop_table('users')

