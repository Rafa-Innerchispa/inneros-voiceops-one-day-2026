# VoiceOps recovered local runtime

Date: 2026-09-18. Runtime owner for this recovery: ChatGPT.

## Source and release boundaries

Cursor's original bundle has been recovered with original commits 0b68a28, c09b7df, c922d29 intact. SHA256 of received bundle: 7235939871dcee351f2baef002c700d73b976ee603bce60b3cc1761a8fc779d5.

The hackathon branch advanced separately to d8dda5013a8ceecef86ddb35e500836208539a15 during recovery. Do not overwrite it. This recovered and runtime-tested implementation is published separately as `chatgpt/boson-runtime-recovery-20260918`. Select its exact commit when judging this runtime. `main`, the original VoiceOps production and QuoteOps remain unchanged.

## Running deployment

Public: https://voiceopsboson.creatorcore.ai
LAN dashboard: http://192.168.1.4:8875
Use HTTPS for browser microphone access.
Host: primary local Intel .4. Service: `inneros-voiceops-boson.service`, systemd USER scope. Port 8765 belongs to QuoteOps and must not be used.
Runtime path: `/home/rlopez/inneros/inneros_core/workspaces/inneros-voiceops-one-day-2026`.

## Verified vs pending

- HTTP app and new Cloudflare tunnel route work. Restart persistence must be checked after the final source commit.
- Home Assistant is read through the existing local `homeassistant_client`, using its own authorized server-side configuration.
- Inverter AC output is NOT PV generation. Breaker kW is converted to W. Unknown values remain unknown.
- Alarm state is real. Zone count is not invented.
- PBX data comes from the existing read-only UCM runtime broker. This shows only configured owner endpoints, currently 1004 and 1006. It is NOT a complete PBX extension inventory. Registration updates require the actual phone; no demo register endpoint is used.
- Local Qwen/vLLM replies and tool use were verified against 127.0.0.1:18000. Greeting and battery-voltage follow-up made real model requests and read actual HA data.
- Browser speech synthesis is the available audible fallback. Audio queue and interruption logic were repaired. Human speaker/microphone verification is still required on the user's browser.
- The Boson relay implements the documented GA protocol: 24 kHz PCM, output_audio events, real upstream connection, real client-secret API, tool outputs after response.done. Native audio is NOT marked validated until a real credential/session succeeds.
- Owner provider setup is exposed only by an expiring invitation generated on the local server. Never commit credentials or invitation URLs.
- InsForge code supports remote I/O but no authenticated insert/readback was verified in this runtime. Display NOT_CONNECTED.
- InstaCloud is optional and NOT_CONNECTED. No cloud migration was performed.
- Camera data is NVR presence only. No motion event or camera image proof is claimed.
- DMX status is read-only from the existing local engine. The public execution flow does not alter physical hardware.

## Executable demo action

`create_incident_ticket` proposes a local incident ticket. Explicit human approval uses the existing deterministic gate, issues and consumes a single-use permit, persists a JSON ticket, reads it back and hashes the evidence. Physical network/power/PBX/alarms operations remain blocked. Do not describe this ticket action as a physical actuation.

## Validation commands

`python -m pip install -e '.[dev]'`
`python -m pytest tests/test_recovered_runtime.py -q`
`node --check src/voiceops/web/app.js`
`python -m compileall -q src`
`git diff --check`

The historic simulation tests predate the truthful runtime contract; keep their outcomes separate from live acceptance. Passing unit tests alone is not evidence of a connected provider. Tests with mocks never constitute physical execution proof.
