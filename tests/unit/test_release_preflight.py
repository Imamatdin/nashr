"""Release probes distinguish unreachable services, missing schema, and bad auth."""

import httpx
import pytest

from scripts.release_preflight import ProbeConfig, run_checks


def _config() -> ProbeConfig:
    return ProbeConfig(
        api_url="https://api.test",
        supabase_url="https://db.test",
        service_key="private-test-key",
    )


async def test_missing_schema_is_not_reported_as_database_outage() -> None:
    """A reachable database without new tables is a distinct release failure."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.test":
            assert "apikey" not in request.headers
            assert "authorization" not in request.headers
            return httpx.Response(200, json={"status": "ok", "service": "nashr-api"})
        assert request.headers["apikey"] == "private-test-key"
        assert request.method == "GET"
        if request.url.path == "/rest/v1/projects":
            assert request.url.params["limit"] == "0"
            return httpx.Response(200, json=[])
        return httpx.Response(404, json={"message": "private-test-key"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        checks = await run_checks(_config(), client)
    results = {check.name: check for check in checks}
    assert results["api"].ok
    assert results["database"].ok
    assert not results["documents"].ok
    assert results["documents"].detail == "HTTP 404"
    assert "private-test-key" not in str(checks)


@pytest.mark.parametrize("status", [301, 401, 403, 429, 503])
async def test_non_success_responses_fail_closed(status: int) -> None:
    """Redirects, denied credentials, throttling and outages never count as ready."""
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(status))
    ) as client:
        checks = await run_checks(_config(), client)
    assert all(not check.ok for check in checks)
    assert all(check.detail == f"HTTP {status}" for check in checks)


async def test_timeout_does_not_echo_request_secrets() -> None:
    """Exception messages can contain request details; only emit the error class."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("private-test-key", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        checks = await run_checks(_config(), client)
    assert all(not check.ok and check.detail == "ConnectTimeout" for check in checks)


async def test_real_response_shapes_and_rpc_catalog_are_required() -> None:
    """A proxy HTML success page cannot pass a release probe."""
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text="<html>OK</html>"))
    ) as client:
        checks = await run_checks(_config(), client)
    assert all(not check.ok and check.detail == "Unexpected response" for check in checks)


async def test_all_expected_schema_surfaces_present() -> None:
    """Inspect the RPC catalog without invoking any write RPC."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.test":
            payload = {"status": "ok", "service": "nashr-api"}
        elif request.url.path == "/rest/v1/":
            payload = {
                "paths": {
                    "/rpc/ensure_document": {},
                    "/rpc/commit_revision": {},
                    "/rpc/accept_proposal": {},
                    "/rpc/reject_proposal": {},
                    "/rpc/register_export": {},
                }
            }
        else:
            return httpx.Response(200, json=[])
        return httpx.Response(200, json=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        checks = await run_checks(_config(), client)
    assert len(checks) == 5
    assert all(check.ok for check in checks)
