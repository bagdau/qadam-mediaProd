SELECT 'users' AS relation, count(*) AS rows FROM users
UNION ALL SELECT 'connected_accounts', count(*) FROM connected_accounts
UNION ALL SELECT 'media_assets', count(*) FROM media_assets
UNION ALL SELECT 'publications', count(*) FROM publications
UNION ALL SELECT 'audit_logs', count(*) FROM audit_logs
ORDER BY relation;
