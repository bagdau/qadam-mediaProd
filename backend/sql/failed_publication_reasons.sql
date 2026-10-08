SELECT coalesce(fail_reason, 'unknown') AS reason, count(*) AS failures
FROM publications
WHERE status IN ('FAILED', 'NEEDS_REVIEW') AND created_at >= now() - interval '30 days'
GROUP BY 1 ORDER BY failures DESC, reason;
