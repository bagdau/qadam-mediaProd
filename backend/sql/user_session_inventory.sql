SELECT u.email, count(s.id) FILTER (WHERE s.revoked_at IS NULL AND s.expires_at > now()) AS active_sessions
FROM users AS u LEFT JOIN sessions AS s ON s.user_id = u.id
GROUP BY u.id, u.email ORDER BY active_sessions DESC, u.email;
