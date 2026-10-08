SELECT current_database() AS database_name,
       pg_database_size(current_database()) AS size_bytes,
       now() - pg_postmaster_start_time() AS uptime,
       (SELECT count(*) FROM pg_stat_activity) AS connections;
