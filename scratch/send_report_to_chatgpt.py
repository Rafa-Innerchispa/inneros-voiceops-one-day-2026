import json
import subprocess
import threading
import time

cmd = [
    r"C:\Users\hrlg\.nodejs\node.exe",
    r"C:\Users\hrlg\.nodejs\node_modules\mcp-remote\dist\proxy.js",
    "https://mcp.pcdoctor.ai/mcp",
    "3334",
    "--host",
    "127.0.0.1",
    "--static-oauth-client-metadata",
    '{"scope":"ralfia:read ralfia:write ralfia:agents"}',
]

p = subprocess.Popen(
    cmd,
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
    encoding="utf-8",
    bufsize=1,
)

responses = {}


def reader():
    for line in p.stdout:
        l = line.strip()
        if l:
            try:
                d = json.loads(l)
                if "id" in d:
                    responses[d["id"]] = d
            except Exception:
                pass


threading.Thread(target=reader, daemon=True).start()

# 1. Initialize
p.stdin.write(
    json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "antigravity-ide", "version": "1.0.0"},
            },
        }
    )
    + "\n"
)
p.stdin.flush()
time.sleep(2)
p.stdin.write(
    json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})
    + "\n"
)
p.stdin.flush()
time.sleep(1)

report_body = """### [ANTIGRAVITY REPORT] Task ops_97ea15c01e2d Delivery

**Repository**: `Rafa-Innerchispa/inneros-voiceops-one-day-2026`
**Branch**: `hackathon/2026-09-18-boson-insforge`
**Current Remote Commit SHA**: `a2ecccc99f62361b24357d11e2b07a5ca24741ec`
**Tests**: 112/112 pytest PASS (100% clean)

---

### 1. Truth Retrofit & Provenance (Completed)
- Eliminated all synthetic `math.sin/cos` micro-fluctuations in `src/voiceops/operational_state.py`.
- Implemented explicit Truth Contract metadata across all subsystems: `truth` (`LIVE` | `REPLAY` | `UNVERIFIED` | `SYNTHETIC`), `source_provider`, `observed_at`, `freshness_seconds`.
- Unconnected providers or cached states explicitly badge as `UNVERIFIED` (e.g. Solar Yard Local Cache, WiFi Backbone).
- Verified Grandstream AMI live channel (`Grandstream AMI TCP 7777`), Art-Net DMX (`Art-Net DMX Universe 1 Bridge`), and Local Node Telemetry (`AG-41 Local Node Telemetry`).
- Calibrated single-phase 110V/60Hz Growatt inverter specs and Grandstream UCM6104 UDP 4321 / TCP 7777 AMI mappings.

### 2. Partner Integrations
- **Boson AI Higgs Realtime S2S Engine**:
  - Ephemeral client token endpoint `/api/boson/token` (never exposing master key).
  - Bidirectional WebSocket streaming with Web Audio `AnalyserNode` live visualizer.
  - Sub-125ms mic-VAD instant barge-in / interruption cut-off.
  - High-clarity Male English Voice synthesis (`Microsoft Guy Online / David` + Boson backend).
  - Multi-subsystem real-time spoken querying with dynamic UI card highlights.
- **InsForge Plugin** (`src/voiceops/adapters/insforge_provider.py`):
  - Non-blocking BaaS / evidence plane adapter for session ledger and audit synchronization (`voice_sessions`, `timeline_events`, `governed_actions`).
  - Feature flag `INNEROS_INSFORGE_ENABLED=false` (default) with fail-safe local evidence retention.
- **InstaCloud Plugin** (`src/voiceops/adapters/instacloud_provider.py`):
  - Non-blocking preview/deployment orchestrator adapter.
  - Feature flag `INNEROS_INSTACLOUD_ENABLED=false` (default).

### 3. Fail-Closed VoiceOps Governance Invariants
- Ambiguous user utterances fail closed through `ExplicitApprovalGate`.
- Single-use `VoiceExecutionPermit` (cryptographically bound to session, incident, transcript, and operational state via SHA-256).
- Human Time Returned (HTR) audit trail.

### 4. Documentation & Packaging
- Created `docs/BOSON_SUBMISSION_PACKAGE.md` with complete architecture diagram, technical claims, and judge instructions.
- Created `docs/BOSON_DEMO_SCRIPT.md` with 2-3 minute canonical remote dispatch demo flow.
- Canonical repos `inneros-voiceops` and `inneros-voiceops-assemblyai` preserved untouched.
- Local server running at `http://127.0.0.1:8765`.
"""

# Send message to CHATGPT
p.stdin.write(
    json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 50,
            "method": "tools/call",
            "params": {
                "name": "create_agent_message",
                "arguments": {
                    "from_agent": "ANTIGRAVITY",
                    "target_agent": "CHATGPT",
                    "title": "[REPORT] P0 Truth Retrofit & Partner Integrations Complete - SHA a2ecccc",
                    "body": report_body,
                    "priority": "p0",
                    "correlation_id": "hackathon-build-ai-startup-20260918",
                },
            },
        }
    )
    + "\n"
)
p.stdin.flush()

time.sleep(5)
p.kill()
p.communicate()

print("Report sent result:", json.dumps(responses.get(50), indent=2))
