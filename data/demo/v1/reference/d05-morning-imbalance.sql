WITH eligible AS (
    SELECT start_station_id, end_station_id FROM trips
    WHERE started_at >= '2025-01-01' AND started_at < '2026-01-01'
      AND EXTRACT(ISODOW FROM started_at) <= 5
      AND EXTRACT(HOUR FROM started_at) >= 7 AND EXTRACT(HOUR FROM started_at) < 10
), departures AS (
    SELECT start_station_id AS station_id, COUNT(*) AS n FROM eligible GROUP BY start_station_id
), arrivals AS (
    SELECT end_station_id AS station_id, COUNT(*) AS n FROM eligible GROUP BY end_station_id
)
SELECT s.station_id, COALESCE(d.n, 0) AS departures, COALESCE(a.n, 0) AS arrivals,
       COALESCE(d.n, 0) - COALESCE(a.n, 0) AS net_departures
FROM stations s LEFT JOIN departures d USING (station_id) LEFT JOIN arrivals a USING (station_id)
ORDER BY net_departures DESC, s.station_id LIMIT 5;
