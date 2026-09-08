SELECT s.station_id, s.name, COUNT(*) AS departures
FROM trips t JOIN stations s ON t.start_station_id = s.station_id
WHERE started_at >= '2025-01-01' AND started_at < '2026-01-01'
GROUP BY s.station_id, s.name
ORDER BY departures DESC, s.station_id LIMIT 5;
