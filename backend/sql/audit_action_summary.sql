SELECT action, count(*) AS occurrences, max(created_at) AS last_seen_at
FROM audit_logs WHERE created_at >= now() - interval '7 days'
GROUP BY action ORDER BY occurrences DESC, action;
