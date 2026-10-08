DELETE FROM sessions
WHERE revoked_at < now() - interval '30 days'
RETURNING id, user_id, revoked_at;
