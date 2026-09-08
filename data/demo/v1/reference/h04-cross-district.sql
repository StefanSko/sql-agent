SELECT ROUND(100.0 * COUNT(*) FILTER (WHERE s.district <> e.district) / COUNT(*), 2) AS cross_district_pct
FROM trips t JOIN stations s ON s.station_id = t.start_station_id
JOIN stations e ON e.station_id = t.end_station_id
WHERE started_at >= '2025-01-01' AND started_at < '2026-01-01';
