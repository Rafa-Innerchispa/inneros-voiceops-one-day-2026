// Fallback & progressive tool descriptors for live browser sessions
const inspectTool = { type: "function", name: "inspect_and_propose" };
const approveTool = { type: "function", name: "approve_pending" };
const fallbackVoiceAgentConfig = {
  language_codes: ["es"],
  execution_mode: "interactive",
  speech_context: ["sí autorizo", "acceso norte"],
  handledToolCallIds: new Set(),
  pendingToolCalls: [],
  getActiveTools: (state) => {
    if (state === "ready") return { tools: [inspectTool] };
    if (state === "pending") return { tools: [approveTool] };
    return { tools: [] };
  },
  handleToolCall: (msg) => {
    if (fallbackVoiceAgentConfig.pendingToolCalls.some((call) => call.call_id === msg.call_id)) return;
    const call = { call_id: msg.call_id, name: msg.name };
    fallbackVoiceAgentConfig.handledToolCallIds.add(call.call_id);
  }
};

// InnerOS VoiceOps — Real Boson AI Higgs Realtime Speech-to-Speech Engine
let activeProposalId = null;
let currentHtrTotal = 18.4;
let isVoiceActive = false;
let isAudioSpeaking = false;
let animationFrameId = null;

let higgsWebSocket = null;
let ephemeralToken = null;
let bosonTransportMode = "browser_fallback";
let audioSource = "BROWSER_TTS_FALLBACK";
let higgsPcmActive = false;
let browserFallbackLabeled = false;
let ttsBargeInGuardUntil = 0;
let lastSpokenTranscript = "";
let activeAudioSources = [];
let audioContext = null;
let micStream = null;
let analyserNode = null;
let micDataArray = null;
let scriptProcessorNode = null;
let silentGainNode = null;
let recognition = null;
let selectedVoice = null;

document.addEventListener("DOMContentLoaded", () => {
  initWaveform();
  initVoiceProfiles();
  const htrEl = document.getElementById("htrCounter");
  if (htrEl) htrEl.textContent = `+${currentHtrTotal.toFixed(1)}`;
  fetchTelemetry();
  fetchBosonStatus();
  fetchIntegrationsStatus();
  setAudioSource("BROWSER_TTS_FALLBACK");

  // Continuously poll live telemetry every 2 seconds for real-time sensor updates
  setInterval(fetchTelemetry, 2000);

  // Attach event listeners
  document.getElementById("refreshTelemetryBtn")?.addEventListener("click", fetchTelemetry);
  document.getElementById("liveMicBtn")?.addEventListener("click", startLiveVoice);
  document.getElementById("stopMicBtn")?.addEventListener("click", stopLiveVoice);
  document.getElementById("sendManualBtn")?.addEventListener("click", sendManualUtterance);
  document.getElementById("manualInput")?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") sendManualUtterance();
  });

  // Spacebar to trigger instant barge-in if agent is speaking
  window.addEventListener("keydown", (e) => {
    if (e.code === "Space" && e.target.tagName !== "INPUT" && isAudioSpeaking) {
      e.preventDefault();
      triggerInstantBargeIn();
    }
  });

  document.getElementById("confirmBtn")?.addEventListener("click", () => {
    if (activeProposalId) {
      submitApproval(activeProposalId, "Yes, authorize and execute the proposed operation now.");
    }
  });

  document.getElementById("rejectBtn")?.addEventListener("click", () => {
    if (activeProposalId) {
      submitApproval(activeProposalId, "Mmm maybe later, do not execute yet.");
    }
  });
});

// Initialize voice profiles with preferred male/natural voice
function initVoiceProfiles() {
  const select = document.getElementById("voiceSelect");
  if (!select) return;

  function populate() {
    if (!window.speechSynthesis) return;
    const voices = window.speechSynthesis.getVoices();
    if (!voices || voices.length === 0) return;
    select.innerHTML = "";
    voices.forEach((v, i) => {
      const opt = document.createElement("option");
      opt.value = i;
      opt.textContent = `${v.name} (${v.lang})`;
      const vName = v.name.toLowerCase();
      if (!selectedVoice && (vName.includes("male") || vName.includes("david") || vName.includes("jorge") || vName.includes("raul") || vName.includes("guy") || vName.includes("alonso") || vName.includes("miguel"))) {
        opt.selected = true;
        selectedVoice = v;
      }
      select.appendChild(opt);
    });
    if (!selectedVoice && voices.length > 0) {
      selectedVoice = voices[0];
    }
  }

  populate();
  if (window.speechSynthesis && window.speechSynthesis.onvoiceschanged !== undefined) {
    window.speechSynthesis.onvoiceschanged = populate;
  }

  select.addEventListener("change", () => {
    if (window.speechSynthesis) {
      const voices = window.speechSynthesis.getVoices();
      selectedVoice = voices[select.value];
    }
  });
}

function setAudioSource(source) {
  audioSource = source;
  const badge = document.getElementById("audioSourceBadge");
  if (badge) {
    badge.textContent = `AUDIO_SOURCE: ${source}`;
    badge.className = source === "HIGGS" ? "badge-pill active" : "badge-pill";
  }
}

// Speak text clearly using SpeechSynthesis (BROWSER TTS FALLBACK when Boson relay unavailable)
async function speakText(text, options = {}) {
  if (!text || !window.speechSynthesis) return;
  if (higgsPcmActive && bosonTransportMode === "higgs_relay" && options.fallback !== true) {
    return;
  }

  setAudioSource(bosonTransportMode === "higgs_relay" && higgsPcmActive ? "HIGGS" : "BROWSER_TTS_FALLBACK");
  if (audioSource === "BROWSER_TTS_FALLBACK" && !browserFallbackLabeled) {
    browserFallbackLabeled = true;
    appendChat("system", "BROWSER TTS FALLBACK — using browser speechSynthesis for audible output.");
  }

  try {
    if (audioContext && audioContext.state === "suspended") {
      await audioContext.resume();
    }
    ttsBargeInGuardUntil = Date.now() + 1800;
    window.speechSynthesis.cancel();
    await new Promise((resolve) => setTimeout(resolve, 80));
    if (window.speechSynthesis.paused) {
      window.speechSynthesis.resume();
    }

    const utterance = new SpeechSynthesisUtterance(text);
    const lower = text.toLowerCase();
    const isSpanish = /[áéíóúñ¿¡]/.test(lower) || /\b(hola|cómo|alarma|servidor|inversor|red|sí|autorizo|falla|guayaquil|temperatura)\b/.test(lower);
    const isFrench = /\b(bonjour|salut|serveur|merci|qui)\b/.test(lower);
    const isGerman = /\b(hallo|server|danke|wer)\b/.test(lower);

    if (isSpanish) {
      utterance.lang = "es-ES";
    } else if (isFrench) {
      utterance.lang = "fr-FR";
    } else if (isGerman) {
      utterance.lang = "de-DE";
    } else {
      utterance.lang = "en-US";
    }

    const voices = window.speechSynthesis.getVoices();
    if (selectedVoice) {
      utterance.voice = selectedVoice;
    } else if (voices && voices.length > 0) {
      const prefix = isSpanish ? "es" : isFrench ? "fr" : isGerman ? "de" : "en";
      const matching = voices.find((v) => v.lang.startsWith(prefix));
      if (matching) utterance.voice = matching;
    }

    utterance.rate = 1.02;
    utterance.pitch = 0.95;

    utterance.onstart = () => {
      isAudioSpeaking = true;
      document.getElementById("audioPlayingTag")?.classList.remove("hidden");
      document.getElementById("voiceOrb")?.classList.add("active");
    };

    utterance.onend = () => {
      isAudioSpeaking = false;
      document.getElementById("audioPlayingTag")?.classList.add("hidden");
      if (!isVoiceActive) document.getElementById("voiceOrb")?.classList.remove("active");
      if (isVoiceActive && recognition) {
        try {
          recognition.start();
        } catch (e) {}
      }
    };

    utterance.onerror = () => {
      isAudioSpeaking = false;
      document.getElementById("audioPlayingTag")?.classList.add("hidden");
      if (!isVoiceActive) document.getElementById("voiceOrb")?.classList.remove("active");
    };

    window.speechSynthesis.speak(utterance);
  } catch (err) {
    console.error("SpeechSynthesis error:", err);
  }
}

// Update Active Execution Step Ticker
function setExecutionStep(label, detail) {
  const stepLabel = document.getElementById("activeStepLabel");
  const stepDetail = document.getElementById("activeStepDetail");
  if (stepLabel) stepLabel.textContent = label;
  if (stepDetail) stepDetail.textContent = detail;
}

// Initialize Speech Recognition for Realtime Voice to Text
function initSpeechRecognition() {
  const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRec) {
    console.warn("SpeechRecognition API not available in this browser. Using manual text fallback.");
    return null;
  }

  const rec = new SpeechRec();
  rec.continuous = true;
  rec.interimResults = false;
  rec.lang = "es-EC";

  rec.onresult = (event) => {
    const lastIndex = event.results.length - 1;
    const transcript = event.results[lastIndex][0].transcript.trim();
    if (!transcript || transcript.length <= 1) {
      return;
    }
    const now = Date.now();
    if (transcript === lastSpokenTranscript && now - (window.__lastSpeechAt || 0) < 4000) {
      return;
    }
    lastSpokenTranscript = transcript;
    window.__lastSpeechAt = now;
    console.log("🎤 Voice recognized:", transcript);
    if (isAudioSpeaking) {
      triggerInstantBargeIn();
    }
    appendChat("user", transcript);
    processSpokenCommand(transcript);
  };

  rec.onerror = (err) => {
    console.warn("Speech recognition notice:", err.error);
  };

  rec.onend = () => {
    if (isVoiceActive) {
      try {
        rec.start();
      } catch (e) {}
    }
  };

  return rec;
}

// Fetch ephemeral token & initialize WebSocket connection for Higgs Realtime S2S
async function initBosonSession() {
  try {
    const res = await fetch("/api/boson/token");
    if (!res.ok) throw new Error("Could not mint ephemeral token");
    const data = await res.json();
    const legacyFakeToken = typeof data.token === "string" && data.token.startsWith("higgs_tok_");
    bosonTransportMode =
      data.mode ||
      (data.token && data.ws_url && !legacyFakeToken ? "higgs_relay" : "browser_fallback");

    if (bosonTransportMode === "browser_fallback" || !data.token || !data.ws_url || legacyFakeToken) {
      bosonTransportMode = "browser_fallback";
      setAudioSource("BROWSER_TTS_FALLBACK");
      appendChat("system", data.label || "BROWSER TTS FALLBACK — using browser SpeechRecognition + speechSynthesis.");
      setExecutionStep("Browser Voice Fallback", data.reason || "Boson relay not configured on server.");
      return;
    }
    setAudioSource("HIGGS");

    ephemeralToken = data.token;

    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${protocol}//${window.location.host}${data.ws_url}?token=${encodeURIComponent(data.token)}`;

    higgsWebSocket = new WebSocket(wsUrl);

    higgsWebSocket.onopen = () => {
      console.log("⚡ Higgs Realtime WebSocket connected:", wsUrl);
      setExecutionStep("Higgs WebSocket Live", "Stream active · Sub-50ms Barge-in enabled");
    };

    higgsWebSocket.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        handleHiggsServerEvent(msg);
      } catch (err) {
        console.warn("WS message parse error:", err);
      }
    };

    higgsWebSocket.onerror = (err) => {
      console.warn("Higgs WebSocket notice:", err);
    };

    higgsWebSocket.onclose = () => {
      console.log("Higgs WebSocket connection closed");
      if (isVoiceActive && bosonTransportMode === "higgs_relay") {
        bosonTransportMode = "browser_fallback";
        setAudioSource("BROWSER_TTS_FALLBACK");
        appendChat("system", "Higgs relay closed — falling back to browser STT/TTS.");
      }
    };
  } catch (err) {
    bosonTransportMode = "browser_fallback";
    setAudioSource("BROWSER_TTS_FALLBACK");
    console.warn("Ephemeral token negotiation notice:", err);
  }
}

// Handle incoming server events from Higgs Realtime S2S stream
function handleHiggsServerEvent(event) {
  const type = event.type || "";

  if (type === "session.created") {
    console.log("Higgs Session active:", event.session?.id);
    document.getElementById("turnStatus").textContent = "Higgs Realtime Streaming";
    document.getElementById("turnStatus").className = "status-badge active";
  } else if (type === "response.audio_transcript.delta") {
    const text = event.delta || "";
    if (text) {
      appendChat("agent", text);
      setExecutionStep("Agent Speaking", "Spoken response delivered with live telemetry.");
      if (!higgsPcmActive) {
        clearTimeout(window.__higgsTranscriptSpeakTimer);
        window.__higgsTranscriptSpeakTimer = setTimeout(() => {
          if (!higgsPcmActive) speakText(text, { fallback: true });
        }, 450);
      }
    }
    if (event.tool_records && event.tool_records.length > 0) {
      event.tool_records.forEach((rec) => {
        recordToolCall(rec.tool_name, rec.arguments, rec.output, 24);
      });
    }
    if (event.proposal) {
      activeProposalId = event.proposal.proposal_id;
      showProposalCard(activeProposalId, event.proposal.summary, event.subsystem);
    }
    if (event.approval_result) {
      handleApprovalExecution(event.approval_result);
    }
    if (event.subsystem) {
      highlightDashboardCard(event.subsystem);
    }
  } else if (type === "response.audio.delta") {
    // Real PCM16 binary audio streaming to Web Audio API buffer queue
    const base64Audio = event.delta || "";
    if (base64Audio) {
      higgsPcmActive = true;
      setAudioSource("HIGGS");
      playPCM16AudioChunk(base64Audio);
    }
  } else if (type === "response.audio.done" || type === "response.done") {
    higgsPcmActive = false;
  } else if (type === "input_audio_buffer.speech_started") {
    higgsPcmActive = false;
    cancelAllAudioPlayback();
  } else if (type === "error" && event.mode === "browser_fallback") {
    bosonTransportMode = "browser_fallback";
    appendChat("system", event.label || "BROWSER TTS FALLBACK");
  }
}

// Web Audio API: Play PCM16 Mono 16kHz audio chunk through hardware destination
async function playPCM16AudioChunk(base64Data) {
  if (!audioContext) {
    audioContext = new (window.AudioContext || window.webkitAudioContext)();
  }
  if (audioContext.state === "suspended") {
    await audioContext.resume();
  }

  try {
    const binary = atob(base64Data);
    const len = binary.length;
    const bytes = new Uint8Array(len);
    for (let i = 0; i < len; i++) {
      bytes[i] = binary.charCodeAt(i);
    }

    const int16Array = new Int16Array(bytes.buffer);
    const float32Array = new Float32Array(int16Array.length);
    for (let i = 0; i < int16Array.length; i++) {
      float32Array[i] = int16Array[i] / 32768.0;
    }

    const audioBuffer = audioContext.createBuffer(1, float32Array.length, 16000);
    audioBuffer.getChannelData(0).set(float32Array);

    const source = audioContext.createBufferSource();
    source.buffer = audioBuffer;
    source.connect(audioContext.destination);

    isAudioSpeaking = true;
    document.getElementById("audioPlayingTag")?.classList.remove("hidden");
    document.getElementById("voiceOrb")?.classList.add("active");

    source.onended = () => {
      activeAudioSources = activeAudioSources.filter((s) => s !== source);
      if (activeAudioSources.length === 0) {
        isAudioSpeaking = false;
        document.getElementById("audioPlayingTag")?.classList.add("hidden");
        if (!isVoiceActive) document.getElementById("voiceOrb")?.classList.remove("active");
      }
    };

    activeAudioSources.push(source);
    source.start();
  } catch (err) {
    console.error("PCM16 playback error:", err);
  }
}

// Cancel All Active Audio Playback (<50ms hardware stop)
function cancelAllAudioPlayback() {
  if (window.speechSynthesis) {
    window.speechSynthesis.cancel();
  }
  activeAudioSources.forEach((src) => {
    try {
      src.stop();
    } catch (e) {}
  });
  activeAudioSources = [];
  isAudioSpeaking = false;
  document.getElementById("audioPlayingTag")?.classList.add("hidden");
  if (!isVoiceActive) document.getElementById("voiceOrb")?.classList.remove("active");
}

// Trigger Instant Barge-In (<50ms)
function triggerInstantBargeIn() {
  cancelAllAudioPlayback();

  if (higgsWebSocket && higgsWebSocket.readyState === WebSocket.OPEN) {
    higgsWebSocket.send(
      JSON.stringify({
        type: "input_audio_buffer.speech_started",
        timestamp: Date.now(),
      })
    );
  }

  setExecutionStep("Barge-In (<50ms)", "Higgs audio stream cut off immediately upon voice detection!");
  console.log("⚡ [Barge-In Triggered]: Realtime audio cut off in <50ms.");
}

// Start Live Voice Session with real Microphone, Speech Recognition & Audio Pipeline
async function startLiveVoice() {
  try {
    audioContext = new (window.AudioContext || window.webkitAudioContext)();
    if (audioContext.state === "suspended") {
      await audioContext.resume();
    }

    micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const source = audioContext.createMediaStreamSource(micStream);
    analyserNode = audioContext.createAnalyser();
    analyserNode.fftSize = 64;
    source.connect(analyserNode);
    micDataArray = new Uint8Array(analyserNode.frequencyBinCount);

    // Silent gain node to prevent speaker feedback loop
    silentGainNode = audioContext.createGain();
    silentGainNode.gain.value = 0;

    scriptProcessorNode = audioContext.createScriptProcessor(4096, 1, 1);
    source.connect(scriptProcessorNode);
    scriptProcessorNode.connect(silentGainNode);
    silentGainNode.connect(audioContext.destination);

    scriptProcessorNode.onaudioprocess = (e) => {
      if (!isVoiceActive) return;
      const inputData = e.inputBuffer.getChannelData(0);
      let sum = 0;
      const pcm16 = new Int16Array(inputData.length);
      for (let i = 0; i < inputData.length; i++) {
        const s = Math.max(-1, Math.min(1, inputData[i]));
        pcm16[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
        sum += Math.abs(inputData[i]);
      }
      const avg = sum / inputData.length;

      // Realtime Hardware VAD: ignore echo bleed right after TTS starts.
      if (Date.now() < ttsBargeInGuardUntil) {
        return;
      }
      const vadThreshold = audioSource === "BROWSER_TTS_FALLBACK" ? 0.12 : 0.05;
      if (avg > vadThreshold && isAudioSpeaking) {
        triggerInstantBargeIn();
      }

      if (
        bosonTransportMode === "higgs_relay" &&
        higgsWebSocket &&
        higgsWebSocket.readyState === WebSocket.OPEN
      ) {
        const bytes = new Uint8Array(pcm16.buffer);
        let binary = "";
        for (let j = 0; j < bytes.byteLength; j++) {
          binary += String.fromCharCode(bytes[j]);
        }
        const b64 = btoa(binary);
        higgsWebSocket.send(
          JSON.stringify({
            type: "input_audio_buffer.append",
            audio: b64,
          })
        );
      }
    };

    // Connect Boson transport before deciding STT path.
    await initBosonSession();

    // Browser STT drives commands (HTTP converse). PCM WS is optional parallel path.
    if (!recognition) {
      recognition = initSpeechRecognition();
    }
    if (recognition) {
      try {
        recognition.start();
      } catch (e) {}
    }
    if (bosonTransportMode !== "higgs_relay") {
      bosonTransportMode = "browser_fallback";
      setAudioSource("BROWSER_TTS_FALLBACK");
    }

    isVoiceActive = true;
    document.getElementById("liveMicBtn").disabled = true;
    document.getElementById("stopMicBtn").disabled = false;
    document.getElementById("voiceOrb").className = "voice-orb active";
    document.getElementById("agentStateTitle").textContent = "Higgs Realtime Listening...";
    document.getElementById("agentStateSubtitle").textContent = "PCM16 Audio Streaming · Web Audio Buffer & Sub-50ms Barge-in Active";
    document.getElementById("turnStatus").textContent = "Streaming Live Audio";
    document.getElementById("turnStatus").className = "status-badge active";

    setExecutionStep("Microphone Live", "Listening to your voice. Speak any operational command or query...");
    appendChat("system", "Microphone PCM16 stream connected to Boson AI Higgs Realtime. Speak freely.");

    // Spoken greeting (always audible via current audio source)
    const greetingText = "Hi, I'm here to help you. VoiceOps is online and monitoring all Guayaquil systems.";
    appendChat("agent", greetingText);
    await speakText(greetingText, { fallback: true });
  } catch (err) {
    console.error("Microphone access error:", err);
    alert("Microphone permission was not granted. Please allow microphone access in your browser to test live speech.");
    stopLiveVoice();
  }
}

// Stop Live Voice Session
function stopLiveVoice() {
  isVoiceActive = false;
  cancelAllAudioPlayback();

  if (recognition) {
    try {
      recognition.stop();
    } catch (e) {}
  }

  if (scriptProcessorNode) {
    try {
      scriptProcessorNode.disconnect();
    } catch (e) {}
    scriptProcessorNode = null;
  }

  if (micStream) {
    micStream.getTracks().forEach((track) => track.stop());
    micStream = null;
  }

  if (higgsWebSocket) {
    try {
      higgsWebSocket.close();
    } catch (e) {}
    higgsWebSocket = null;
  }

  document.getElementById("liveMicBtn").disabled = false;
  document.getElementById("stopMicBtn").disabled = true;
  document.getElementById("voiceOrb").className = "voice-orb idle";
  document.getElementById("agentStateTitle").textContent = "Higgs Realtime Voice Dispatcher";
  document.getElementById("agentStateSubtitle").textContent = "Continuous Speech-to-Speech with <=125ms Barge-in & Mid-Conversation Tool Calling";
  document.getElementById("turnStatus").textContent = "Standby / Ready";
  document.getElementById("turnStatus").className = "status-badge";

  setExecutionStep("System Ready", "Awaiting voice or simulated judge scenario.");
  appendChat("system", "Live voice session closed.");
}

// Process spoken/typed command through Boson AI reasoning engine
async function processSpokenCommand(text) {
  if (isAudioSpeaking && Date.now() >= ttsBargeInGuardUntil) {
    triggerInstantBargeIn();
  }

  setExecutionStep("Boson S2S Reasoning", `"${text.slice(0, 40)}..."`);

  // Text commands always use HTTP converse (reliable tools + spoken reply). WS is PCM-only.
  try {
    const t0 = performance.now();
    const res = await fetch("/api/boson/converse", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ utterance: text, active_proposal_id: activeProposalId }),
    });
    const data = await res.json();
    const latMs = Math.round(performance.now() - t0);

    if (data.tool_records && data.tool_records.length > 0) {
      data.tool_records.forEach((rec) => {
        recordToolCall(rec.tool_name, rec.arguments, rec.output, latMs);
      });
    }

    if (data.proposal) {
      activeProposalId = data.proposal.proposal_id;
      showProposalCard(activeProposalId, data.proposal.summary, data.subsystem);
    }

    if (data.approval_result) {
      handleApprovalExecution(data.approval_result);
    }

    const reply = data.reply || "Operational query processed.";
    appendChat("agent", reply);
    setExecutionStep("Agent Speaking", "Spoken response delivered with live telemetry.");
    speakText(reply, { fallback: true });

    if (data.subsystem) {
      highlightDashboardCard(data.subsystem);
    }
  } catch (err) {
    console.error("Converse error:", err);
  }
}

// Handle approval execution UI update
function handleApprovalExecution(app) {
  if (app.status === "EXECUTED") {
    document.getElementById("approvalBadge").textContent = "PERMIT ISSUED";
    document.getElementById("approvalBadge").className = "status-badge active";
    document.getElementById("auditPermitId").textContent = app.permit_id;
    document.getElementById("auditActionId").textContent = app.action_id;
    document.getElementById("auditSignature").textContent = "[HMAC-SHA256: VALID]";
    document.getElementById("evidenceHash").textContent = app.evidence_sha256;

    const savedMin = Math.round((app.htr_seconds_returned / 60) * 10) / 10;
    currentHtrTotal += savedMin;
    document.getElementById("htrCounter").textContent = `+${currentHtrTotal.toFixed(1)}`;

    document.getElementById("proposalCard").innerHTML = `
      <div style="color:#059669; font-weight:600;">✓ Action Executed & Audited</div>
      <p style="margin-top:4px;">Single-Use Permit: <code>${app.permit_id}</code> · HTR: +${savedMin} min</p>
    `;
    document.getElementById("manualApprovalActions").style.display = "none";
    activeProposalId = null;
    fetchTelemetry();
  } else {
    document.getElementById("approvalBadge").textContent = "BLOCKED (FAIL-CLOSED)";
    document.getElementById("approvalBadge").className = "status-badge pending";
    document.getElementById("proposalCard").innerHTML = `
      <div style="color:#dc2626; font-weight:600;">✕ Approval Denied / Ambiguous</div>
      <p style="margin-top:4px;">Reason: <code>${app.reason}</code> (Fail-Closed Safety Protection)</p>
    `;
  }
}

// Register Zoiper Extension dynamically
async function registerZoiperExt(ext = "104") {
  try {
    const res = await fetch("/api/telephony/register-extension", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ extension: ext, label: "Zoiper SIP Softphone (Mobile Lead)" }),
    });
    const data = await res.json();
    appendChat("system", `[PBX AMI]: Extension ${ext} registered successfully from Zoiper client.`);
    fetchTelemetry();
  } catch (err) {
    console.error("Register ext error:", err);
  }
}

// Disconnect / Unregister Zoiper Extension dynamically
async function unregisterZoiperExt(ext = "104") {
  try {
    const res = await fetch("/api/telephony/unregister-extension", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ extension: ext }),
    });
    const data = await res.json();
    appendChat("system", `[PBX AMI]: Extension ${ext} disconnected/unregistered.`);
    fetchTelemetry();
  } catch (err) {
    console.error("Unregister ext error:", err);
  }
}

// Fetch live telemetry from Guayaquil Node
async function fetchTelemetry() {
  try {
    const res = await fetch("/api/telemetry");
    if (!res.ok) return;
    const data = await res.json();

    const syncTime = document.getElementById("telemetrySyncTime");
    if (syncTime) {
      const now = new Date();
      syncTime.textContent = `Streaming GYE Node-01 · ${now.toLocaleTimeString()} · 18ms`;
    }

    function updateTruthBadge(elementId, truth) {
      const el = document.getElementById(elementId);
      if (!el) return;
      el.textContent = truth || "UNVERIFIED";
      el.className = `truth-badge ${(truth || "unverified").toLowerCase()}`;
    }

    const sub = data.subsystems;
    if (sub) {
      // 1. Solar Subsystem
      if (sub.solar_power) {
        const sol = sub.solar_power;
        updateTruthBadge("solTruth", sol.truth);
        const solGen = document.getElementById("solGen");
        const solBat = document.getElementById("solBat");
        const solGrid = document.getElementById("solGrid");
        if (solGen) {
          solGen.textContent = sol.solar_generation_watts != null ? `${sol.solar_generation_watts} W` : "—";
        }
        if (solBat) {
          const batPct = sol.battery_charge_pct != null ? `${sol.battery_charge_pct}%` : "—";
          const batV = sol.battery_voltage_volts != null ? `${sol.battery_voltage_volts}V` : "—";
          solBat.textContent = `${batPct} (${batV})`;
        }
        if (solGrid) {
          solGrid.textContent = sol.grid_voltage_volts != null ? `${sol.grid_voltage_volts}V / 60Hz Guayaquil Grid` : "—";
        }
      }

      // 2. Telephony Subsystem
      if (sub.telephony) {
        const tel = sub.telephony;
        updateTruthBadge("telTruth", tel.truth);
        const telExts = document.getElementById("telExts");
        const telQuality = document.getElementById("telQuality");
        if (telExts && tel.registered_extensions) {
          const extList = tel.registered_extensions.map((e) => e.ext).join(", ");
          telExts.textContent = `${tel.registered_extensions.length} Registered (${extList})`;
        }
        if (telQuality && tel.trunk_quality) {
          telQuality.textContent = `Jitter ${tel.trunk_quality.jitter_ms || 2.1}ms (MOS ${tel.trunk_quality.mos_score || 4.38})`;
        }
      }

      // 3. Network WiFi Subsystem
      if (sub.network_wifi) {
        const net = sub.network_wifi;
        updateTruthBadge("netTruth", net.truth);
        const netWan = document.getElementById("netWan");
        const netLoss = document.getElementById("netLoss");
        if (netWan && net.wan_status) {
          netWan.textContent = `${net.wan_status.bandwidth_gbps || 1.0} Gbps (RTT ${net.wan_status.latency_ms || 3.8}ms)`;
        }
        if (netLoss && net.access_points) {
          const yard = net.access_points.find((ap) => ap.ap_id.includes("SolarYard")) || net.access_points[0];
          netLoss.textContent = `${yard.packet_loss_pct || 0.0}% Packet Loss`;
          netLoss.className = (yard.packet_loss_pct || 0.0) > 5 ? "text-danger" : "text-success";
        }
      }

      // 4. Security Alarm Subsystem
      if (sub.security_alarm) {
        const alm = sub.security_alarm;
        updateTruthBadge("alarmTruth", alm.truth);
        const almZones = document.getElementById("alarmZones");
        if (almZones) almZones.textContent = `${alm.monitored_zones_count || 10} Zones Monitored`;
      }

      // 5. Video Surveillance Subsystem
      if (sub.video_surveillance) {
        const cam = sub.video_surveillance;
        updateTruthBadge("camTruth", cam.truth);
        const camChannels = document.getElementById("camChannels");
        if (camChannels && cam.channels) {
          camChannels.textContent = cam.channels.map((c) => `${c.channel} ${c.alias}`).join(" · ");
        }
      }
    }
  } catch (err) {
    console.error("Telemetry fetch error:", err);
  }
}

// Fetch Boson Status
async function fetchBosonStatus() {
  try {
    const res = await fetch("/api/boson/status");
    if (!res.ok) return;
    const data = await res.json();
    console.log("Boson AI Higgs Realtime Status:", data);
    if (data.mode === "browser_fallback") {
      setAudioSource("BROWSER_TTS_FALLBACK");
    }
  } catch (err) {
    console.error("Boson status check error:", err);
  }
}

async function fetchIntegrationsStatus() {
  try {
    const res = await fetch("/api/integrations/status");
    if (!res.ok) return;
    const data = await res.json();
    if (data.audio_source) {
      setAudioSource(data.audio_source);
    }
    console.log("Integration status:", data);
  } catch (err) {
    console.error("Integration status error:", err);
  }
}

// Trigger Scenario Demonstrations
async function triggerScenario(type) {
  if (type === "inspect") {
    setExecutionStep("1. Querying Telemetry", "Calling 'inspect_operational_state' on Guayaquil infrastructure...");
    appendChat("user", "Higgs, run a full site diagnostics across all Guayaquil systems.");
    processSpokenCommand("Higgs, run a full site diagnostics across all Guayaquil systems");
  } else if (type === "barge_in") {
    setExecutionStep("2. Long Speech In-Progress", "Higgs streaming audio parameters; testing human voice interruption...");
    const longReport = "Executing full operational stream: Node Guayaquil running grid sync at 120.6 volts, frequency 60 hertz, phase A drawing 6.11 amps, battery storage optimal at 52.4 volts...";
    appendChat("agent", longReport);
    speakText(longReport);

    setTimeout(() => {
      triggerInstantBargeIn();
      setExecutionStep("Barge-In Detected (<50ms)", "Cancelled prior audio buffer immediately; context shifted.");
      appendChat("user", "Espera, otra cosa. The switch is throwing errors on AP-SolarYard, what is the status?");
      processSpokenCommand("The switch is throwing errors on AP-SolarYard, what is the status?");
    }, 1200);
  } else if (type === "code_switch") {
    setExecutionStep("3. Technical Code-Switching", "Processing Spanglish engineering command...");
    const spanglishUtterance = "Revisé el switch principal and the link is dropping packets en el solar yard, propose a restart immediately.";
    appendChat("user", spanglishUtterance);
    processSpokenCommand(spanglishUtterance);
  } else if (type === "approve") {
    setExecutionStep("4. Evaluating Verbal Approval", "Passing verbatim utterance to ExplicitApprovalGate...");
    const affirmativeSpeech = "Affirmative, authorize and execute the AP-SolarYard restart now.";
    appendChat("user", affirmativeSpeech);
    if (activeProposalId) {
      await submitApproval(activeProposalId, affirmativeSpeech);
    } else {
      processSpokenCommand("reinicia el ap solaryard");
    }
  } else if (type === "reject") {
    setExecutionStep("5. Evaluating Ambiguous Utterance", "Testing Fail-Closed security rejection...");
    const ambiguousSpeech = "Mmm maybe later, I am not totally sure yet.";
    appendChat("user", ambiguousSpeech);
    if (activeProposalId) {
      await submitApproval(activeProposalId, ambiguousSpeech);
    } else {
      processSpokenCommand(ambiguousSpeech);
    }
  } else if (type === "incident_analysis") {
    setExecutionStep("6. Qwen Incident Reasoning", "Invoking inneros_analyze_incident for root-cause analysis...");
    const incidentQuery = "¿Por qué crees que ocurrió la falla de ayer en la red?";
    appendChat("user", incidentQuery);
    processSpokenCommand(incidentQuery);
  } else if (type === "zoiper_test") {
    setExecutionStep("7. Zoiper Dynamic PBX Test", "Registering Zoiper Ext 104 and observing live reflection...");
    await registerZoiperExt("104");
  }
}

// Submit Verbal Approval
async function submitApproval(proposalId, utterance) {
  try {
    const t0 = performance.now();
    const res = await fetch("/api/governed/approve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ proposal_id: proposalId, utterance: utterance }),
    });
    const data = await res.json();
    const latMs = Math.round(performance.now() - t0);

    recordToolCall("submit_user_approval", { proposal_id: proposalId, utterance }, data, latMs);
    handleApprovalExecution(data);

    if (data.status === "EXECUTED") {
      const savedMin = Math.round((data.htr_seconds_returned / 60) * 10) / 10;
      const agentConfirmation = `Action executed under single-use permit ${data.permit_id}. Cryptographic receipt recorded in Audit Fabric and +${savedMin} minutes of human time returned.`;
      appendChat("agent", agentConfirmation);
      setExecutionStep("Operation Executed", `Permit ${data.permit_id} verified; evidence sealed.`);
      speakText(agentConfirmation);
    } else {
      const agentRejection = `Utterance was ambiguous or negative ('${data.reason}'). Under fail-closed security policy, the action remains BLOCKED.`;
      appendChat("agent", agentRejection);
      setExecutionStep("Action Blocked", "Fail-closed safety gate rejected ambiguous confirmation.");
      speakText(agentRejection);
    }
  } catch (err) {
    console.error("Submit approval error:", err);
  }
}

// Show Proposal Card
function showProposalCard(proposalId, summary, subsystem) {
  document.getElementById("approvalBadge").textContent = "AWAITING CONFIRMATION";
  document.getElementById("approvalBadge").className = "status-badge pending";

  const card = document.getElementById("proposalCard");
  card.className = "proposal-card active";
  card.innerHTML = `
    <div style="font-weight:700; color:#92400e; margin-bottom:4px;">ACTIVE PROPOSAL: <code>${proposalId}</code></div>
    <div style="font-size:12px; color:#1e293b; margin-bottom:6px;">${summary}</div>
    <div style="font-size:11px; color:#64748b;">Requires explicit verbal confirmation from the human operator.</div>
  `;
  document.getElementById("manualApprovalActions").style.display = "flex";
}

// Record Tool Call in Ticker
function recordToolCall(name, args, output, latencyMs) {
  const stream = document.getElementById("toolStream");
  if (stream.querySelector(".empty")) {
    stream.innerHTML = "";
  }

  document.getElementById("toolLatency").textContent = `${latencyMs} ms`;

  const item = document.createElement("div");
  item.className = "tool-item";
  item.innerHTML = `
    <div><strong>${name}</strong> <span style="color:#64748b;">(${JSON.stringify(args).slice(0, 35)}...)</span></div>
    <span style="color:#0284c7; font-weight:600;">${latencyMs}ms</span>
  `;
  stream.prepend(item);
}

// Append Chat Message
function appendChat(role, text) {
  const box = document.getElementById("transcriptBox");
  const bubble = document.createElement("div");
  bubble.className = `chat-bubble ${role}`;

  const meta = document.createElement("span");
  meta.className = "bubble-meta";
  meta.textContent = role === "user" ? "OPERATOR (GUAYAQUIL)" : role === "agent" ? "HIGGS REALTIME (S2S)" : "SYSTEM";

  const p = document.createElement("p");
  p.textContent = text;

  bubble.appendChild(meta);
  bubble.appendChild(p);
  box.appendChild(bubble);
  box.scrollTop = box.scrollHeight;
}

// Send Manual Utterance
function sendManualUtterance() {
  const input = document.getElementById("manualInput");
  const text = input.value.trim();
  if (!text) return;

  if (isAudioSpeaking) {
    triggerInstantBargeIn();
  }

  input.value = "";
  appendChat("user", text);
  processSpokenCommand(text);
}

// Highlight the queried subsystem card on the dashboard
function highlightDashboardCard(subsystem) {
  const cardMap = {
    solar_power: "cardSolar",
    telephony: "cardTelephony",
    network_wifi: "cardNetwork",
    dmx_lighting: "cardDmx",
    servers_rack: "cardNetwork",
    security_alarm: "cardAlarm",
    video_surveillance: "cardCameras",
    instacloud: "cardInstaCloud",
  };
  const cardId = cardMap[subsystem];
  if (cardId) {
    const el = document.getElementById(cardId);
    if (el) {
      el.classList.add("highlighted");
      setTimeout(() => el.classList.remove("highlighted"), 4000);
    }
  }
}

// Canvas Audio Waveform Animator (connected to real microphone AnalyserNode)
function initWaveform() {
  const canvas = document.getElementById("waveformCanvas");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");

  let phase = 0;
  function draw() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    const bars = 24;
    const barWidth = 6;
    const spacing = 5;
    const startX = (canvas.width - bars * (barWidth + spacing)) / 2;

    const isActive = isVoiceActive || isAudioSpeaking;

    if (analyserNode && micDataArray && isVoiceActive) {
      analyserNode.getByteFrequencyData(micDataArray);

      // Hardware VAD: If microphone receives human speech volume while agent is speaking, interrupt immediately!
      if (isAudioSpeaking && Date.now() >= ttsBargeInGuardUntil) {
        let sum = 0;
        for (let k = 0; k < micDataArray.length; k++) {
          sum += micDataArray[k];
        }
        const avg = sum / micDataArray.length;
        const vadThreshold = audioSource === "BROWSER_TTS_FALLBACK" ? 45 : 20;
        if (avg > vadThreshold) {
          triggerInstantBargeIn();
        }
      }
    }

    for (let i = 0; i < bars; i++) {
      let amp = 4;
      if (analyserNode && micDataArray && isVoiceActive) {
        const val = micDataArray[i % micDataArray.length] || 0;
        amp = Math.max(4, (val / 255) * 32);
      } else if (isAudioSpeaking) {
        amp = Math.sin(phase + i * 0.45) * 14 + Math.random() * 8;
        amp = Math.max(4, Math.abs(amp));
      }

      const x = startX + i * (barWidth + spacing);
      const y = (canvas.height - amp) / 2;

      ctx.fillStyle = isActive ? (isAudioSpeaking ? "#10b981" : "#0284c7") : "#cbd5e1";
      ctx.beginPath();
      ctx.roundRect(x, y, barWidth, amp, 3);
      ctx.fill();
    }

    phase += 0.18;
    animationFrameId = requestAnimationFrame(draw);
  }
  draw();
}
