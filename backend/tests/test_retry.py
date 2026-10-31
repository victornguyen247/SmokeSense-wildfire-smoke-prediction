import httpx
import pytest

from ingestion.connectors._common import get_with_retry


def _client(responses):
    calls = iter(responses)

    def handler(request):
        result = next(calls)
        if isinstance(result, Exception):
            raise result
        return result

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_retries_then_succeeds():
    sleeps = []
    client = _client(
        [httpx.Response(503), httpx.Response(429), httpx.Response(200, text="ok")]
    )

    response = get_with_retry(client, "https://example.test", sleep=sleeps.append)

    assert response.status_code == 200
    assert sleeps == [2.0, 4.0]


def test_honours_retry_after():
    sleeps = []
    client = _client(
        [httpx.Response(429, headers={"Retry-After": "30"}), httpx.Response(200)]
    )

    get_with_retry(client, "https://example.test", sleep=sleeps.append)

    assert sleeps == [30.0]


def test_does_not_retry_client_errors():
    sleeps = []
    client = _client([httpx.Response(403)])

    response = get_with_retry(client, "https://example.test", sleep=sleeps.append)

    assert response.status_code == 403
    assert sleeps == []


def test_returns_last_response_when_retries_exhausted():
    client = _client([httpx.Response(500)] * 4)

    response = get_with_retry(client, "https://example.test", sleep=lambda _: None)

    assert response.status_code == 500


def test_raises_network_error_after_last_attempt():
    error = httpx.ConnectError("down")
    client = _client([error, error])

    with pytest.raises(httpx.ConnectError):
        get_with_retry(client, "https://example.test", attempts=2, sleep=lambda _: None)
