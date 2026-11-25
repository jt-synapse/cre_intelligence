-- Local development credential, reachable only through a loopback port on the host.
CREATE ROLE cre_runtime LOGIN PASSWORD 'local-runtime' NOSUPERUSER NOBYPASSRLS;
CREATE ROLE cre_worker LOGIN PASSWORD 'local-worker' NOSUPERUSER NOBYPASSRLS;
