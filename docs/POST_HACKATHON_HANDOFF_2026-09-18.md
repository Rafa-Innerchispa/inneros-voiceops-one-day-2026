# InnerOS VoiceOps / Boson Higgs — Post-Hackathon Handoff

Date: 2026-09-18
Event: Build an AI Startup in One Day — Boson AI / AWS Builder Loft, San Francisco
Project: InnerOS VoiceOps
Repository: Rafa-Innerchispa/inneros-voiceops-one-day-2026
Public runtime: https://voiceopsboson.creatorcore.ai

## Outcome

The project was submitted and presented. It did not win a prize, but the technical work is being preserved as a reusable experimental branch of the InnerOS VoiceOps product line.

The hackathon repo remains separate from the long-lived VoiceOps product repositories. Reusable improvements should be ported deliberately after review rather than merging the hackathon repo wholesale.

## Preserve both development lines

### Recovery / demo line
Branch: chatgpt/boson-runtime-recovery-20260918
SHA at demo recovery: 27240eb5d5688bcb0cdef213b1eb973b7613ecb8
Archive branch: archive/2026-09-18-demo-recovery

This line contains the persistent .4 runtime recovery, truthful provider status, browser voice fallback, local Qwen routing, live Home Assistant reads, governed safe actions, evidence contracts, and the final verified test suite.

### Hackathon / Cursor line
Branch: hackathon/2026-09-18-boson-insforge
SHA after latest hackathon-track update: 4377b96b048ea2c6c0430e6addddd71c29826fc6
Archive branch: archive/2026-09-18-hackathon-track

This line preserves independent work done during the hackathon, including later Home Assistant bridge fixes. It was intentionally not force-merged over the recovery line.

## Permanent product repositories

Do not overwrite or erase the existing VoiceOps product work:
- Rafa-Innerchispa/inneros-voiceops
- Rafa-Innerchispa/inneros-voiceops-assemblyai

Post-hackathon rule: the one-day repository is an experiment/snapshot. Reusable Higgs, governance, status, audio, and evidence improvements can be reviewed and ported to the permanent VoiceOps product incrementally.

## Runtime state recovered during the event

Canonical hackathon runtime host:
- node: .4 / primary
- service: inneros-voiceops-boson.service
- port: 8875
- public hostname: voiceopsboson.creatorcore.ai
- service enabled under systemd --user
- user linger enabled

At the final recovery checkpoint:
- public / and /healthz returned HTTP 200
- runtime health exposed build SHA 27240eb5d5688bcb0cdef213b1eb973b7613ecb8
- Home Assistant read path was REAL/LIVE
- local AMD/Qwen reasoning was proven with live Home Assistant tool use
- Grandstream status path exposed configured owner extensions only
- physical infrastructure mutations remained disabled in the public demo
- safe local incident-ticket execution used explicit approval, a single-use permit, persistence, independent readback, and evidence hashing

## Voice architecture

Two voice paths exist and must remain visibly distinct:

1. Native Boson Higgs Realtime
   - model: higgs-realtime
   - realtime WebSocket: wss://api.boson.ai/v1/realtime
   - STT inside the session: higgs-stt-3.1
   - native PCM audio output
   - tool calling and interruption handling

2. Browser fallback
   - browser speech recognition / text path
   - VoiceOps + local Qwen/tools
   - browser SpeechSynthesis output

Truth rule:
- Audible speech alone does not prove Higgs.
- Mark AUDIO_SOURCE=HIGGS only after a real Higgs realtime connection and native audio are observed.
- Otherwise mark fallback truthfully.

## Governance contract

Core demo flow:

inspect -> propose -> explicit human approval -> single-use execution permit -> execute -> verify -> evidence

The model cannot authorize its own consequential action.

Public demo physical mutations remain blocked. A safe local incident-ticket action was used for end-to-end governance proof.

## Testing evidence

Recovery line final test evidence:
- 136 pytest tests passed
- sequential PCM playback / cancellation / once-per-turn fallback contract passed
- no double-speech contract passed
- compile / syntax checks passed
- git diff check was clean at the final published recovery commit

## Sponsor / partner truth

Partner integrations must never be marked REAL from configuration alone.

Boson:
- REAL requires actual provider roundtrip plus native audio.
- Browser fallback must remain labeled fallback.

InsForge:
- intended role: remote evidence/audit plane
- REAL requires remote INSERT followed by independent GET/readback
- store session/timeline/governed action evidence only after remote confirmation

InstaCloud:
- intended role: optional cloud preview/deployment layer
- .4 remains canonical local control plane
- REAL requires an actual project/deployment, public preview URL and provider health evidence

## Boson credits

Funding registry now records Boson AI Workspace credits for the same Boson Workspace used by the project.

Two separate Boson confirmation emails were received on 2026-09-18, each stating that USD 10.00 free credit was added to the workspace, for USD 20.00 total confirmed grants by email.

Important: the provider Billing page should remain the authority for current remaining balance after any usage.

The credits work across Boson APIs. Prioritize them for:
- Higgs Realtime native voice validation
- bounded VoiceOps testing
- interruption/tool-calling experiments
- post-hackathon voice integration work

Current public pricing at the time of handoff:
- Higgs Realtime audio input: approximately USD 0.0023/min
- Higgs Realtime audio output: approximately USD 0.014/min
- actual billing is token-metered

## Submission positioning

One-line description:
InnerOS VoiceOps is a real-time voice agent that turns natural conversation into governed physical actions across live infrastructure, with human approval and verifiable evidence.

Core phrase:
From conversation to governed action.

## What we learned

The principal operational failure during the hackathon was orchestration overhead, not lack of technical capability.

Future time-boxed event protocol:

1. Pick exactly one canonical runtime and one canonical branch for the demo.
2. Define the minimum demo path before adding sponsor extras.
3. Classify every item as WORKING, BLOCKED, or NOT REQUIRED FOR DEMO.
4. Do not touch a working path unless the demo requires it.
5. Run independent checks in parallel.
6. Require human input only for true human gates such as OAuth or credentials.
7. After every execution block report only DONE / BLOCKED / NEXT.
8. Never trust an agent self-report without one independent runtime or repository check.
9. Freeze a known-good snapshot before experimental integration work.
10. Preserve experimental branches instead of forcing them into the permanent product under deadline pressure.

## Post-hackathon plan

Keep both archive branches. Do not delete either line.

Next product work should:
- compare the recovery and hackathon tracks
- extract the best Higgs transport/audio work
- retain truthful provider badges
- retain governed action contracts
- complete native Boson validation
- complete InsForge remote readback
- complete InstaCloud preview proof only if it adds product value
- port selected improvements into the permanent VoiceOps product after review

No destructive merge is required to preserve the work.
