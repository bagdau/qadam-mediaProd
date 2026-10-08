DELETE FROM oauth_states
WHERE expires_at < now() - interval '24 hours'
RETURNING id, user_id, expires_at;
