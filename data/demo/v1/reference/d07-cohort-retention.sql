WITH retained AS (
    SELECT r.rider_id, DATE_TRUNC('month', r.signup_date) AS cohort,
           EXISTS (
               SELECT 1 FROM trips t WHERE t.rider_id = r.rider_id
                 AND t.started_at >= DATE_TRUNC('month', r.signup_date) + INTERVAL '1 month'
                 AND t.started_at < DATE_TRUNC('month', r.signup_date) + INTERVAL '2 months'
           ) AS retained
    FROM riders r WHERE r.signup_date >= '2025-01-01' AND r.signup_date < '2025-12-01'
)
SELECT TO_CHAR(cohort, 'YYYY-MM') AS cohort_month, COUNT(*) AS cohort_size,
       COUNT(*) FILTER (WHERE retained) AS retained_riders,
       ROUND(100.0 * COUNT(*) FILTER (WHERE retained) / COUNT(*), 2) AS retention_pct
FROM retained GROUP BY cohort ORDER BY cohort;
