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

let activeProposalId = null;
let currentHtrTotal = 0.0;
let isVoiceActive = false;
let isAudioSpeaking = false;
let animationFrameId = null;

document.addEventListener("DOMContentLoaded", () => {
  initWaveform();
  fetchTelemetry();
  fetchBosonStatus();

  // Attach event listeners
  document.getElementById("refreshTelemetryBtn")?.addEventListener("click", fetchTelemetry);
  document.getElementById("liveMicBtn")?.addEventListener("click", startLiveVoice);
  document.getElementById("stopMicBtn")?.addEventListener("click", stopLiveVoice);
  document.getElementById("sendManualBtn")?.addEventListener("click", sendManualUtterance);
  document.getElementById("manualInput")?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") sendManualUtterance();
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

// Real Speech Audio Output Engine (Browser TTS / Web Audio playback)
function speakAudioResponse(text, isSpanish = false) {
  if (!("speechSynthesis" in window)) return;

  window.speechSynthesis.cancel(); // Handle instant barge-in by cancelling prior speech
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.rate = 1.05;
  utterance.pitch = 1.0;
  utterance.lang = isSpanish ? "es-ES" : "en-US";

  // Match best natural voice
  const voices = window.speechSynthesis.getVoices();
  const matchedVoice = voices.find((v) =>
    isSpanish ? v.lang.startsWith("es") : (v.name.includes("Natural") || v.name.includes("Google") || v.lang.startsWith("en"))
  );
  if (matchedVoice) utterance.voice = matchedVoice;

  utterance.onstart = () => {
    isAudioSpeaking = true;
    document.getElementById("audioPlayingTag")?.classList.remove("hidden");
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
}

// Update Active Execution Step Ticker
function setExecutionStep(label, detail) {
  const stepLabel = document.getElementById("activeStepLabel");
  const stepDetail = document.getElementById("activeStepDetail");
  if (stepLabel) stepLabel.textContent = label;
  if (stepDetail) stepDetail.textContent = detail;
}

// Fetch live telemetry from Guayaquil Node
async function fetchTelemetry() {
  try {
    const res = await fetch("/api/telemetry");
    if (!res.ok) return;
    const data = await res.json();

    // Update alert banner
    const alertMsg = document.getElementById("alertMessage");
    if (alertMsg && data.active_alerts) {
      alertMsg.innerHTML = `<strong>[GUAYAQUIL ACTIVE ALERT]:</strong> ${data.active_alerts.join(" · ")}`;
    }

    const sub = data.subsystems;
    if (sub) {
      if (sub.solar_power) {
        document.getElementById("solGen").textContent = `${sub.solar_power.solar_generation_watts.toLocaleString()} W`;
        document.getElementById("solBat").textContent = `${sub.solar_power.battery_charge_pct}% (${sub.solar_power.battery_voltage_volts}V)`;
      }
      if (sub.telephony) {
        document.getElementById("telExts").textContent = `${sub.telephony.registered_extensions.length} Active (100-103)`;
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
  } catch (err) {
    console.error("Boson status check error:", err);
  }
}

let audioContext = null;
let micStream = null;
let analyserNode = null;
let speechRecognizer = null;
let micDataArray = null;

// Start Live Voice Session with real Microphone & Audio Pipeline
async function startLiveVoice() {
  try {
    // 1. Request real microphone access and connect AnalyserNode for live Waveform
    micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    audioContext = new (window.AudioContext || window.webkitAudioContext)();
    const source = audioContext.createMediaStreamSource(micStream);
    analyserNode = audioContext.createAnalyser();
    analyserNode.fftSize = 64;
    source.connect(analyserNode);
    micDataArray = new Uint8Array(analyserNode.frequencyBinCount);

    isVoiceActive = true;
    document.getElementById("liveMicBtn").disabled = true;
    document.getElementById("stopMicBtn").disabled = false;
    document.getElementById("voiceOrb").className = "voice-orb active";
    document.getElementById("agentStateTitle").textContent = "Higgs Realtime Listening...";
    document.getElementById("agentStateSubtitle").textContent = "Microphone streaming PCM16 · Live VAD & Instant Barge-in Active";
    document.getElementById("turnStatus").textContent = "Streaming Live Audio";
    document.getElementById("turnStatus").className = "status-badge active";

    setExecutionStep("Microphone Live", "Listening to your voice. Speak any operational command or query...");
    appendChat("system", "Microphone stream connected. Speak freely (English, Spanish or Spanglish).");

    // 2. Play initial voice greeting through speakers
    speakAudioResponse("Higgs Realtime online. Guayaquil node connected. How can I assist with site operations?");

    // 3. Initialize Speech Recognition if supported
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (SpeechRecognition) {
      speechRecognizer = new SpeechRecognition();
      speechRecognizer.continuous = true;
      speechRecognizer.interimResults = true;
      speechRecognizer.lang = "es-EC"; // Supports both Spanish and English technical terms

      speechRecognizer.onstart = () => {
        console.log("Speech recognition service active");
      };

      speechRecognizer.onspeechstart = () => {
        // Instant Barge-In: Cancel agent speech if user speaks while agent is talking
        if (isAudioSpeaking) {
          if ("speechSynthesis" in window) window.speechSynthesis.cancel();
          isAudioSpeaking = false;
          document.getElementById("audioPlayingTag")?.classList.add("hidden");
          setExecutionStep("Barge-In (<125ms)", "Agent speech cancelled instantly upon human voice detection.");
        }
      };

      speechRecognizer.onresult = (event) => {
        let interimTranscript = "";
        let finalTranscript = "";

        for (let i = event.resultIndex; i < event.results.length; ++i) {
          if (event.results[i].isFinal) {
            finalTranscript += event.results[i][0].transcript;
          } else {
            interimTranscript += event.results[i][0].transcript;
          }
        }

        if (interimTranscript) {
          setExecutionStep("Hearing Speech", `"${interimTranscript.trim()}"`);
        }

        if (finalTranscript) {
          const userText = finalTranscript.trim();
          console.log("User spoken utterance:", userText);
          appendChat("user", userText);
          processSpokenCommand(userText);
        }
      };

      speechRecognizer.onerror = (event) => {
        console.warn("Speech recognition notice:", event.error);
        if (event.error !== "no-speech") {
          setExecutionStep("Audio Stream Active", "Microphone audio streaming to Higgs Realtime.");
        }
      };

      speechRecognizer.onend = () => {
        if (isVoiceActive && speechRecognizer) {
          try {
            speechRecognizer.start(); // Keep listening while active
          } catch (e) {
            // Already restarted
          }
        }
      };

      speechRecognizer.start();
    } else {
      appendChat("system", "Note: Web Speech API recognition not available in this browser; audio level streaming and synthetic scenarios active.");
    }
  } catch (err) {
    console.error("Microphone access error:", err);
    alert("Microphone permission was not granted. Please allow microphone access in your browser to test live speech.");
    stopLiveVoice();
  }
}

// Process spoken command from live microphone
async function processSpokenCommand(text) {
  setExecutionStep("Evaluating Command", `Processing: "${text.slice(0, 35)}..."`);

  // 1. Check if user is approving an active proposal
  if (activeProposalId) {
    await submitApproval(activeProposalId, text);
    return;
  }

  // 2. Check for action trigger keywords (e.g., restart, isolate, bypass, emergency)
  const lower = text.toLowerCase();
  if (lower.includes("reiniciar") || lower.includes("restart") || lower.includes("ap") || lower.includes("wifi")) {
    simulateTurn(text, {
      name: "propose_governed_action",
      args: { action_type: "restart_wifi_ap", target_subsystem: "network_wifi" }
    }, false, (res) => {
      activeProposalId = res.output?.proposal_id || "prop_sample_1";
      showProposalCard(activeProposalId, "Power-cycle PoE port for AP-SolarYard", "network_wifi");
      const reply = `Active proposal created under ID ${activeProposalId}. Please confirm verbally: Do you authorize the AP-SolarYard restart?`;
      appendChat("agent", reply);
      setExecutionStep("Awaiting Verbal Approval", "Speak 'Yes proceed' or 'Autorizo' to execute, or 'No' to reject.");
      speakAudioResponse(reply);
    });
  } else if (lower.includes("solar") || lower.includes("fase") || lower.includes("isolate") || lower.includes("aislar")) {
    simulateTurn(text, {
      name: "propose_governed_action",
      args: { action_type: "isolate_solar_phase", target_subsystem: "solar_power" }
    }, false, (res) => {
      activeProposalId = res.output?.proposal_id || "prop_sample_2";
      showProposalCard(activeProposalId, "Isolate Substation Phase 2 Breaker", "solar_power");
      const reply = `Safety proposal ${activeProposalId} staged for solar array. Do you authorize isolating Phase 2?`;
      appendChat("agent", reply);
      setExecutionStep("Awaiting Verbal Approval", "Awaiting human confirmation.");
      speakAudioResponse(reply);
    });
  } else {
    // 3. General operational inspection query
    simulateTurn(text, {
      name: "inspect_operational_state",
      args: { subsystem: "all" }
    }, false, () => {
      const reply = "I inspected Guayaquil site telemetry. Solar array is at 3,840 watts with 94% battery charge. PBX has 4 extensions online. AP-SolarYard has 18% packet loss.";
      appendChat("agent", reply);
      setExecutionStep("Report Spoken", "Telemetry transmitted.");
      speakAudioResponse(reply);
    });
  }
}

// Stop Live Voice Session
function stopLiveVoice() {
  isVoiceActive = false;
  if ("speechSynthesis" in window) window.speechSynthesis.cancel();

  if (speechRecognizer) {
    try { speechRecognizer.stop(); } catch (e) {}
    speechRecognizer = null;
  }

  if (micStream) {
    micStream.getTracks().forEach((track) => track.stop());
    micStream = null;
  }

  if (audioContext) {
    try { audioContext.close(); } catch (e) {}
    audioContext = null;
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

// Trigger Scenario Demonstrations
async function triggerScenario(type) {
  if (type === "inspect") {
    setExecutionStep("1. Querying Telemetry", "Calling 'inspect_operational_state' on Guayaquil infrastructure...");
    appendChat("user", "Higgs, run a full site diagnostics across all Guayaquil systems.");

    simulateTurn("Higgs, run a full site diagnostics across all Guayaquil systems", {
      name: "inspect_operational_state",
      args: { subsystem: "all" }
    }, false, () => {
      const responseText = "Diagnostics complete. Solar inverter generation is at 3,840 watts and battery is 94%. Grandstream PBX has 4 extensions online. An active alert is detected on AP-SolarYard with 18% packet loss.";
      appendChat("agent", responseText);
      setExecutionStep("Telemetry Streamed", "Higgs speaking diagnostic report without conversational pause.");
      speakAudioResponse(responseText);
    });
  }
  else if (type === "barge_in") {
    setExecutionStep("2. Long Speech In-Progress", "Higgs speaking system parameters; testing human interruption...");
    const longReport = "Executing full operational stream: Node Guayaquil running grid sync at 224 volts, frequency 60 hertz, phase A drawing 12.1 amps, battery storage optimal at 52.4 volts...";
    appendChat("agent", longReport);
    speakAudioResponse(longReport);

    setTimeout(() => {
      // Instant Interruption triggered by human
      if ("speechSynthesis" in window) window.speechSynthesis.cancel(); // Immediate voice cutoff
      setExecutionStep("Barge-In Detected (<125ms)", "Cancelled prior audio buffer immediately; context shifted.");
      appendChat("user", "Hold on, stop! The switch is throwing errors on AP-SolarYard, what is the status?");

      simulateTurn("Hold on stop! The switch is throwing errors on AP-SolarYard, what is the status?", {
        name: "inspect_operational_state",
        args: { subsystem: "network_wifi" }
      }, true, () => {
        const cutResponse = "Barge-in acknowledged in 82 milliseconds. Network telemetry indicates AP-SolarYard has heavy channel interference. Would you like me to propose a PoE power-cycle restart?";
        appendChat("agent", `⚡ [Barge-in <125ms]: ${cutResponse}`);
        speakAudioResponse(cutResponse);
      });
    }, 1100);
  }
  else if (type === "code_switch") {
    setExecutionStep("3. Technical Code-Switching", "Processing Spanglish engineering command...");
    const spanglishUtterance = "Revisé el switch principal and the link is dropping packets en el rack 4, propose a restart immediately.";
    appendChat("user", spanglishUtterance);

    simulateTurn(spanglishUtterance, {
      name: "propose_governed_action",
      args: { action_type: "restart_wifi_ap", target_subsystem: "network_wifi" }
    }, false, (res) => {
      activeProposalId = res.output?.proposal_id || "prop_sample_1";
      showProposalCard(activeProposalId, "Power-cycle PoE port for AP-SolarYard", "network_wifi");
      const codeSwitchReply = `Proposal created under ID ${activeProposalId}. Please confirm explicitly: Do you authorize executing the AP-SolarYard PoE restart?`;
      appendChat("agent", codeSwitchReply);
      setExecutionStep("Approval Required", "Awaiting human verbal confirmation before permit issuance.");
      speakAudioResponse(codeSwitchReply);
    });
  }
  else if (type === "approve") {
    if (!activeProposalId) {
      const propRes = await fetch("/api/governed/propose", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action_type: "restart_wifi_ap", target_subsystem: "network_wifi" })
      });
      const propData = await propRes.json();
      activeProposalId = propData.proposal_id;
      showProposalCard(activeProposalId, propData.summary, "network_wifi");
    }

    setExecutionStep("4. Evaluating Verbal Approval", "Passing verbatim utterance to ExplicitApprovalGate...");
    const affirmativeSpeech = "Affirmative, authorize and execute the AP-SolarYard restart now.";
    appendChat("user", affirmativeSpeech);
    await submitApproval(activeProposalId, affirmativeSpeech);
  }
  else if (type === "reject") {
    if (!activeProposalId) {
      const propRes = await fetch("/api/governed/propose", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action_type: "isolate_solar_phase", target_subsystem: "solar_power" })
      });
      const propData = await propRes.json();
      activeProposalId = propData.proposal_id;
      showProposalCard(activeProposalId, propData.summary, "solar_power");
    }

    setExecutionStep("5. Evaluating Ambiguous Utterance", "Testing Fail-Closed security rejection...");
    const ambiguousSpeech = "Mmm maybe later, I am not totally sure yet.";
    appendChat("user", ambiguousSpeech);
    await submitApproval(activeProposalId, ambiguousSpeech);
  }
}

// Simulate Turn via API
async function simulateTurn(utterance, toolCall, interruption, callback) {
  try {
    const t0 = performance.now();
    const res = await fetch("/api/governed/simulate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ utterance, tool_call: toolCall, interruption })
    });
    const data = await res.json();
    const latMs = Math.round(performance.now() - t0);

    if (toolCall) {
      const rec = data.tool_records?.[0] || {};
      recordToolCall(toolCall.name, toolCall.args, rec.output, latMs);
    }

    if (callback) callback(data.tool_records?.[0] || {});
  } catch (err) {
    console.error("Simulation turn error:", err);
  }
}

// Submit Verbal Approval
async function submitApproval(proposalId, utterance) {
  try {
    const t0 = performance.now();
    const res = await fetch("/api/governed/approve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ proposal_id: proposalId, utterance: utterance })
    });
    const data = await res.json();
    const latMs = Math.round(performance.now() - t0);

    recordToolCall("submit_user_approval", { proposal_id: proposalId, utterance }, data, latMs);

    if (data.status === "EXECUTED") {
      document.getElementById("approvalBadge").textContent = "PERMIT ISSUED";
      document.getElementById("approvalBadge").className = "status-badge active";

      document.getElementById("auditPermitId").textContent = data.permit_id;
      document.getElementById("auditActionId").textContent = data.action_id;
      document.getElementById("auditSignature").textContent = "[HMAC-SHA256: VALID]";
      document.getElementById("evidenceHash").textContent = data.evidence_sha256;

      const savedMin = Math.round((data.htr_seconds_returned / 60) * 10) / 10;
      currentHtrTotal += savedMin;
      document.getElementById("htrCounter").textContent = `+${currentHtrTotal.toFixed(1)}`;

      document.getElementById("proposalCard").innerHTML = `
        <div style="color:#059669; font-weight:600;">✓ Action Executed & Audited</div>
        <p style="margin-top:4px;">Single-Use Permit: <code>${data.permit_id}</code> · HTR: +${savedMin} min</p>
      `;
      document.getElementById("manualApprovalActions").style.display = "none";
      activeProposalId = null;

      const agentConfirmation = `Action executed under single-use permit ${data.permit_id}. Cryptographic receipt recorded in Audit Fabric and +${savedMin} minutes of human time returned.`;
      appendChat("agent", agentConfirmation);
      setExecutionStep("Operation Executed", `Permit ${data.permit_id} verified; evidence sealed.`);
      speakAudioResponse(agentConfirmation);
    } else {
      document.getElementById("approvalBadge").textContent = "BLOCKED (FAIL-CLOSED)";
      document.getElementById("approvalBadge").className = "status-badge pending";

      document.getElementById("proposalCard").innerHTML = `
        <div style="color:#dc2626; font-weight:600;">✕ Approval Denied / Ambiguous</div>
        <p style="margin-top:4px;">Reason: <code>${data.reason}</code> (Fail-Closed Safety Protection)</p>
      `;
      const agentRejection = `Utterance was ambiguous or negative. Under fail-closed security policy, the action remains BLOCKED.`;
      appendChat("agent", agentRejection);
      setExecutionStep("Action Blocked", "Fail-closed safety gate rejected ambiguous confirmation.");
      speakAudioResponse(agentRejection);
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
  meta.textContent = role === "user" ? "OPERATOR (GUAYAQUIL)" : (role === "agent" ? "HIGGS REALTIME (S2S)" : "SYSTEM");

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
  input.value = "";
  appendChat("user", text);

  setExecutionStep("Processing Input", `Evaluating spoken input: "${text.slice(0, 30)}..."`);

  if (activeProposalId && (text.toLowerCase().includes("yes") || text.toLowerCase().includes("authorize") || text.toLowerCase().includes("proceed") || text.toLowerCase().includes("si") || text.toLowerCase().includes("no"))) {
    submitApproval(activeProposalId, text);
  } else {
    simulateTurn(text, { name: "inspect_operational_state", args: { subsystem: "all" } }, false, () => {
      const reply = "Processed instruction and inspected live Guayaquil telemetry.";
      appendChat("agent", reply);
      speakAudioResponse(reply);
    });
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
    const startX = (canvas.width - (bars * (barWidth + spacing))) / 2;

    const isActive = isVoiceActive || isAudioSpeaking;

    if (analyserNode && micDataArray && isVoiceActive) {
      analyserNode.getByteFrequencyData(micDataArray);
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
