"""Operations console: admin authorization, desk review queue, copy-job history."""
from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.domain import CopyJob, Desk, User
from tests.conftest import auth_headers, make_admin

pytestmark = pytest.mark.asyncio


async def _user_id(email: str) -> str:
    async with AsyncSessionLocal() as session:
        user = (
            await session.execute(select(User).where(User.email == email))
        ).scalar_one()
        return user.id


async def _seed_pending_desk(email: str, name: str, slug: str) -> str:
    async with AsyncSessionLocal() as session:
        desk = Desk(
            owner_user_id=await _user_id(email),
            name=name,
            slug=slug,
            description="desk waiting for review",
            status="PENDING_REVIEW",
        )
        session.add(desk)
        await session.flush()
        await session.commit()
        return desk.id


async def _seed_copy_job(desk_id: str, follower_email: str) -> str:
    async with AsyncSessionLocal() as session:
        job = CopyJob(
            desk_id=desk_id,
            follower_user_id=await _user_id(follower_email),
            source_fill_id="fill-seeded-for-the-console",
            status="FILLED",
            copy_ratio=0.25,
            requested_shares=10,
            filled_shares=10,
        )
        session.add(job)
        await session.flush()
        await session.commit()
        return job.id


async def test_admin_routes_reject_a_regular_account(client: AsyncClient):
    headers = await auth_headers(client, "regular-console@example.com")

    event = await client.post(
        "/api/v4/prediction/admin/events",
        json={"slug": "nope", "title": "Nope"},
        headers=headers,
    )
    assert event.status_code == 403
    assert event.json()["detail"] == "ADMIN_REQUIRED"

    market = await client.post(
        "/api/v4/prediction/admin/markets",
        json={"event_slug": "nope", "question": "Nope?", "outcomes": ["YES", "NO"]},
        headers=headers,
    )
    assert market.status_code == 403
    assert market.json()["detail"] == "ADMIN_REQUIRED"

    close = await client.post("/api/v4/prediction/admin/markets/any/close", headers=headers)
    assert close.status_code == 403
    assert close.json()["detail"] == "ADMIN_REQUIRED"

    queue = await client.get("/api/v4/prediction/admin/desks", headers=headers)
    assert queue.status_code == 403
    assert queue.json()["detail"] == "ADMIN_REQUIRED"

    jobs = await client.get("/api/v4/prediction/admin/copy-jobs", headers=headers)
    assert jobs.status_code == 403
    assert jobs.json()["detail"] == "ADMIN_REQUIRED"


async def test_admin_creates_an_event_and_a_market(client: AsyncClient):
    admin = await auth_headers(client, "console-admin@example.com")
    await make_admin("console-admin@example.com")

    event = await client.post(
        "/api/v4/prediction/admin/events",
        json={"slug": "console-event", "title": "Console Event", "category": "Crypto"},
        headers=admin,
    )
    assert event.status_code == 201, event.text
    assert event.json()["slug"] == "console-event"

    market = await client.post(
        "/api/v4/prediction/admin/markets",
        json={
            "event_slug": "console-event",
            "question": "Does the console work?",
            "outcomes": ["YES", "NO"],
        },
        headers=admin,
    )
    assert market.status_code == 201, market.text
    body = market.json()
    assert body["question"] == "Does the console work?"
    assert [t["symbol"] for t in body["tokens"]] == ["YES", "NO"]
    assert body["status"] == "ACTIVE"


async def test_review_queue_lists_pending_desks_and_approves_them(client: AsyncClient):
    admin = await auth_headers(client, "queue-admin@example.com")
    await make_admin("queue-admin@example.com")
    owner = await auth_headers(client, "queue-owner@example.com")
    desk_id = await _seed_pending_desk("queue-owner@example.com", "Queue Desk", "queue-desk")

    queue = await client.get("/api/v4/prediction/admin/desks", headers=admin)
    assert queue.status_code == 200
    desks = queue.json()["desks"]
    entry = next(d for d in desks if d["id"] == desk_id)
    assert entry["owner_email"] == "queue-owner@example.com"
    assert entry["status"] == "PENDING_REVIEW"
    assert entry["follower_count"] == 0

    approved = await client.post(f"/api/v4/prediction/admin/desks/{desk_id}/approve", headers=admin)
    assert approved.status_code == 200
    assert approved.json()["status"] == "ACTIVE"

    # A desk that is no longer pending leaves the default queue.
    queue = await client.get("/api/v4/prediction/admin/desks", headers=admin)
    assert all(d["id"] != desk_id for d in queue.json()["desks"])
    active = await client.get("/api/v4/prediction/admin/desks?status=ACTIVE", headers=admin)
    assert any(d["id"] == desk_id for d in active.json()["desks"])

    # The owner cannot approve their own desk.
    denied = await client.post(f"/api/v4/prediction/admin/desks/{desk_id}/approve", headers=owner)
    assert denied.status_code == 403


async def test_copy_job_history_lists_jobs_for_admins(client: AsyncClient):
    admin = await auth_headers(client, "jobs-admin@example.com")
    await make_admin("jobs-admin@example.com")
    follower = await auth_headers(client, "jobs-follower@example.com")
    desk_id = await _seed_pending_desk("jobs-follower@example.com", "Jobs Desk", "jobs-desk")
    job_id = await _seed_copy_job(desk_id, "jobs-follower@example.com")

    jobs = await client.get("/api/v4/prediction/admin/copy-jobs", headers=admin)
    assert jobs.status_code == 200
    entries = jobs.json()["jobs"]
    entry = next(j for j in entries if j["id"] == job_id)
    assert entry["desk_name"] == "Jobs Desk"
    assert entry["follower_email"] == "jobs-follower@example.com"
    assert entry["status"] == "FILLED"
    assert entry["copy_ratio"] == 0.25
    assert entry["requested_shares"] == 10
    assert entry["filled_shares"] == 10

    filtered = await client.get("/api/v4/prediction/admin/copy-jobs?status=REJECTED", headers=admin)
    assert filtered.json()["jobs"] == []

    denied = await client.get("/api/v4/prediction/admin/copy-jobs", headers=follower)
    assert denied.status_code == 403


async def test_trader_copy_jobs_stay_scoped_to_the_caller(client: AsyncClient):
    follower = await auth_headers(client, "scoped-follower@example.com")
    desk_id = await _seed_pending_desk("scoped-follower@example.com", "Scoped Desk", "scoped-desk")
    job_id = await _seed_copy_job(desk_id, "scoped-follower@example.com")

    mine = await client.get("/api/v1/copy-jobs", headers=follower)
    assert mine.status_code == 200
    assert [j["id"] for j in mine.json()["jobs"]] == [job_id]

    other = await auth_headers(client, "scoped-other@example.com")
    theirs = await client.get("/api/v1/copy-jobs", headers=other)
    assert theirs.json()["jobs"] == []


async def test_auth_me_reports_the_admin_flag(client: AsyncClient):
    admin = await auth_headers(client, "flag-admin@example.com")
    await make_admin("flag-admin@example.com")
    regular = await auth_headers(client, "flag-regular@example.com")

    me_admin = await client.get("/api/v1/auth/me", headers=admin)
    assert me_admin.status_code == 200
    assert me_admin.json()["is_admin"] is True

    me_regular = await client.get("/api/v1/auth/me", headers=regular)
    assert me_regular.json()["is_admin"] is False
