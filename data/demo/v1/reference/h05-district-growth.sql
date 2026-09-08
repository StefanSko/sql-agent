WITH counts AS (
    SELECT s.district,
           COUNT(*) FILTER (WHERE started_at < '2025-12-01') AS november_trips,
           COUNT(*) FILTER (WHERE started_at >= '2025-12-01') AS december_trips
    FROM trips t JOIN stations s ON s.station_id = t.start_station_id
    WHERE started_at >= '2025-11-01' AND started_at < '2026-01-01'
    GROUP BY s.district
)
SELECT district, november_trips, december_trips,
       ROUND(100.0 * (december_trips - november_trips) / november_trips, 2) AS growth_pct
FROM counts WHERE november_trips > 0
ORDER BY 1.0 * (december_trips - november_trips) / november_trips DESC, district LIMIT 1;
