from __future__ import annotations

from voiceops.adapters.integration_status import collect_integration_status


def test_integration_status_contract() -> None:
    status = collect_integration_status()
    assert status["audio_source"] in {"HIGGS", "BROWSER_TTS_FALLBACK"}
    assert "boson" in status
    assert "home_assistant" in status
    assert "grandstream_ami" in status
    assert "qwen" in status
    assert "insforge" in status
    assert status["instacloud"]["truth"] == "NOT_CONNECTED"
