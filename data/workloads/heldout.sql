CREATE TABLE depots (
    depot_id integer PRIMARY KEY,
    label text NOT NULL
);

CREATE TABLE artifacts (
    artifact_id integer PRIMARY KEY,
    depot_id integer NOT NULL REFERENCES depots(depot_id),
    quantity integer NOT NULL
);

INSERT INTO depots (depot_id, label) VALUES (1, 'Alpha'), (2, 'Beta');
INSERT INTO artifacts (artifact_id, depot_id, quantity) VALUES
    (1, 1, 5),
    (2, 1, 7),
    (3, 2, 11);
