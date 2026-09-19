from __future__ import annotations

import json
import threading
from urllib.request import urlopen

from voiceops.adapters.integration_status import collect_integration_status
from voiceops.webapp import VoiceOpsDemoServer


def test_integration_status_contract() -> None:
    status = collect_integration_status()
    assert status["audio_source"] in {"HIGGS", "BROWSER_TTS_FALLBACK"}
    assert "partner_integrations" in status
    assert "boson" in status["partner_integrations"]
    assert "insforge" in status["partner_integrations"]
    assert "instacloud" in status["partner_integrations"]
    assert status["instacloud"]["truth"] == "NOT_CONNECTED"
    assert status["insforge"]["truth"] == "NOT_CONNECTED"
    assert status["partner_integrations"]["boson"]["truth"] in {"REAL", "FALLBACK"}


def test_instacloud_remote_probe_when_configured(monkeypatch) -> None:
    class FakeResponse:
        status = 200

        def read(self) -> bytes:
            return b'{"ok": true, "service": "voiceops-boson-preview"}'

        def __enter__(self):
            return self

        def __exit__(self, *args: object) -> None:
            return None

    monkeypatch.setenv("INNEROS_INSTACLOUD_ENABLED", "true")
    monkeypatch.setenv("INSTACLOUD_API_KEY", "test-key")
    monkeypatch.setenv("INSTACLOUD_PREVIEW_URL", "https://preview.example.test")
    monkeypatch.setenv("INSTACLOUD_DEPLOYMENT_ID", "voiceops-boson-preview")

    from voiceops.adapters.instacloud_provider import InstaCloudProvider

    status = InstaCloudProvider().get_status(opener=lambda *args, **kwargs: FakeResponse())
    assert status["truth"] == "REAL"
    assert status["deployment_status"] == "HEALTHY"
    assert status["remote_confirmed"] is True


def test_integrations_status_http_endpoint() -> None:
    server = VoiceOpsDemoServer(("127.0.0.1", 0))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    base = f"http://{host}:{port}"
    try:
        with urlopen(base + "/api/integrations/status", timeout=3) as response:  # noqa: S310
            data = json.loads(response.read().decode("utf-8"))
        assert "partner_integrations" in data
        assert data["insforge"]["remote_confirmed"] is False

        with urlopen(base + "/api/integrations/status?ts=1", timeout=3) as response:  # noqa: S310
            assert response.status == 200
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
