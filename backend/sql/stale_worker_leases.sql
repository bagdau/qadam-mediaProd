SELECT id, status, lease_until, attempts FROM publications
WHERE status IN ('INITIATING', 'UPLOADING') AND lease_until < now()
ORDER BY lease_until;
