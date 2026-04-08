# Backend SQL migrations

This folder contains ordered SQL migrations executed by the backend at startup.

- Migration files are run lexicographically.
- Applied migrations are tracked in `schema_migrations`.
- Files should use a sortable prefix, e.g. `001_description.sql`.
