"""Black-box checks for ``X-Request-ID`` propagation."""

from __future__ import annotations

from uuid import uuid4

import httpx


HEADER = "X-Request-ID"


def test_request_id_echoed_when_client_sends_one(client: httpx.Client) -> None:
    """A client-supplied ``X-Request-ID`` must be echoed verbatim."""

    supplied = str(uuid4())
    response = client.get("/healthz", headers={HEADER: supplied})

    assert response.status_code == 200, response.text
    # ``httpx`` headers are case-insensitive on lookup; use the canonical name.
    echoed = response.headers.get(HEADER)
    assert echoed == supplied, (supplied, echoed)


def test_request_id_generated_when_client_omits_header(
    client: httpx.Client,
) -> None:
    """Absent a client header, the server must generate a non-empty value."""

    response = client.get("/healthz")

    assert response.status_code == 200, response.text
    generated = response.headers.get(HEADER)
    assert generated is not None, dict(response.headers)
    assert generated, "server-generated X-Request-ID was empty"
