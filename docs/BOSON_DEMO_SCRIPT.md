# Boson AI Higgs Audio & InsForge — Canonical Demo Script

## Goal
Demonstrate sub-second Speech-to-Speech interaction with Boson AI Higgs Audio, live microphone capture, English male voice dispatch, truth-contracted real-time hardware telemetry, and fail-closed approval governance with single-use execution permits.

---

## 2-3 Minute Spoken Demo Flow

### Scene: Remote Operations Dispatch
- **Context**: Ecuadorian founder operating in San Francisco governing the Guayaquil edge facility (110V/60Hz Growatt solar microgrid, Grandstream UCM6104 PBX, Art-Net DMX lighting, and AG-41 compute node).

---

### Step 1: Voice Verification & Live Telemetry Inquiry
- **User (Spoken Mic)**:
  > *"Ralphi, give me a status report on the Guayaquil solar inverter and check if our PBX telephony extensions are registered."*

- **VoiceOps (Boson Higgs Realtime Male Voice)**:
  > *"Guayaquil inverter is operating on 110 volts AC at 60 Hertz with battery at 88 percent. PBX telephony extension 101 is registered on UDP 4321, with 3 extensions online. Art-Net DMX and compute node AG-41 are both operational."*
  
- **Visual Feedback**:
  - Web Audio microphone visualizer waves activate.
  - Solar and PBX telemetry cards glow purple on live reference.
  - Explicit badges indicate `TRUTH: LIVE` with source `Grandstream AMI TCP 7777` and `Home Assistant REST`.

---

### Step 2: Instant Barge-in & Context Code-Switching
- **User Interrupts Mid-Speech (<125ms Barge-in)**:
  > *"Wait, what is our current grid load, and can we dim the studio lights to standby?"*

- **VoiceOps (Immediate Cut-off & Responsive Spoken Answer)**:
  > *"Grid load is currently 420 watts on the 110-volt line. I can dim the studio lights to 20 percent on Art-Net universe 0. Do you authorize this adjustment?"*

---

### Step 3: Ambiguity Test (Fail-Closed Governance)
- **User (Ambiguous / Casual Response)**:
  > *"Maybe, if you think it's okay."*

- **VoiceOps (Governance Rejection)**:
  > *"Adjustment held. Ambiguous input received. I require an explicit 'I authorize' or 'Proceed' to execute physical changes."*

---

### Step 4: Explicit Approval & Execution Permit Issuance
- **User (Explicit Authorization)**:
  > *"I authorize the studio light adjustment now."*

- **VoiceOps (Execution & HTR Audit)**:
  > *"Authorized. Single-use Voice Execution Permit issued. Art-Net DMX universe 0 set to 20 percent. Decision recorded in audit log. 180 seconds of Human Time Returned."*

- **Visual Feedback**:
  - Studio Lighting card updates to `Standby (20%)`.
  - HTR counter increases with SHA-256 permit badge.
  - Non-blocking InsForge compliance event synchronized.
