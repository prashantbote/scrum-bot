"""Row-level security (plan §4.2): cross-tenant isolation enforced by PostgreSQL itself."""

import uuid

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from scrum_core.db import owner_session, session_for, set_org_context, system_session
from scrum_core.models import TENANT_TABLES, Organization, Team, User
from scrum_core.models.base import Role

pytestmark = pytest.mark.db


async def test_every_tenant_table_has_forced_rls_policy(migrated_db):
    async with owner_session() as db:
        rows = (
            await db.execute(
                text("""
            SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity,
                   EXISTS (SELECT 1 FROM pg_policies p WHERE p.tablename = c.relname AND p.policyname = 'tenant_isolation')
            FROM pg_class c JOIN information_schema.columns col ON col.table_name = c.relname
            WHERE col.column_name = 'org_id' AND c.relkind = 'r' AND col.table_schema = 'public'
        """)
            )
        ).all()
    tables = {r[0] for r in rows}
    assert set(TENANT_TABLES) <= tables
    assert [r[0] for r in rows if not (r[1] and r[2] and r[3])] == []


async def test_app_role_cannot_bypass_rls_or_rewrite_audit(migrated_db):
    async with system_session() as db:
        role = (
            await db.execute(text("SELECT rolbypassrls, rolsuper FROM pg_roles WHERE rolname = current_user"))
        ).one()
        assert role == (False, False)
        assert (await db.execute(text("SELECT has_table_privilege('audit_log', 'UPDATE')"))).scalar() is False
        assert (await db.execute(text("SELECT has_table_privilege('audit_log', 'DELETE')"))).scalar() is False


async def test_cross_tenant_isolation(migrated_db):
    org_a, org_b = uuid.uuid4(), uuid.uuid4()
    async with owner_session() as db:
        for org in (org_a, org_b):
            db.add(Organization(id=org, name=f"Org {org.hex[:6]}"))
        await db.flush()
        for org in (org_a, org_b):
            await set_org_context(db, org)
            u = User(
                org_id=org,
                idp_subject=f"rls-{org}",
                email=f"lead@{org.hex[:6]}.io",
                display_name="Lead",
                role=Role.scrum_lead,
                aliases=[],
            )
            db.add(u)
            await db.flush()
            db.add(Team(org_id=org, name="Secret team", lead_user_id=u.id, timezone="UTC"))
            await db.flush()

    async with session_for(org_a) as db:
        teams = (await db.execute(select(Team))).scalars().all()
        assert {t.org_id for t in teams} == {org_a}
        users = (await db.execute(select(func.count()).select_from(User))).scalar()
        assert users == 1

    # Writing a row for another tenant is rejected by WITH CHECK.
    with pytest.raises(DBAPIError):
        async with session_for(org_a) as db:
            db.add(Organization(id=uuid.uuid4(), name="x"))  # allowed (tenant root)…
            await db.flush()
            lead = (await db.execute(select(User))).scalar_one()
            db.add(Team(org_id=org_b, name="Smuggled", lead_user_id=lead.id, timezone="UTC"))
            await db.flush()

    # No tenant context → no rows at all (not an error).
    async with system_session() as db:
        assert (await db.execute(select(func.count()).select_from(Team))).scalar() == 0


async def test_sign_in_lookup_function(migrated_db):
    org = uuid.uuid4()
    async with owner_session() as db:
        db.add(Organization(id=org, name="Lookup Org", idp_issuer=f"https://idp.example/{org}"))
        await db.flush()
        await set_org_context(db, org)
        db.add(User(org_id=org, idp_subject="kc-sub-123", email="x@lookup.io", display_name="X", aliases=[]))
    async with system_session() as db:
        q = text("SELECT org_id FROM auth_find_user(:s, :i)")
        assert (await db.execute(q, {"s": "kc-sub-123", "i": f"https://idp.example/{org}"})).scalar() == org
        assert (await db.execute(q, {"s": "kc-sub-123", "i": "https://evil.example"})).scalar() is None
        # …but the app role still can't read the users table without tenant context.
        assert (await db.execute(select(func.count()).select_from(User))).scalar() == 0
