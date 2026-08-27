CREATE TABLE stations (
    station_id integer PRIMARY KEY,
    name text NOT NULL,
    district text NOT NULL,
    capacity integer NOT NULL,
    lat double precision NOT NULL,
    lon double precision NOT NULL
);

CREATE TABLE riders (
    rider_id integer PRIMARY KEY,
    signup_date date NOT NULL,
    plan text NOT NULL CHECK (plan IN ('member', 'casual')),
    home_district text NOT NULL
);

CREATE TABLE trips (
    trip_id integer PRIMARY KEY,
    rider_id integer NOT NULL REFERENCES riders(rider_id),
    start_station_id integer NOT NULL REFERENCES stations(station_id),
    end_station_id integer NOT NULL REFERENCES stations(station_id),
    started_at timestamp NOT NULL,
    ended_at timestamp NOT NULL,
    distance_km double precision NOT NULL
);
