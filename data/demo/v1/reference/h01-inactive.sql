SELECT COUNT(*) AS inactive_riders FROM riders r
WHERE NOT EXISTS (SELECT 1 FROM trips t WHERE t.rider_id = r.rider_id
                  AND started_at >= '2025-01-01' AND started_at < '2026-01-01');
