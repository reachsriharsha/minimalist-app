"""Round-trip test for /api/v1/hello — skipped without Postgres + Redis."""

from __future__ import annotations


async def test_hello_round_trips_db_and_redis(
    client, require_db, require_redis
):
    """A1.3: two calls, both 200, hello_count strictly increases."""

    r1 = await client.get("/api/v1/hello")
    assert r1.status_code == 200, r1.text
    body1 = r1.json()
    assert body1["item_name"] == "hello"
    assert isinstance(body1["hello_count"], int)

    r2 = await client.get("/api/v1/hello")
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    assert body2["item_name"] == "hello"
    assert body2["hello_count"] > body1["hello_count"]
