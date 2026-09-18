# VoiceOps recovery handoff — 2026-09-18

## Source and boundaries

The original Cursor commits were recovered intact from the uploaded Git bundle (SHA256 `7235939871dcee351f2baef002c700d73b976ee603bce60b3cc1761a8fc779d5`). They are `0b68a28b45ddd8eacd58091bcb1c8a217ee68bb6`, `c09b7df807f63159cc9278edd8e8abb780ab21a4`, and `c922d29062b042e79e8df9749cd188e04f1d702b`, descending from `4f33cd41434f396582a55b49eade3c040002e193`.

Recovery changes are additive. Do not reset the branch or modify the separate canonical VoiceOps repositories. Temporary transfer scripts and bundles are not product source.

## Running installation

The isolated application is installed on the primary local server as `inneros-voiceops-boson.service`, using the project virtual environment. Port **8875**, not 8765 (which belongs to QuoteOps). The public hostname is `https://voiceopsboson.creatorcore.ai`. It exposes this local origin through Cloudflare. The old `voiceops.creatorcore.ai` deployment is separate and unchanged.

`/healthz` reports the actual loaded build SHA. Start/restart via `systemctl --user`, not a system-wide unit. The user service is enabled and user linger is enabled. Reload after a source change before claiming the running SHA changed.

## Verified on the primary runtime

- HTTP health and public Cloudflare health returned 200.
- Qwen local conversation returned a generative greeting (about 2.15 seconds) with `LIVE_MODEL_RESPONSE`; no telemetry tool was called for that greeting.
- A follow-up energy question invoked `inspect_operational_state` and returned the actual observed inverter output and battery voltage (497 W and 27.6 V at the recorded test time, not constants to reproduce).
- Home Assistant values are read through the existing local authenticated integration. Inverter AC output is **not** photovoltaic generation. kW is converted to W for the breaker field.
- Grandstream status is obtained from the existing authenticated UCM runtime broker. It currently covers the configured owner extensions, **not an inventory of every PBX extension**. Connected PBX and registered phone are distinct states.
- Alarm state is observed; unknown zone count stays unknown. NVR network presence is not claimed as a live image or motion detection.
- The safe action `create_incident_ticket` was proposed, rejected under explicit negation, then approved in a separate test. A local file was written and independently read back; its SHA256 was returned. Repeating the consumed proposal was blocked.
- Physical network, breaker, alarm, and PBX mutations are blocked in the public demo. The ticket is a real local action, not a physical actuation.
- Python regression suite: **136 passed** after updating obsolete tests that previously expected simulated physical actions to succeed.
- Browser playback contract executed in Node against the actual app.js: sequential PCM scheduling, cancellation, one fallback utterance per completed response, and no simultaneous native/TTS playback passed. This is a deterministic audio pipeline test, **not a claim that the user's speakers were heard remotely**.

## Native Higgs and optional providers

The real Boson server relay and client-secret code are present. Session setup now initiates `session.update` immediately after connecting, rather than waiting indefinitely for the session it has not yet created. Input/output use 24 kHz PCM, native server VAD, and session-bound tool handling. A missing/failed connection visibly selects browser voice fallback; ordinary fallback dialogue uses local Qwen.

**Native Higgs is not yet end-to-end verified in this runtime because the provider credential has not been activated.** An owner-only short-lived setup link is obtained on the local server through `/api/operator/setup-link`; it validates the key against Boson before storing it outside Git. Do not publish that invitation or a credential in source or logs. Do not call a browser TTS response native Higgs audio.

**InsForge: NOT CONNECTED / remote authentication and readback still required.** Its optional mirror must not block local evidence. **InstaCloud: NOT CONNECTED**, and no preview deployment is claimed. These are not completed sponsor integrations.

## Reproduce

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m pytest -q
node tests/audio_playback_contract.cjs
.venv/bin/python -m voiceops.webapp --host 127.0.0.1 --port 8875 --reasoner amd5
```

For a standalone installation, configure the documented HA, AMI, Boson, local Qwen and optional InsForge environment variables. The local-home broker integration is optional and installation-specific. Never fabricate LIVE status when a dependency is missing. Use HTTPS or localhost for browser microphone permissions; plain private-IP HTTP is not a microphone-ready secure context.

Do not create or move the final judging tag until the owner has accepted the actual voice demonstration and the submission description matches the verified provider state.

## Publication branch

The independently recovered local runtime is published on `chatgpt/boson-runtime-recovery-20260918`. The hackathon branch advanced separately to `8afdd18` and is preserved unchanged. Do not force-push or replace that parallel source tree. Use the recovered runtime branch and its exact build SHA when auditing this running installation.
