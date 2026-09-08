-- Synthetic bike-share demo v1. Pure arithmetic/MD5: no random(), wall clock, or external data.
-- Apply this directory's schema.sql first, to an empty database. All timestamps are naive local time.
INSERT INTO stations
SELECT id, 'Station ' || lpad(id::text, 3, '0'),
       (ARRAY['Central', 'North', 'East', 'South', 'West'])[(id - 1) % 5 + 1],
       12 + (id * 7 % 29), 52.45 + (id % 10) * 0.012, 13.30 + (id / 10) * 0.016
FROM generate_series(1, 100) AS id;

INSERT INTO riders
SELECT id, DATE '2025-01-01' + (id * 37 % 330),
       CASE WHEN id % 10 < 7 THEN 'member' ELSE 'casual' END,
       (ARRAY['Central', 'North', 'East', 'South', 'West'])[(id * 3) % 5 + 1]
FROM generate_series(1, 2000) AS id;

-- 100 inactive riders (1901..2000), two unused stations (99,100).
-- Some rider cohorts stop after 30/90 days; others remain active all year.
-- Prefer summer dates, weekday commute hours, and residential-to-central morning routes.
WITH hashes AS MATERIALIZED (
    SELECT id, md5('demo-v1:a:' || id) AS a, md5('demo-v1:b:' || id) AS b
    FROM generate_series(1, 100000) AS id
), entropy AS MATERIALIZED (
    SELECT id,
           ('x' || substr(a, 1, 8))::bit(32)::bigint AS r1,
           ('x' || substr(a, 9, 8))::bit(32)::bigint AS r2,
           ('x' || substr(a, 17, 8))::bit(32)::bigint AS r3,
           ('x' || substr(a, 25, 8))::bit(32)::bigint AS r4,
           ('x' || substr(b, 1, 8))::bit(32)::bigint AS r5,
           ('x' || substr(b, 9, 8))::bit(32)::bigint AS r6,
           ('x' || substr(b, 17, 8))::bit(32)::bigint AS r7,
           ('x' || substr(b, 25, 8))::bit(32)::bigint AS r8
    FROM hashes
), assigned AS (
    SELECT *, (1 + r1 % 1900)::integer AS rider_id FROM entropy
), lifetimes AS (
    SELECT a.*, r.signup_date,
           LEAST(DATE '2025-12-31' - r.signup_date,
                 CASE a.rider_id % 5 WHEN 0 THEN 30 WHEN 1 THEN 90 ELSE 364 END) + 1 AS span
    FROM assigned a JOIN riders r USING (rider_id)
), candidates AS (
    SELECT *, signup_date + (r2 % span)::integer AS day1,
              signup_date + (r3 % span)::integer AS day2
    FROM lifetimes
), dates AS (
    SELECT *, CASE WHEN EXTRACT(MONTH FROM day1) BETWEEN 6 AND 8
                   THEN day1 ELSE day2 END AS day
    FROM candidates
), hours AS (
    SELECT *, CASE WHEN EXTRACT(ISODOW FROM day) <= 5 AND r4 % 10 < 6
                   THEN (ARRAY[7, 8, 8, 9, 16, 17, 17, 18])[(r5 % 8 + 1)::integer]
                   ELSE (9 + r5 % 12)::integer END AS hour,
           CASE WHEN id % 10000 = 0 THEN 60.0
                WHEN id % 997 = 0 THEN 0.0
                ELSE (5 + r6 % 115)::numeric / 10 END AS distance
    FROM dates
), journeys AS (
    SELECT *, day + make_interval(hours => hour, mins => (r8 % 60)::integer) AS started,
           CASE WHEN EXTRACT(ISODOW FROM day) <= 5 AND hour BETWEEN 7 AND 9 AND r4 % 10 < 8
                THEN 2 + r6 % 4 + 5 * (r7 % 19)
                WHEN EXTRACT(ISODOW FROM day) <= 5 AND hour BETWEEN 16 AND 18 AND r4 % 10 < 8
                THEN 1 + 5 * (r7 % 20)
                ELSE 1 + r6 % 98 END AS origin,
           CASE WHEN EXTRACT(ISODOW FROM day) <= 5 AND hour BETWEEN 7 AND 9 AND r4 % 10 < 8
                THEN 1 + 5 * (r8 % 20)
                WHEN EXTRACT(ISODOW FROM day) <= 5 AND hour BETWEEN 16 AND 18 AND r4 % 10 < 8
                THEN 2 + r8 % 4 + 5 * (r6 % 19)
                ELSE 1 + r8 % 98 END AS destination
    FROM hours
)
INSERT INTO trips
SELECT id, rider_id, origin::integer, destination::integer, started,
       started + make_interval(mins => CASE WHEN id % 10000 = 0 THEN 1
                              ELSE 8 + ceil(distance * 3)::integer + (r7 % 15)::integer END),
       distance::double precision
FROM journeys ORDER BY id;

CREATE INDEX trips_rider_started_idx ON trips (rider_id, started_at, trip_id);
CREATE INDEX trips_started_idx ON trips (started_at);
CREATE INDEX trips_origin_idx ON trips (start_station_id);
CREATE INDEX trips_destination_idx ON trips (end_station_id);
ANALYZE;
