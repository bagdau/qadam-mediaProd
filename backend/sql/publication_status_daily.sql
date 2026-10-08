SELECT date_trunc('day', created_at) AS day, status, count(*) AS publications
FROM publications WHERE created_at >= now() - interval '30 days'
GROUP BY 1, 2 ORDER BY 1 DESC, 2;
