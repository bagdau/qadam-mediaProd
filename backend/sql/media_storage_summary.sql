SELECT status, count(*) AS assets, coalesce(sum(size_bytes), 0) AS bytes
FROM media_assets GROUP BY status ORDER BY status;
