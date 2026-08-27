\i /seed/schema.sql
\copy stations FROM '/seed/seed/stations.csv' WITH (FORMAT csv, HEADER true)
\copy riders FROM '/seed/seed/riders.csv' WITH (FORMAT csv, HEADER true)
\copy trips FROM '/seed/seed/trips.csv' WITH (FORMAT csv, HEADER true)

CREATE ROLE agent_reader LOGIN PASSWORD 'agent_reader' NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
GRANT CONNECT ON DATABASE probe TO agent_reader;
GRANT USAGE ON SCHEMA public TO agent_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO agent_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO agent_reader;
