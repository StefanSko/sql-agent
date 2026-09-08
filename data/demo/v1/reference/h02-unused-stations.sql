SELECT s.station_id, s.name FROM stations s
WHERE NOT EXISTS (SELECT 1 FROM trips t
                  WHERE (t.start_station_id = s.station_id OR t.end_station_id = s.station_id)
                    AND started_at >= '2025-01-01' AND started_at < '2026-01-01')
ORDER BY s.station_id;
