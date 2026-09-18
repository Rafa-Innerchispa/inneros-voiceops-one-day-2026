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
      submitApproval(activeProposalId, "Si, autorizo la operacion ahora mismo.");
    }
  });

  document.getElementById("rejectBtn")?.addEventListener("click", () => {
    if (activeProposalId) {
      submitApproval(activeProposalId, "Mmm tal vez luego, no estoy seguro.");
    }
  });
});

// Fetch live telemetry from Guayaquil Node
async function fetchTelemetry() {
  try {
    const res = await fetch("/api/telemetry");
    if (!res.ok) return;
    const data = await res.json();

    // Update alert banner
    const alertMsg = document.getElementById("alertMessage");
    if (alertMsg && data.active_alerts) {
      alertMsg.innerHTML = `<strong>[GUAYAQUIL ALERT]:</strong> ${data.active_alerts.join(" Â· ")}`;
    }

    const sub = data.subsystems;
    if (sub) {
      if (sub.solar_power) {
        document.getElementById("solGen").textContent = `${sub.solar_power.solar_generation_watts.toLocaleString()} W`;
        document.getElementById("solBat").textContent = `${sub.solar_power.battery_charge_pct}% (${sub.solar_power.battery_voltage_volts}V)`;
      }
      if (sub.telephony) {
        document.getElementById("telExts").textContent = `${sub.telephony.registered_extensions.length} Activas (100-103)`;
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

// Start Live Voice Session
function startLiveVoice() {
  isVoiceActive = true;
  document.getElementById("liveMicBtn").disabled = true;
  document.getElementById("stopMicBtn").disabled = false;
  document.getElementById("voiceOrb").className = "voice-orb active";
  document.getElementById("agentStateTitle").textContent = "Higgs Realtime Escuchando...";
  document.getElementById("agentStateSubtitle").textContent = "MicrÃ³fono abierto Â· Streaming PCM16 mono Â· InterrupciÃ³n activa";
  document.getElementById("turnStatus").textContent = "MicrÃ³fono Transmitiendo";
  document.getElementById("turnStatus").className = "status-badge active";

  appendChat("user", "ðŸŽ¤ [MicrÃ³fono iniciado]: Transmitiendo audio PCM16 hacia Higgs Realtime S2S...");
}

// Stop Live Voice Session
function stopLiveVoice() {
  isVoiceActive = false;
  document.getElementById("liveMicBtn").disabled = false;
  document.getElementById("stopMicBtn").disabled = true;
  document.getElementById("voiceOrb").className = "voice-orb idle";
  document.getElementById("agentStateTitle").textContent = "Higgs Realtime Despachador";
  document.getElementById("agentStateSubtitle").textContent = "Listo para recibir Ã³rdenes o telemetrÃ­a en EspaÃ±ol / InglÃ©s / Spanglish";
  document.getElementById("turnStatus").textContent = "Turno en Espera";
  document.getElementById("turnStatus").className = "status-badge";

  appendChat("system", "SesiÃ³n de voz detenida.");
}

// Trigger Scenario Demonstrations
async function triggerScenario(type) {
  const box = document.getElementById("transcriptBox");

  if (type === "inspect") {
    appendChat("user", "Higgs, haz un diagnÃ³stico completo de todo el sitio Guayaquil.");
    simulateTurn("Higgs, haz un diagnÃ³stico completo de todo el sitio Guayaquil", {
      name: "inspect_operational_state",
      args: { subsystem: "all" }
    }, false, (res) => {
      appendChat("agent", "He inspeccionado todos los subsistemas de Guayaquil. El inversor solar estÃ¡ al 94% de baterÃ­a y el PBX Grandstream tiene 4 extensiones operativas. Se detectÃ³ degradaciÃ³n con 18% de packet loss en el punto de acceso AP-SolarYard.");
    });
  }
  else if (type === "barge_in") {
    appendChat("agent", "Iniciando lectura del reporte exhaustivo de telemetrÃ­a: Nodo Guayaquil operando bajo norma ecuatoriana, voltaje de red en 224 voltios, fase A con 12.1 amperios...");
    setTimeout(() => {
      appendChat("user", "ðŸ›‘ Â¡Espera corta ahÃ­! El switch estÃ¡ tirando alertas, dame el estado del AP.");
      simulateTurn("Â¡Espera corta ahÃ­! El switch estÃ¡ tirando alertas, dame el estado del AP", {
        name: "inspect_operational_state",
        args: { subsystem: "network_wifi" }
      }, true, (res) => {
        appendChat("agent", "âš¡ [Barge-in <125ms]: Audio anterior cancelado inmediatamente. Estado de red: AP-SolarYard presenta alta interferencia. Â¿Deseas que proponga un reinicio gobernado del puerto PoE?");
      });
    }, 900);
  }
  else if (type === "code_switch") {
    appendChat("user", "RevisÃ© el switch principal and the link is dropping packets en el rack 4, propose a restart immediately.");
    simulateTurn("RevisÃ© el switch principal and the link is dropping packets en el rack 4, propose a restart immediately.", {
      name: "propose_governed_action",
      args: { action_type: "restart_wifi_ap", target_subsystem: "network_wifi" }
    }, false, (res) => {
      activeProposalId = res.output?.proposal_id || "prop_sample_1";
      showProposalCard(activeProposalId, "Reiniciar puerto PoE del AP-SolarYard", "network_wifi");
      appendChat("agent", "Propuesta generada con ID " + activeProposalId + ". He aislado la recomendaciÃ³n. Por favor confirma explÃ­citamente: Â¿Autorizas ejecutar el reinicio del AP-SolarYard?");
    });
  }
  else if (type === "approve") {
    if (!activeProposalId) {
      // Auto create proposal first
      const propRes = await fetch("/api/governed/propose", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action_type: "restart_wifi_ap", target_subsystem: "network_wifi" })
      });
      const propData = await propRes.json();
      activeProposalId = propData.proposal_id;
      showProposalCard(activeProposalId, propData.summary, "network_wifi");
    }

    appendChat("user", "Afirmativo, autorizo reiniciar el AP-SolarYard ahora mismo.");
    await submitApproval(activeProposalId, "Afirmativo, autorizo reiniciar el AP-SolarYard ahora mismo.");
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

    appendChat("user", "Mmm tal vez luego, no estoy seguro todavÃ­a.");
    await submitApproval(activeProposalId, "Mmm tal vez luego, no estoy seguro todavÃ­a.");
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
      document.getElementById("approvalBadge").textContent = "PERMISO EMITIDO";
      document.getElementById("approvalBadge").className = "status-badge active";

      document.getElementById("auditPermitId").textContent = data.permit_id;
      document.getElementById("auditActionId").textContent = data.action_id;
      document.getElementById("auditSignature").textContent = "[HMAC-SHA256: VALID]";
      document.getElementById("evidenceHash").textContent = data.evidence_sha256;

      const savedMin = Math.round((data.htr_seconds_returned / 60) * 10) / 10;
      currentHtrTotal += savedMin;
      document.getElementById("htrCounter").textContent = `+${currentHtrTotal.toFixed(1)}`;

      document.getElementById("proposalCard").innerHTML = `
        <div style="color:#059669; font-weight:600;">âœ“ AcciÃ³n Ejecutada y Auditada</div>
        <p style="margin-top:4px;">Permiso: <code>${data.permit_id}</code> Â· HTR: +${savedMin} min</p>
      `;
      document.getElementById("manualApprovalActions").style.display = "none";
      activeProposalId = null;

      appendChat("agent", `AcciÃ³n ejecutada bajo permiso de un solo uso ${data.permit_id}. Evidencia criptogrÃ¡fica sellada en Audit Fabric y +${savedMin} minutos de tiempo devueltos.`);
    } else {
      document.getElementById("approvalBadge").textContent = "BLOQUEADO (FAIL-CLOSED)";
      document.getElementById("approvalBadge").className = "status-badge pending";

      document.getElementById("proposalCard").innerHTML = `
        <div style="color:#dc2626; font-weight:600;">âœ• AprobaciÃ³n Denegada / Ambigua</div>
        <p style="margin-top:4px;">Motivo: <code>${data.reason}</code> (Bloqueo de seguridad preventivo)</p>
      `;
      appendChat("agent", `La frase '${utterance}' no constituye una aprobaciÃ³n afirmativa inequÃ­voca. Por polÃ­tica de seguridad fail-closed, la acciÃ³n permanece BLOQUEADA.`);
    }
  } catch (err) {
    console.error("Submit approval error:", err);
  }
}

// Show Proposal Card
function showProposalCard(proposalId, summary, subsystem) {
  document.getElementById("approvalBadge").textContent = "ESPERANDO CONFIRMACIÃ“N";
  document.getElementById("approvalBadge").className = "status-badge pending";

  const card = document.getElementById("proposalCard");
  card.className = "proposal-card active";
  card.innerHTML = `
    <div style="font-weight:700; color:#92400e; margin-bottom:4px;">PROPUESTA ACTIVA: <code>${proposalId}</code></div>
    <div style="font-size:12px; color:#1e293b; margin-bottom:6px;">${summary}</div>
    <div style="font-size:11px; color:#64748b;">Requiere confirmaciÃ³n verbal explÃ­cita del operador humano.</div>
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
  meta.textContent = role === "user" ? "OPERADOR (GUAYAQUIL)" : (role === "agent" ? "HIGGS REALTIME (S2S)" : "SISTEMA");

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

  // Parse if it looks like an approval or general query
  if (activeProposalId && (text.toLowerCase().includes("si") || text.toLowerCase().includes("autorizo") || text.toLowerCase().includes("yes") || text.toLowerCase().includes("no"))) {
    submitApproval(activeProposalId, text);
  } else {
    simulateTurn(text, { name: "inspect_operational_state", args: { subsystem: "all" } }, false, () => {
      appendChat("agent", "He procesado tu comando e inspeccionado la telemetrÃ­a correspondiente en Guayaquil.");
    });
  }
}

// Simple Canvas Audio Waveform Animator
function initWaveform() {
  const canvas = document.getElementById("waveformCanvas");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");

  let phase = 0;
  function draw() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    const bars = 28;
    const barWidth = 6;
    const spacing = 6;
    const startX = (canvas.width - (bars * (barWidth + spacing))) / 2;

    for (let i = 0; i < bars; i++) {
      let amp = isVoiceActive ? Math.sin(phase + i * 0.4) * 16 + Math.random() * 10 : 4;
      amp = Math.max(3, Math.abs(amp));

      const x = startX + i * (barWidth + spacing);
      const y = (canvas.height - amp) / 2;

      ctx.fillStyle = isVoiceActive ? "#0284c7" : "#cbd5e1";
      ctx.beginPath();
      ctx.roundRect(x, y, barWidth, amp, 3);
      ctx.fill();
    }

    phase += 0.15;
    animationFrameId = requestAnimationFrame(draw);
  }
  draw();
}
