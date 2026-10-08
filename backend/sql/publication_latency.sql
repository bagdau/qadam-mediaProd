SELECT mode,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY finished_at - created_at) AS p50,
       percentile_cont(0.95) WITHIN GROUP (ORDER BY finished_at - created_at) AS p95
FROM publications
WHERE finished_at IS NOT NULL AND created_at >= now() - interval '30 days'
GROUP BY mode;
