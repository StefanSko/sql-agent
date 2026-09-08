SELECT r.plan,
       ROUND(AVG(EXTRACT(EPOCH FROM ended_at - started_at) / 60), 2) AS avg_minutes,
       ROUND(AVG(distance_km::numeric), 2) AS avg_km
FROM trips t JOIN riders r USING (rider_id)
WHERE started_at >= '2025-01-01' AND started_at < '2026-01-01'
GROUP BY r.plan ORDER BY r.plan;
