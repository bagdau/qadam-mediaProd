SELECT user_id, sha256, count(*) AS copies, sum(size_bytes) AS bytes
FROM media_assets WHERE status = 'ready'
GROUP BY user_id, sha256 HAVING count(*) > 1 ORDER BY bytes DESC;
