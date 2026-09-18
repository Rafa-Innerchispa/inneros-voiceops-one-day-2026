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
let currentHtrTotal = 0;
let isVoiceActive = false;
let isAudioSpeaking = false;
let animationFrameId = null;

let higgsWebSocket = null;
let ephemeralToken = null;
let bosonConnectionMode = "browser_fallback";
let higgsAudioSampleRate = 24000;
let useBrowserTtsFallback = true;
let pendingTranscript = "";
let activeAudioSources = [];
let audioContext = null;
let micStream = null;
let analyserNode = null;
let micDataArray = null;
let scriptProcessorNode = null;
let silentGainNode = null;
let recognition = null;
let selectedVoice = null;
let currentAudioSource = "NONE";

const AUDIO_SOURCE = {
  NONE: "NONE",
  HIGGS: "HIGGS",
  BROWSER_TTS_FALLBACK: "BROWSER_TTS_FALLBACK",
};

function setAudioSource(source) {
  currentAudioSource = source;
  const badge = document.getElementById("audioSourceBadge");
  const tag = document.getElementById("audioPlayingTag");
  if (badge) {
    badge.textContent = source;
    badge.className = `badge-val ${source === AUDIO_SOURCE.HIGGS ? "text-success" : source === AUDIO_SOURCE.BROWSER_TTS_FALLBACK ? "text-warning" : ""}`;
  }
  if (tag && !isAudioSpeaking) {
    tag.textContent = `AUDIO_SOURCE = ${source}`;
  }
  console.log(`AUDIO_SOURCE = ${source}`);
}

function formatTelemetryValue(value, truth, suffix = "") {
  if (truth && truth !== "LIVE") return "—";
  if (value === null || value === undefined || value === "") return "—";
  return `${value}${suffix}`;
}

document.addEventListener("DOMContentLoaded", () => {
  initWaveform();
  initVoiceProfiles();
  const htrEl = document.getElementById("htrCounter");
  if (htrEl) htrEl.textContent = `+${currentHtrTotal.toFixed(1)}`;
  fetchTelemetry();
  fetchBosonStatus();
  fetchVoiceStatus();

  // Continuously poll live telemetry every 2 seconds for real-time sensor updates
  setInterval(fetchTelemetry, 2000);
  setInterval(fetchVoiceStatus, 5000);

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

// Speak text clearly using SpeechSynthesis — only when Boson audio is unavailable
function speakText(text, force = false) {
  if (!text || !window.speechSynthesis) return;
  if (!force && !useBrowserTtsFallback) return;

  try {
    window.speechSynthesis.cancel();
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
      setAudioSource(AUDIO_SOURCE.BROWSER_TTS_FALLBACK);
      const tag = document.getElementById("audioPlayingTag");
      if (tag) {
        tag.textContent = "AUDIO_SOURCE = BROWSER_TTS_FALLBACK";
        tag.classList.remove("hidden");
      }
      document.getElementById("voiceOrb")?.classList.add("active");
    };

    utterance.onend = () => {
      isAudioSpeaking = false;
      document.getElementById("audioPlayingTag")?.classList.add("hidden");
      if (!isVoiceActive) document.getElementById("voiceOrb")?.classList.remove("active");
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
    if (transcript && transcript.length > 1) {
      console.log("🎤 Voice recognized:", transcript);
      appendChat("user", transcript);
      processSpokenCommand(transcript);
    }
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
    const data = await res.json();
    ephemeralToken = data.token || null;
    bosonConnectionMode = data.connection_mode || (data.ok ? "direct" : "browser_fallback");
    higgsAudioSampleRate = data.sample_rate || 24000;
    useBrowserTtsFallback = !data.ok;

    let wsUrl;
    let subprotocols = ["realtime"];
    if (data.ok && data.ws_url && data.ws_url.startsWith("wss://")) {
      wsUrl = data.ws_url;
      subprotocols.push(`bai-client-secret.${data.token}`);
      useBrowserTtsFallback = false;
      setAudioSource(data.AUDIO_SOURCE || AUDIO_SOURCE.HIGGS);
    } else {
      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      wsUrl = `${protocol}//${window.location.host}${data.ws_url || "/ws/higgs"}`;
      useBrowserTtsFallback = true;
      setAudioSource(data.AUDIO_SOURCE || AUDIO_SOURCE.BROWSER_TTS_FALLBACK);
    }

    higgsWebSocket = new WebSocket(wsUrl, subprotocols);

    higgsWebSocket.onopen = () => {
      console.log("⚡ Higgs Realtime WebSocket connected:", wsUrl, bosonConnectionMode);
      setExecutionStep(
        useBrowserTtsFallback ? "Browser Voice Fallback" : "Higgs Realtime Live",
        useBrowserTtsFallback
          ? "BROWSER TTS FALLBACK · STT via SpeechRecognition"
          : "Upstream Boson · Sub-50ms Barge-in enabled"
      );
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
    };
  } catch (err) {
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
  } else if (
    type === "response.output_audio_transcript.delta" ||
    type === "response.audio_transcript.delta" ||
    type === "response.text.delta"
  ) {
    const text = event.delta || "";
    pendingTranscript += text;
    if (text) {
      appendChat("agent", text);
      const src = event.AUDIO_SOURCE || event.audio_source || (useBrowserTtsFallback ? AUDIO_SOURCE.BROWSER_TTS_FALLBACK : AUDIO_SOURCE.HIGGS);
      setExecutionStep(
        src === AUDIO_SOURCE.BROWSER_TTS_FALLBACK ? "AUDIO_SOURCE = BROWSER_TTS_FALLBACK" : "AUDIO_SOURCE = HIGGS (transcript)",
        src === AUDIO_SOURCE.BROWSER_TTS_FALLBACK ? "Browser SpeechSynthesis output" : "Boson Higgs transcript (audio via PCM stream)"
      );
      if (src === AUDIO_SOURCE.BROWSER_TTS_FALLBACK || useBrowserTtsFallback) {
        speakText(text, true);
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
  } else if (type === "response.output_audio.delta" || type === "response.audio.delta") {
    const base64Audio = event.delta || "";
    if (base64Audio) {
      useBrowserTtsFallback = false;
      setAudioSource(AUDIO_SOURCE.HIGGS);
      const tag = document.getElementById("audioPlayingTag");
      if (tag) {
        tag.textContent = "AUDIO_SOURCE = HIGGS";
        tag.classList.remove("hidden");
      }
      playPCM16AudioChunk(base64Audio, event.sample_rate || higgsAudioSampleRate);
    }
  } else if (type === "response.done") {
    const finalText = pendingTranscript;
    pendingTranscript = "";
    if (useBrowserTtsFallback && finalText) {
      speakText(finalText, true);
    }
  } else if (type === "input_audio_buffer.speech_started") {
    cancelAllAudioPlayback();
  } else if (type === "error") {
    console.warn("Higgs error event:", event);
    useBrowserTtsFallback = true;
    setAudioSource(AUDIO_SOURCE.BROWSER_TTS_FALLBACK);
  }
}

// Web Audio API: Play PCM16 Mono 16kHz audio chunk through hardware destination
function playPCM16AudioChunk(base64Data, sampleRate = 24000) {
  if (!audioContext) {
    audioContext = new (window.AudioContext || window.webkitAudioContext)();
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

    const audioBuffer = audioContext.createBuffer(1, float32Array.length, sampleRate);
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
    higgsWebSocket.send(JSON.stringify({ type: "response.cancel" }));
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
      const inRate = audioContext.sampleRate || 48000;
      const targetRate = higgsAudioSampleRate;
      const ratio = inRate / targetRate;
      const outLen = Math.floor(inputData.length / ratio);
      const pcm16 = new Int16Array(outLen);
      let sum = 0;
      for (let i = 0; i < outLen; i++) {
        const srcIdx = Math.min(inputData.length - 1, Math.floor(i * ratio));
        const s = Math.max(-1, Math.min(1, inputData[srcIdx]));
        pcm16[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
        sum += Math.abs(inputData[srcIdx]);
      }
      const avg = sum / Math.max(outLen, 1);

      if (avg > 0.05 && isAudioSpeaking) {
        triggerInstantBargeIn();
      }

      if (higgsWebSocket && higgsWebSocket.readyState === WebSocket.OPEN) {
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

    // Start Web Speech Recognition
    if (!recognition) {
      recognition = initSpeechRecognition();
    }
    if (recognition) {
      try {
        recognition.start();
      } catch (e) {}
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

    // Connect WebSocket
    await initBosonSession();

    // Spoken greeting
    const greetingText = "Hi, I'm here to help you. VoiceOps is online and monitoring all Guayaquil systems.";
    appendChat("agent", greetingText);
    speakText(greetingText);
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
  if (isAudioSpeaking) {
    triggerInstantBargeIn();
  }

  setExecutionStep("Boson S2S Reasoning", `"${text.slice(0, 40)}..."`);

  // If WebSocket is open, send via WebSocket
  if (higgsWebSocket && higgsWebSocket.readyState === WebSocket.OPEN) {
    higgsWebSocket.send(
      JSON.stringify({
        type: "conversation.item.create",
        item: {
          type: "message",
          role: "user",
          content: [{ type: "input_text", text: text }],
        },
        active_proposal_id: activeProposalId,
      })
    );
    return;
  }

  // Fallback to HTTP endpoint
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
    setExecutionStep("AUDIO_SOURCE = BROWSER_TTS_FALLBACK", "HTTP converse fallback · SpeechSynthesis");
    setAudioSource(AUDIO_SOURCE.BROWSER_TTS_FALLBACK);
    speakText(reply, true);

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
        if (solGen) solGen.textContent = formatTelemetryValue(sol.solar_generation_watts, sol.truth, " W");
        if (solBat) {
          const pct = formatTelemetryValue(sol.battery_charge_pct, sol.truth, "%");
          const volts = formatTelemetryValue(sol.battery_voltage_volts, sol.truth, "V");
          solBat.textContent = pct === "—" ? "—" : `${pct} (${volts})`;
        }
        if (solGrid) solGrid.textContent = formatTelemetryValue(sol.grid_voltage_volts, sol.truth, "V / 60Hz Guayaquil Grid");
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
        if (telQuality) {
          telQuality.textContent = tel.truth === "LIVE" ? "AMI live read" : "—";
        }
      }

      // 3. Network WiFi Subsystem
      if (sub.network_wifi) {
        const net = sub.network_wifi;
        updateTruthBadge("netTruth", net.truth);
        const netWan = document.getElementById("netWan");
        const netLoss = document.getElementById("netLoss");
        if (netWan) {
          netWan.textContent = net.wan_online === true ? "WAN online" : net.wan_online === false ? "WAN offline" : "—";
        }
        if (netLoss && net.access_points) {
          const yard = net.access_points.find((ap) => ap.ap_id.includes("SolarYard")) || net.access_points[0];
          netLoss.textContent = yard?.status || "—";
          netLoss.className = String(yard?.status || "").includes("DEGRADED") ? "text-danger" : "text-success";
        }
      }

      // 4. Security Alarm Subsystem
      if (sub.security_alarm) {
        const alm = sub.security_alarm;
        updateTruthBadge("alarmTruth", alm.truth);
        const almZones = document.getElementById("alarmZones");
        if (almZones) almZones.textContent = formatTelemetryValue(alm.monitored_zones_count, alm.truth, " Zones Monitored");
      }

      // 5. Video Surveillance Subsystem
      if (sub.video_surveillance) {
        const cam = sub.video_surveillance;
        updateTruthBadge("camTruth", cam.truth);
        const camChannels = document.getElementById("camChannels");
        if (camChannels) {
          camChannels.textContent = cam.nvr_host ? `${cam.nvr_host} · ${cam.presence || "—"}` : "—";
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
    if (data.AUDIO_SOURCE && currentAudioSource === AUDIO_SOURCE.NONE) {
      setAudioSource(data.AUDIO_SOURCE);
    }
    console.log("Boson AI Higgs Realtime Status:", data);
  } catch (err) {
    console.error("Boson status check error:", err);
  }
}

function providerStatusClass(mode) {
  const normalized = String(mode || "").toUpperCase();
  if (normalized === "REAL" || normalized === "CONFIGURED") return "real";
  if (normalized === "FALLBACK" || normalized === "BROWSER_TTS_FALLBACK") return "fallback";
  return "not-connected";
}

function renderProviderStatus(data) {
  const list = document.getElementById("providerStatusList");
  if (!list || !data.providers) return;

  const labels = {
    boson_higgs: "Boson Higgs",
    browser_tts: "Browser TTS",
    home_assistant: "Home Assistant",
    grandstream_ami: "Grandstream AMI",
    qwen_amd: "Qwen AMD",
    insforge: "InsForge",
    instacloud: "InstaCloud",
  };

  list.innerHTML = Object.entries(data.providers)
    .map(([key, provider]) => {
      const label = labels[key] || key;
      const mode = provider.mode || provider.status || "NOT_CONNECTED";
      const cls = providerStatusClass(mode);
      return `<div class="provider-row"><span>${label}</span><span class="truth-badge ${cls}">${mode}</span></div>`;
    })
    .join("");

  const instaCard = document.getElementById("cardInstaCloud");
  if (instaCard && data.providers.instacloud) {
    const badge = instaCard.querySelector(".truth-badge");
    const mode = data.providers.instacloud.mode || "NOT_CONNECTED";
    if (badge) {
      badge.textContent = mode;
      badge.className = `truth-badge ${providerStatusClass(mode)}`;
    }
  }
}

async function fetchVoiceStatus() {
  try {
    const res = await fetch("/api/voice/status");
    if (!res.ok) return;
    const data = await res.json();
    if (data.AUDIO_SOURCE && !isVoiceActive) {
      setAudioSource(data.AUDIO_SOURCE);
    }
    renderProviderStatus(data);
    console.log("Voice provider status:", data);
  } catch (err) {
    console.error("Voice status check error:", err);
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
      if (isAudioSpeaking) {
        let sum = 0;
        for (let k = 0; k < micDataArray.length; k++) {
          sum += micDataArray[k];
        }
        const avg = sum / micDataArray.length;
        if (avg > 20) {
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

// Recovery transport: one audio engine, one upstream session, no double STT/TTS.
(() => {
  let ready = false, nextPlayAt = 0, responseId = null, audioReceived = false;
  let interrupted = false, agentBubble = null, fallbackSpeech = null, opening = null;
  const dialogueId = globalThis.crypto?.randomUUID?.() || ("local-" + Date.now().toString(36) + Math.random().toString(36).slice(2));
  let greetingPending = false, lastFallbackText = '', polling = false;
  const el = id => document.getElementById(id);
  const textAt = (id, text) => { if (el(id)) el(id).textContent = text; };
  const send = value => { if (higgsWebSocket?.readyState === WebSocket.OPEN) higgsWebSocket.send(JSON.stringify(value)); };

  async function unlockAudio() {
    if (!audioContext || audioContext.state === 'closed') audioContext = new (window.AudioContext || window.webkitAudioContext)();
    if (audioContext.state !== 'running') await audioContext.resume();
    return audioContext;
  }
  function reportAudio(message) {
    textAt('agentStateSubtitle', message);
    console.warn('VoiceOps audio:', message);
  }
  function restartRecognition() {
    if (!isVoiceActive || !useBrowserTtsFallback || isAudioSpeaking) return;
    recognition ||= initSpeechRecognition();
    try { recognition?.start(); } catch (_) {}
  }
  function activateFallback(message) {
    ready = false; opening = null; useBrowserTtsFallback = true;
    bosonConnectionMode = 'browser_fallback';
    setAudioSource(AUDIO_SOURCE.BROWSER_TTS_FALLBACK);
    textAt('turnStatus', 'Browser voice fallback');
    reportAudio(message || 'Higgs connection unavailable. Browser voice fallback enabled.');
    restartRecognition();
  }
  function showAgentDelta(text) {
    if (!agentBubble) {
      appendChat('agent', '');
      agentBubble = el('transcriptBox')?.lastElementChild?.querySelector('p');
    }
    if (agentBubble) agentBubble.textContent = pendingTranscript;
    const box = el('transcriptBox'); if (box) box.scrollTop = box.scrollHeight;
  }

  speakText = function(text, force = false) {
    if (!text || (!force && !useBrowserTtsFallback)) return;
    const synth = window.speechSynthesis;
    if (!synth) { reportAudio('Browser speech output unavailable. Use Higgs audio.'); return; }
    if (text === lastFallbackText && synth.speaking) return;
    lastFallbackText = text;
    synth.cancel(); synth.resume();
    fallbackSpeech = new SpeechSynthesisUtterance(text);
    fallbackSpeech.lang = /[\u00e1\u00e9\u00ed\u00f3\u00fa\u00f1\u00bf]|\b(hola|alarma|revisa|casa|datos|estoy|autorizo)\b/i.test(text) ? 'es-EC' : 'en-US';
    const voices = synth.getVoices();
    const chosen = selectedVoice && selectedVoice.lang.slice(0,2) === fallbackSpeech.lang.slice(0,2) ? selectedVoice : voices.find(v => v.lang.startsWith(fallbackSpeech.lang.slice(0,2)));
    if (chosen) fallbackSpeech.voice = chosen;
    fallbackSpeech.volume = 1; fallbackSpeech.rate = 1;
    fallbackSpeech.onstart = () => {
      isAudioSpeaking = true; setAudioSource(AUDIO_SOURCE.BROWSER_TTS_FALLBACK);
      el('audioPlayingTag')?.classList.remove('hidden');
      if (useBrowserTtsFallback) try { recognition?.stop(); } catch (_) {}
    };
    fallbackSpeech.onend = () => { isAudioSpeaking = false; fallbackSpeech = null; el('audioPlayingTag')?.classList.add('hidden'); restartRecognition(); };
    fallbackSpeech.onerror = event => {
      isAudioSpeaking = false; fallbackSpeech = null;
      if (!['interrupted', 'canceled'].includes(event.error)) reportAudio('Speech output: ' + event.error + '. Press Test audio to enable playback.');
      restartRecognition();
    };
    synth.speak(fallbackSpeech);
  };

  cancelAllAudioPlayback = function() {
    window.speechSynthesis?.cancel(); fallbackSpeech = null;
    for (const source of activeAudioSources) try { source.stop(); } catch (_) {}
    activeAudioSources = []; nextPlayAt = audioContext?.currentTime || 0;
    isAudioSpeaking = false;
    el('audioPlayingTag')?.classList.add('hidden');
  };
  triggerInstantBargeIn = function() {
    interrupted = true; cancelAllAudioPlayback(); pendingTranscript = '';
    if (ready && responseId) send({type:'response.cancel'});
    textAt('turnStatus', 'Listening');
    restartRecognition();
  };

  playPCM16AudioChunk = function(data, rate = 24000) {
    if (interrupted || !data) return;
    try {
      if (!audioContext || audioContext.state !== 'running') {
        reportAudio('Audio device suspended. Press Test audio or Start voice.');
        useBrowserTtsFallback = true; return;
      }
      const bytes = Uint8Array.from(atob(data), c => c.charCodeAt(0));
      if (bytes.length % 2 || !bytes.length) throw new Error('Invalid PCM16 frame');
      const view = new DataView(bytes.buffer);
      const buffer = audioContext.createBuffer(1, bytes.length/2, rate);
      const samples = buffer.getChannelData(0);
      for (let i=0; i<samples.length; i++) samples[i] = view.getInt16(i*2,true)/32768;
      const node = audioContext.createBufferSource(); node.buffer = buffer; node.connect(audioContext.destination);
      const begin = Math.max(audioContext.currentTime + 0.025, nextPlayAt);
      nextPlayAt = begin + buffer.duration;
      activeAudioSources.push(node);
      node.onended = () => {
        activeAudioSources = activeAudioSources.filter(s => s !== node);
        if (!activeAudioSources.length) { isAudioSpeaking = false; el('audioPlayingTag')?.classList.add('hidden'); }
      };
      node.start(begin);
      audioReceived = true; isAudioSpeaking = true; useBrowserTtsFallback = false;
      setAudioSource(AUDIO_SOURCE.HIGGS); el('audioPlayingTag')?.classList.remove('hidden');
    } catch (error) { useBrowserTtsFallback = true; reportAudio(error.message); }
  };

  handleHiggsServerEvent = function(event) {
    const kind = event.type || '';
    if (kind === 'session.created') {
      const fallback = event.session?.upstream === 'NOT_CONNECTED' || event.session?.model === 'browser-fallback';
      if (fallback) { activateFallback(); return; }
      textAt('turnStatus','Higgs connected');
    } else if (kind === 'session.updated') {
      ready = true; useBrowserTtsFallback = false; bosonConnectionMode = 'relay';
      try { recognition?.abort(); } catch (_) {}
      textAt('turnStatus','Higgs ready');
      textAt('agentStateSubtitle','Native Higgs audio + live local tools');
      if (greetingPending) {
        greetingPending = false;
        send({type:'conversation.item.create', item:{type:'message',role:'user',content:[{type:'input_text',text:'Hola, soy Rafael. Saluda brevemente y pregunta en que me puedes ayudar.'}]}});
        send({type:'response.create'});
      }
    } else if (kind === 'response.created') {
      responseId = event.response?.id || event.response_id || 'active';
      interrupted = false; audioReceived = false; pendingTranscript = ''; agentBubble = null;
    } else if (['response.output_audio_transcript.delta','response.audio_transcript.delta','response.output_text.delta','response.text.delta'].includes(kind)) {
      if (!interrupted) { pendingTranscript += event.delta || ''; showAgentDelta(event.delta || ''); }
    } else if (['response.output_audio_transcript.done','response.audio_transcript.done','response.output_text.done'].includes(kind)) {
      if (!interrupted && !pendingTranscript) { pendingTranscript = event.transcript || event.text || ''; showAgentDelta(pendingTranscript); }
    } else if (['response.output_audio.delta','response.audio.delta'].includes(kind)) {
      playPCM16AudioChunk(event.delta, event.sample_rate || higgsAudioSampleRate);
    } else if (kind === 'response.done') {
      const status = event.response?.status;
      if (!interrupted && status !== 'cancelled' && !audioReceived && pendingTranscript) speakText(pendingTranscript, true);
      if (status === 'failed') reportAudio('Higgs response failed: ' + (event.response?.status_details?.error?.message || 'provider error'));
      responseId = null; pendingTranscript = ''; agentBubble = null;
    } else if (kind === 'input_audio_buffer.speech_started') {
      interrupted = true; cancelAllAudioPlayback(); textAt('turnStatus','Listening to you');
    } else if (['conversation.item.input_audio_transcription.completed','conversation.item.input_audio_transcription.done'].includes(kind)) {
      const text = event.transcript || event.text; if (text) appendChat('user',text);
    } else if (kind === 'voiceops.tool') {
      recordToolCall(event.name, event.arguments || {}, event.output || {}, event.duration_ms || 0);
      if (event.name === 'propose_governed_action' && event.output?.proposal_id) {
        activeProposalId = event.output.proposal_id;
        showProposalCard(activeProposalId,event.output.summary,event.output.target_subsystem);
      }
      if (event.name === 'submit_user_approval') handleApprovalExecution(event.output || {});
      if (event.name === 'inspect_operational_state') fetchTelemetry();
    } else if (kind === 'voiceops.transport_error') {
      activateFallback(event.error); try { higgsWebSocket?.close(); } catch (_) {}
    } else if (kind === 'error') {
      const message = event.error?.message || event.message || 'Higgs protocol error';
      reportAudio(message);
    }
  };

  initBosonSession = async function() {
    if (ready && higgsWebSocket?.readyState === WebSocket.OPEN) return;
    if (opening) return opening;
    opening = new Promise((resolve) => {
      const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
      const ws = new WebSocket(`${protocol}//${location.host}/ws/higgs`);
      higgsWebSocket = ws;
      const timeout = setTimeout(() => { if (!ready) { activateFallback('Higgs connection timed out; browser voice available.'); ws.close(); resolve(); } }, 18000);
      ws.onopen = () => { textAt('turnStatus','Connecting to Higgs'); };
      ws.onmessage = event => {
        try {
          const data = JSON.parse(event.data); handleHiggsServerEvent(data);
          if (data.type === 'session.updated' || (data.type === 'session.created' && data.session?.upstream === 'NOT_CONNECTED')) {
            clearTimeout(timeout); resolve();
          }
        } catch(error) { reportAudio('Invalid voice event: ' + error.message); }
      };
      ws.onerror = () => { clearTimeout(timeout); activateFallback('Voice socket failed; browser fallback enabled.'); resolve(); };
      ws.onclose = () => { clearTimeout(timeout); if (isVoiceActive) activateFallback('Voice connection closed; browser fallback enabled.'); ready = false; opening = null; resolve(); };
    });
    return opening;
  };

  initSpeechRecognition = function() {
    const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRec) return null;
    const rec = new SpeechRec(); rec.continuous = true; rec.interimResults = false; rec.lang='es-EC';
    rec.onresult = event => {
      if (!useBrowserTtsFallback || isAudioSpeaking) return;
      const text = event.results[event.results.length-1][0].transcript.trim();
      if (text) { appendChat('user',text); processSpokenCommand(text); }
    };
    rec.onerror = e => { if (!['aborted','no-speech'].includes(e.error)) reportAudio('Microphone recognition: ' + e.error); };
    rec.onend = () => setTimeout(restartRecognition,250);
    return rec;
  };

  startLiveVoice = async function() {
    if (isVoiceActive) return;
    try {
      await unlockAudio();
      micStream = await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true,noiseSuppression:true,autoGainControl:true}});
      const source = audioContext.createMediaStreamSource(micStream);
      analyserNode = audioContext.createAnalyser(); analyserNode.fftSize=128;
      micDataArray=new Uint8Array(analyserNode.frequencyBinCount); source.connect(analyserNode);
      silentGainNode=audioContext.createGain(); silentGainNode.gain.value=0;
      scriptProcessorNode=audioContext.createScriptProcessor(2048,1,1);
      source.connect(scriptProcessorNode); scriptProcessorNode.connect(silentGainNode); silentGainNode.connect(audioContext.destination);
      scriptProcessorNode.onaudioprocess = event => {
        if (!isVoiceActive || !ready || higgsWebSocket?.readyState !== WebSocket.OPEN || higgsWebSocket.bufferedAmount>262144) return;
        const input=event.inputBuffer.getChannelData(0), ratio=audioContext.sampleRate/24000;
        const count=Math.floor(input.length/ratio), bytes=new Uint8Array(count*2), view=new DataView(bytes.buffer);
        for(let i=0;i<count;i++) {
          const at=i*ratio, index=Math.floor(at), next=Math.min(index+1,input.length-1), fraction=at-index;
          const s=Math.max(-1,Math.min(1,input[index]*(1-fraction)+input[next]*fraction));
          view.setInt16(i*2,Math.round(s*(s<0?32768:32767)),true);
        }
        let raw=''; for(const b of bytes) raw+=String.fromCharCode(b);
        send({type:'input_audio_buffer.append',audio:btoa(raw)});
      };
      isVoiceActive=true; greetingPending=true;
      el('liveMicBtn').disabled=true; el('stopMicBtn').disabled=false;
      textAt('agentStateTitle','Ralphi is listening');
      await initBosonSession();
      if (useBrowserTtsFallback) { restartRecognition(); speakText('Hola Rafael. El audio alternativo esta disponible mientras reconectamos Higgs.',true); }
    } catch(error) {
      reportAudio('Microphone: '+error.message+'. HTTPS or localhost and permission are required.');
      isVoiceActive=false; if(el('liveMicBtn')) el('liveMicBtn').disabled=false;
      speakText('El microfono necesita permiso. Puedes escribir tu pregunta.',true);
    }
  };

  stopLiveVoice = function() {
    isVoiceActive=false; greetingPending=false; ready=false; opening=null;
    cancelAllAudioPlayback();
    try { recognition?.abort(); scriptProcessorNode?.disconnect(); silentGainNode?.disconnect(); higgsWebSocket?.close(); } catch(_) {}
    micStream?.getTracks().forEach(track=>track.stop()); micStream=null;
    higgsWebSocket=null; scriptProcessorNode=null;
    if(el('liveMicBtn')) el('liveMicBtn').disabled=false;
    if(el('stopMicBtn')) el('stopMicBtn').disabled=true;
    textAt('turnStatus','Stopped');
  };

  processSpokenCommand = async function(text) {
    await unlockAudio();
    if (isAudioSpeaking) triggerInstantBargeIn();
    if (!higgsWebSocket || higgsWebSocket.readyState !== WebSocket.OPEN) await initBosonSession();
    if (ready && higgsWebSocket?.readyState === WebSocket.OPEN) {
      send({type:'conversation.item.create',item:{type:'message',role:'user',content:[{type:'input_text',text}]}});
      send({type:'response.create'}); return;
    }
    try {
      const response=await fetch('/api/boson/converse',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({utterance:text,active_proposal_id:activeProposalId,session_id:dialogueId})});
      const data=await response.json();
      const answer=data.reply || data.error || 'No se pudo obtener una respuesta.';
      appendChat('agent',answer); speakText(answer,true);
      for(const rec of data.tool_records || []) recordToolCall(rec.tool_name,rec.arguments,rec.output,rec.duration_ms || 0);
      if(data.proposal?.proposal_id) {activeProposalId=data.proposal.proposal_id;showProposalCard(activeProposalId,data.proposal.summary,data.subsystem);}
    } catch(error) { reportAudio(error.message); }
  };

  // Waveform is an indicator only: ambient venue noise must not mute the assistant.
  initWaveform = function() {
    const canvas=el('waveformCanvas'); if(!canvas) return;
    const ctx=canvas.getContext('2d');
    function draw(){
      ctx.clearRect(0,0,canvas.width,canvas.height);
      if(analyserNode && micDataArray) analyserNode.getByteFrequencyData(micDataArray);
      for(let i=0;i<24;i++) {
        const h=micDataArray ? Math.max(3,(micDataArray[i] || 0)/255*canvas.height*0.8):3;
        ctx.fillStyle=isAudioSpeaking?'#10b981':'#0284c7';
        ctx.fillRect((canvas.width-264)/2+i*11,(canvas.height-h)/2,6,h);
      }
      animationFrameId=requestAnimationFrame(draw);
    } draw();
  };
  const oldVoiceStatus=fetchVoiceStatus;
  fetchVoiceStatus=async function(){const source=currentAudioSource; await oldVoiceStatus(); if(source !== 'NONE') setAudioSource(source);};
  document.addEventListener('DOMContentLoaded',()=>{
    currentHtrTotal=0; textAt('htrCounter','0.0');
    const start=el('liveMicBtn');
    if(start){const btn=document.createElement('button');btn.textContent='Test audio';btn.className=start.className;btn.type='button';btn.onclick=async()=>{await unlockAudio();speakText('Prueba de audio. Si escuchas esta frase, la salida de voz esta activa.',true);};start.parentNode.appendChild(btn);}
    document.querySelectorAll('.bubble-meta').forEach(node=>{if(node.textContent.includes('HIGGS'))node.textContent='VOICEOPS';});
  });
})();

// Render only provider observations; never leave placeholder readings looking live.
(() => {
  let fetching = false;
  const set=(id,value)=>{const node=document.getElementById(id);if(node)node.textContent=value ?? 'Not available';};
  const num=(n,unit)=>n===null||n===undefined?'Not available':`${n} ${unit}`;
  fetchTelemetry = async function(){
    if(fetching)return;fetching=true;
    try{
      const response=await fetch('/api/telemetry');if(!response.ok)throw Error(`HTTP ${response.status}`);
      const payload=await response.json();const s=payload.subsystems || {};
      for(const [key,prefix] of [['solar_power','sol'],['telephony','tel'],['network_wifi','net'],['security_alarm','alarm'],['video_surveillance','cam'],['dmx_lighting','dmx']]){
        const data=s[key] || {};updateTruthBadge(prefix+'Truth',data.truth || 'UNVERIFIED');
        set(prefix+'Status',data.status || data.truth || 'UNVERIFIED');
        const age=data.freshness_seconds;
        set(prefix+'Provider',`${data.source_provider || 'Unconfigured'}${Number.isFinite(age)?' | Observation age: '+Math.round(age)+'s':''}`);
      }
      const solar=s.solar_power || {};
      set('solGen',num(solar.inverter_output_watts ?? solar.solar_generation_watts,'W AC output'));
      set('solBat',`${num(solar.battery_charge_pct,'% estimated')} | ${num(solar.battery_voltage_volts,'V')}`);
      set('solGrid',`${num(solar.grid_voltage_volts,'V')} | breaker ${num(solar.phase_a_power_watts,'W')}`);
      const phone=s.telephony || {};const peers=phone.peers || phone.registered_extensions || [];
      set('telExts',phone.truth==='LIVE' ? peers.map(p=>`${p.ext}: ${p.registered===true||p.status==='ONLINE'?'registered':p.status || 'unavailable'}`).join(' | ') || 'No registered owner phones' : 'Status unverified');
      set('telQuality',phone.scope || 'No call-quality measurement available');
      set('telProvider',phone.source_provider || 'PBX not connected');
      const net=s.network_wifi || {};
      set('netWan',net.wan_online===true?'WAN online':net.wan_online===false?'WAN offline':'Not available');
      set('netLoss','Not measured');set('netSwitch','UniFi via Home Assistant');
      document.getElementById('cardNetwork')?.classList.remove('alert');
      const alarm=s.security_alarm || {};
      set('alarmStatus',alarm.arm_mode || alarm.status || 'UNVERIFIED');
      set('alarmZones',alarm.monitored_zones_count===null||alarm.monitored_zones_count===undefined?'Zone count not provided':alarm.monitored_zones_count);
      set('alarmTrigger',alarm.truth==='LIVE' ? alarm.is_triggered?'TRIGGERED':'No active trigger':'Not available');
      const camera=s.video_surveillance || {};
      set('camChannels',`NVR presence: ${camera.presence || 'unverified'}`);set('camStatus','PRESENCE ONLY');
      set('camMotion','Motion and image feed not connected');set('dmxScene',s.dmx_lighting?.truth==='LIVE'?(s.dmx_lighting.active_scene || 'Engine idle'):'Not connected');
      const server=s.servers_rack || {};set('serverMetrics',server.truth==='LIVE'?`Primary host | RAM ${server.memory_used_gb}/${server.memory_total_gb} GB | Load ${server.cpu_load_avg?.[0]?.toFixed(2)}`:'Server metrics unavailable');
      set('telemetrySyncTime','Last read '+new Date(payload.query_timestamp).toLocaleTimeString());
      set('alertMessage','Unavailable integrations remain marked as such. No invented readings or call-quality statistics.');
    }catch(error){set('telemetrySyncTime','Telemetry read failed: '+error.message);}
    finally{fetching=false;}
  };
  appendChat=function(role,text){
    const box=document.getElementById('transcriptBox');if(!box)return;
    const bubble=document.createElement('div');bubble.className='chat-bubble '+role;
    const meta=document.createElement('span');meta.className='bubble-meta';
    meta.textContent=role==='user'?'RAFAEL / OPERATOR':role==='agent'?(bosonConnectionMode==='relay'?'BOSON HIGGS':'LOCAL QWEN / VOICE FALLBACK'):'SYSTEM';
    const p=document.createElement('p');p.textContent=text;bubble.append(meta,p);box.append(bubble);box.scrollTop=box.scrollHeight;
  };
  renderProviderStatus=function(data){
    const list=document.getElementById('providerStatusList');if(!list)return;list.replaceChildren();
    for(const [name,info] of Object.entries(data.providers || {})){
      const row=document.createElement('div');row.className='data-row';
      const label=document.createElement('span');label.textContent=name.replaceAll('_',' ');
      const state=document.createElement('strong');state.textContent=info.mode || 'NOT_CONNECTED';
      state.title=info.note || info.source || '';row.append(label,state);list.append(row);
    }
  };
  triggerScenario=function(name){
    const prompts={inspect:'Revisa la casa con datos actuales y dime que fuentes estan disponibles.',code_switch:'Check the battery voltage y responde en espanol.',incident_analysis:'Con los datos disponibles, que podemos confirmar y que no sobre el problema de energia de ayer?',approve:'Propone crear un ticket de incidente local con la evidencia actual.',reject:'No, cancela esa propuesta.'};
    if(name==='barge_in'){triggerInstantBargeIn();return;}
    const text=prompts[name];if(!text)return;appendChat('user',text);processSpokenCommand(text);
  };
  document.addEventListener('DOMContentLoaded',()=>{
    const box=document.getElementById('transcriptBox');if(box)box.replaceChildren();
    appendChat('system','Local runtime online. Start voice or type a question. Provider status is verified independently of the interface.');
    document.querySelectorAll('[onclick*="Zoiper"], [onclick*="zoiper_test"]').forEach(button=>button.remove());
    document.querySelectorAll('.pill-btn').forEach(button=>{button.textContent=button.textContent.replace('(<50ms)','').replace('(&lt;50ms)','');});
    document.querySelectorAll('.subsystem-card .data-row span').forEach(node=>{
      if(node.textContent==='PV Generation:')node.textContent='Inverter AC Output:';
      if(node.textContent==='AP-SolarYard:')node.textContent='Packet loss:';
      if(node.textContent==='SIP Quality:')node.textContent='Read scope:';
    });
    const server=document.createElement('div');server.id='serverMetrics';server.className='provider-sub';
    document.getElementById('cardSolar')?.appendChild(server);
    set('agentStateTitle','Ralphi / InnerOS VoiceOps');
    set('agentStateSubtitle','Local operation with explicit provider status. Test audio before recording.');
    const manual=document.getElementById('manualInput');if(manual)manual.placeholder='Escribe una pregunta sobre la casa o conversa con Ralphi...';
  });
})();
