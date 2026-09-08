SELECT COUNT(*) AS anomalous_trips FROM trips
WHERE started_at >= '2025-01-01' AND started_at < '2026-01-01'
  AND ended_at > started_at
  AND distance_km * 3600 / NULLIF(EXTRACT(EPOCH FROM ended_at - started_at), 0) > 80;
