SELECT r.plan, COUNT(*) AS trip_count,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) AS trip_pct
FROM trips t JOIN riders r USING (rider_id)
WHERE started_at >= '2025-01-01' AND started_at < '2026-01-01'
GROUP BY r.plan ORDER BY r.plan;
