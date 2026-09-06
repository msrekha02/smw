-- A separate database for the test suite.
--
-- Several integrity tests truncate tables to get a clean slate, so pointing
-- them at the development database would silently delete whatever you were
-- looking at. `tests/conftest.py` defaults to this one.
SELECT 'CREATE DATABASE smw_test OWNER smw'
 WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'smw_test')\gexec
