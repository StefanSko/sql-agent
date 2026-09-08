WITH days AS (
    SELECT DISTINCT rider_id, started_at::date AS day FROM trips
    WHERE started_at >= '2025-01-01' AND started_at < '2026-01-01'
), islands AS (
    SELECT rider_id, day - ROW_NUMBER() OVER (PARTITION BY rider_id ORDER BY day)::integer AS island
    FROM days
), streaks AS (
    SELECT rider_id, COUNT(*) AS streak FROM islands GROUP BY rider_id, island
)
SELECT rider_id, MAX(streak) AS longest_streak FROM streaks GROUP BY rider_id
ORDER BY longest_streak DESC, rider_id LIMIT 5;
