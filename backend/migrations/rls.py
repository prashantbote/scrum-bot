"""Migration helpers for row-level security (plan §4.2)."""

from __future__ import annotations

from alembic import op

APP_ROLE = "scrum_app"


def enable_rls(table: str, *, append_only: bool = False) -> None:
    """Tenant isolation on ``table`` + grants for the application role.

    ``current_setting('app.org_id', true)`` returns NULL when unset, so a session without tenant
    context sees no rows instead of erroring.
    """
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {table} "
        f"USING (org_id = NULLIF(current_setting('app.org_id', true), '')::uuid) "
        f"WITH CHECK (org_id = NULLIF(current_setting('app.org_id', true), '')::uuid)"
    )
    privileges = "SELECT, INSERT" if append_only else "SELECT, INSERT, UPDATE, DELETE"
    op.execute(f"GRANT {privileges} ON {table} TO {APP_ROLE}")


def disable_rls(table: str) -> None:
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
