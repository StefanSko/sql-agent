SELECT s.district,
       ROUND((PERCENTILE_CONT(0.9) WITHIN GROUP (
           ORDER BY EXTRACT(EPOCH FROM ended_at - started_at) / 60
       ))::numeric, 2) AS p90_minutes
FROM trips t JOIN stations s ON s.station_id = t.start_station_id
WHERE started_at >= '2025-07-01' AND started_at < '2025-08-01'
GROUP BY s.district ORDER BY s.district;
