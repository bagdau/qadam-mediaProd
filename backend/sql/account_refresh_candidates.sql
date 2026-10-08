SELECT id, user_id, access_expires_at FROM connected_accounts
WHERE status = 'active' AND refresh_token_enc IS NOT NULL
  AND access_expires_at < now() + interval '2 hours'
ORDER BY access_expires_at FOR UPDATE SKIP LOCKED;
