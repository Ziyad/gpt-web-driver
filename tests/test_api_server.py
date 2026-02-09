from __future__ import annotations

import pytest


def test_api_server_stream_is_rejected():
    pytest.importorskip("fastapi")
    testclient = pytest.importorskip("fastapi.testclient")

    from gpt_web_driver.api_server import create_app

    class Session:
        paused_reason = None

        async def start(self) -> None:
            return None

        async def close(self) -> None:
            return None

        def resume(self) -> None:
            self.paused_reason = None

        async def chat_completion(self, prompt: str) -> str:
            return "ok"

    app = create_app(session=Session())

    with testclient.TestClient(app) as client:
        r = client.post(
            "/v1/chat/completions",
            json={"stream": True, "messages": [{"role": "user", "content": "hi"}]},
        )
        assert r.status_code == 400
        assert r.json()["detail"]["error"] == "streaming_not_supported"


def test_api_server_usage_fields_are_ints():
    pytest.importorskip("fastapi.testclient")

    from gpt_web_driver.api_server import create_app
    from fastapi.testclient import TestClient

    class Session:
        paused_reason = None

        async def start(self) -> None:
            return None

        async def close(self) -> None:
            return None

        def resume(self) -> None:
            self.paused_reason = None

        async def chat_completion(self, prompt: str) -> str:
            return f"ok:{prompt}"

    app = create_app(session=Session())

    with TestClient(app) as client:
        r = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hi"}]},
        )
        assert r.status_code == 200
        j = r.json()
        assert j["usage"] == {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}


def test_api_server_paused_returns_503():
    pytest.importorskip("fastapi.testclient")

    from gpt_web_driver.api_server import create_app
    from fastapi.testclient import TestClient

    class Session:
        def __init__(self) -> None:
            self.paused_reason = "challenge detected"

        async def start(self) -> None:
            return None

        async def close(self) -> None:
            return None

        def resume(self) -> None:
            self.paused_reason = None

        async def chat_completion(self, prompt: str) -> str:
            return f"ok:{prompt}"

    s = Session()
    app = create_app(session=s)

    with TestClient(app) as client:
        r = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hi"}]},
        )
        assert r.status_code == 503
        assert r.json()["detail"]["error"] == "paused"
