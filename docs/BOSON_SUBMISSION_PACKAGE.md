# Boson AI Higgs Audio & InsForge Hackathon 2026 — Submission Package

## Project Title
**InnerOS VoiceOps — Realtime Speech-to-Speech Operational Governance with Boson AI Higgs Audio & InsForge**

## Short Description
InnerOS VoiceOps turns spoken operational intent into deterministic, auditable physical execution. Powered by **Boson AI Higgs Realtime S2S** with ultra-low latency streaming, male voice synthesis, and instant mic barge-in, VoiceOps governs real edge infrastructure (110V solar inverters, Grandstream PBX telephony, Art-Net DMX stage lighting, and AG-41 compute nodes) through single-use cryptographically bound execution permits, strict truth-contracted telemetry, and non-blocking InsForge/InstaCloud persistence.

---

## Key Highlights & Innovations

### 1. Boson AI Higgs Audio Realtime Speech-to-Speech
- **Ultra-low latency streaming**: Bidirectional audio streaming over WebSocket with live microphone capture (`AnalyserNode` visualization).
- **Instant Mic-VAD Barge-in (<125ms)**: User interruption cuts audio playback immediately and cancels inflight generation.
- **Natural Male Voice Synthesis**: High-clarity enterprise English male voice (`Microsoft Guy Online / David` & Boson Higgs backend) calibrated for mission-critical dispatch.
- **Dynamic Mid-Conversation Multi-Subsystem Intelligence**: Spoken queries dynamically resolve telemetry across Solar Inverter, PBX Telephony, Studio Lighting, and Compute Cluster in real-time.

### 2. Strict Truth Retrofit & Provenance
- **Zero Fake Fluctuations**: Elimination of synthetic `math.sin/cos` simulation. Telemetry is either fetched live or explicitly tagged with its actual provenance.
- **Standardized Truth Contract**: Every metric and subsystem is tagged with `truth`: `LIVE` | `REPLAY` | `UNVERIFIED` | `SYNTHETIC`.
- **Ecuador Hardware Grounding**:
  - **Solar Microgrid**: 110V / 60Hz single-phase Growatt Hybrid 5kW SPF 5000 ES with 48V LiFePO4 battery bank.
  - **PBX Telephony**: Grandstream UCM6104 IP PBX with AMI TCP 7777 and UDP 4321 signaling.
  - **Studio Lighting**: Art-Net DMX512 node over UDP 6454.
  - **Compute Fleet**: Node `AG-41` (Ubuntu 24.04, AMD ROCm 6.2).

### 3. Fail-Closed VoiceOps Governance
- **Explicit Approval Gate**: Ambiguous consent (`"maybe"`, `"if you want"`) fails closed and halts execution.
- **VoiceExecutionPermit**: Short-lived, single-use execution token cryptographically bound via SHA-256 to `session_id`, `incident_id`, `transcript_hash`, and `state_hash`.
- **Human Time Returned (HTR)**: Verifiable operational time-saving audit trail separating measured vs. estimated gains.

### 4. Non-Blocking Provider Adapters
- **InsForge Plugin**: BaaS / evidence plane adapter for cloud audit logging and compliance synchronization.
- **InstaCloud Plugin**: Preview and deployment orchestrator.
- **Graceful Degradation**: Both adapters run non-blockingly without impeding core local VoiceOps governance when cloud credentials are absent.

---

## Architecture Diagram

```mermaid
flowchart TD
    subgraph Client ["Browser VoiceOps Console"]
        MIC[Live Microphone / VAD]
        UI[Vector Dark/Light Dashboard]
        AUDIO[Web Audio Output / Visualizer]
    end

    subgraph BosonAudio ["Boson AI Voice Engine"]
        HIGGS[Higgs Realtime S2S API]
        S2S_STREAM[Bidirectional Audio WebSocket]
    end

    subgraph VoiceOpsCore ["InnerOS VoiceOps Core Engine"]
        ROUTER[Intent & Context Dispatcher]
        GATE[Explicit Approval Gate]
        PERMIT[VoiceExecutionPermit Engine (SHA-256)]
        TRUTH[Truth-Contracted Operational State]
        HTR[Human Time Returned Audit]
    end

    subgraph PhysicalEdge ["Edge Infrastructure (Guayaquil Node)"]
        SOLAR[Growatt Inverter 110V/60Hz]
        PBX[Grandstream UCM6104 AMI 7777]
        DMX[Art-Net DMX512 UDP 6454]
        ROCM[AG-41 Compute Node]
    end

    subgraph CloudAdapters ["Non-Blocking Cloud Adapters"]
        INSFORGE[InsForge Evidence BaaS]
        INSTACLOUD[InstaCloud Preview Engine]
    end

    MIC -->|Audio Stream / Barge-in| S2S_STREAM
    S2S_STREAM <--> HIGGS
    HIGGS -->|Spoken Audio & Tool Intent| S2S_STREAM
    S2S_STREAM --> AUDIO
    
    HIGGS <-->|Tool Execution & Telemetry| ROUTER
    ROUTER --> TRUTH
    TRUTH <--> PhysicalEdge
    
    ROUTER --> GATE
    GATE -->|Explicit Spoken Approval| PERMIT
    PERMIT -->|Single-Use Execution| PhysicalEdge
    PERMIT --> HTR
    
    HTR -.-> INSFORGE
    VoiceOpsCore -.-> INSTACLOUD
    TRUTH --> UI
```

---

## Test Verification Suite
- **112 / 112 automated tests PASS** (`python -m pytest --basetemp=.pytest_temp -q`).
- Full coverage across:
  - Boson AI Higgs Realtime S2S mock & websocket streaming.
  - Explicit approval gate fail-closed behavior on ambiguity.
  - Single-use permit consumption & state-hash tampering resistance.
  - Truth contract badges (`LIVE`, `REPLAY`, `UNVERIFIED`).
  - Non-blocking InsForge and InstaCloud provider isolation.
  - Ecuador 110V/60Hz grid and Grandstream AMI telephony models.

---

## Repositories & Deployments
- **Hackathon Branch**: `hackathon/2026-09-18-boson-insforge`
- **Repository**: `https://github.com/Rafa-Innerchispa/inneros-voiceops-one-day-2026`
- **Baseline Release**: `pre-hackathon-2026-09-18`
- **Submission Release**: `submission-2026-09-18`
