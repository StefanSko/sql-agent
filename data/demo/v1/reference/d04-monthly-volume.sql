WITH months AS (
    SELECT generate_series(TIMESTAMP '2025-01-01', TIMESTAMP '2025-12-01', INTERVAL '1 month') AS month
)
SELECT TO_CHAR(m.month, 'YYYY-MM') AS month, COUNT(t.trip_id) AS trip_count
FROM months m LEFT JOIN trips t ON t.started_at >= m.month AND t.started_at < m.month + INTERVAL '1 month'
GROUP BY m.month ORDER BY m.month;
