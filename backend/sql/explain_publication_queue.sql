EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)
SELECT id, status, updated_at FROM publications
WHERE status IN ('QUEUED', 'PROCESSING')
ORDER BY updated_at LIMIT 100;
