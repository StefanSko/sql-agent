WITH ranked AS (
    SELECT rider_id, trip_id, distance_km,
           LEAD(trip_id) OVER w AS previous_trip_id,
           LEAD(distance_km) OVER w AS previous_distance,
           ROW_NUMBER() OVER w AS rn
    FROM trips
    WHERE started_at >= '2025-01-01' AND started_at < '2026-01-01'
    WINDOW w AS (PARTITION BY rider_id ORDER BY started_at DESC, trip_id DESC)
)
SELECT rider_id, trip_id AS latest_trip_id, previous_trip_id,
       ROUND((distance_km::numeric - previous_distance::numeric), 2) AS increase_km
FROM ranked WHERE rn = 1 AND previous_trip_id IS NOT NULL AND distance_km > previous_distance
ORDER BY increase_km DESC, rider_id LIMIT 5;
