WITH dates AS (
    SELECT generate_series(TIMESTAMP '2025-01-01', TIMESTAMP '2025-12-31', INTERVAL '1 day')::date AS day
), daily AS (
    SELECT started_at::date AS day, COUNT(*) AS n FROM trips
    WHERE started_at >= '2025-01-01' AND started_at < '2026-01-01' GROUP BY started_at::date
), rolling AS (
    SELECT d.day, SUM(COALESCE(n, 0)) OVER (ORDER BY d.day ROWS BETWEEN 6 PRECEDING AND CURRENT ROW) AS n
    FROM dates d LEFT JOIN daily USING (day)
)
SELECT TO_CHAR(day, 'YYYY-MM-DD') AS window_end, n AS trip_count FROM rolling
ORDER BY n DESC, day LIMIT 1;
