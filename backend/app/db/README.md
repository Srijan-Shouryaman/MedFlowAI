# db (placeholder)

Reserved for the database layer: SQLAlchemy models, session management, and
Alembic migrations.

Nothing lives here yet. `app/registry.py` holds document metadata in process
memory as an explicit stand-in, and names the three methods a real repository
will need to provide.
