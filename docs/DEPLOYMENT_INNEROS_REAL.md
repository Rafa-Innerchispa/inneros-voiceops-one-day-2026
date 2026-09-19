# VoiceOps en servidores InnerOS reales (.4 / producción)

Última revisión: 2026-09-19

## Objetivo

Mismo panel y flujo gobernado (voz → inspección → propuesta → aprobación → ejecución HA real → evidencia) corriendo **dentro de InnerOS**, no solo en laptop de demo.

## Dos repos VoiceOps (evolución, no duplicado)

| Repo | Rol | Voz | Telefonía UCM6104 | URL |
|------|-----|-----|-------------------|-----|
| `inneros-voiceops-assemblyai` | **Canónico** AssemblyAI hackathon | AssemblyAI STT/TTS | **Sí** (AMI, SIP, política Ecuador) | `voiceops.creatorcore.ai` |
| `inneros-voiceops-one-day-2026` | **Evolución** Boson hackathon | Boson Higgs S2S + fallback navegador | Hereda adapters (mismo código base) | `voiceopsboson.creatorcore.ai` / local `:8765` |

Este repo (**one-day-2026**) es la evolución con:

- telemetría LIVE desde Home Assistant (sin `math.sin` fake)
- acciones gobernadas reales vía `ha_service`
- panel **Home Assistant Controls** (selector de entidades)
- Boson Higgs Realtime como capa de voz

**No es un módulo Python instalado dentro del MCP hoy.** Corre como servicio web independiente (`voiceops-web`) que consume las mismas fuentes que InnerOS (HA, UCM, bridge `.4:8875`).

### Ruta de convergencia recomendada

1. Validar aquí el golden path LIVE (HA token + acciones + voz Boson).
2. Portar los commits de truth-retrofit + `ha_actions` + panel HA al repo canónico `inneros-voiceops-assemblyai`.
3. Un solo servicio en `.4` con perfil de voz configurable (`ASSEMBLYAI` vs `BOSON`).

## ¿Está instalado en InnerOS como módulo?

**Parcialmente hoy:**

- **Lectura** de telemetría: el runtime en `.4:8875/api/telemetry` ya expone subsistemas LIVE (solar, alarma, red, rack).
- **Ejecución** y **inventario completo HA**: requieren `HASS_TOKEN` en el host que ejecuta VoiceOps (no basta el bridge de telemetría).
- **MCP pcdoctor** en `.4` ya tiene `ha_list_entities`, `ha_call_service` — mismo Home Assistant, mismo token.

VoiceOps debe usar **el mismo token** que ya usa el MCP de InnerOS para HA.

## Cómo obtener e instalar `HASS_TOKEN` (único paso manual)

El token **no se puede inventar ni scrapear**. Se crea una vez en Home Assistant:

1. Abrir `http://192.168.1.4:8123` (usuario admin HA).
2. Perfil (abajo izquierda) → **Security** → **Long-Lived Access Tokens**.
3. **Create Token** → nombre: `inneros-voiceops` → copiar el token (solo se muestra una vez).
4. Guardar en el servidor InnerOS (`.4`), **sin commitear a git**:

```bash
# En el Intel host (.4) — ruta que VoiceOps ya lee automáticamente
mkdir -p ~/.config/inneros
nano ~/.config/inneros/voiceops.env
```

Contenido mínimo:

```env
HASS_URL=http://192.168.1.4:8123
HASS_TOKEN=PEGAR_TOKEN_AQUI

VOICEOPS_HA_ALLOW_DISCOVERED=true
VOICEOPS_TELEMETRY_BRIDGE_URL=http://127.0.0.1:8875/api/telemetry

BOSON_API_KEY=...
VOICEOPS_TELEPHONY_AMI_HOST=192.168.1.6
VOICEOPS_TELEPHONY_AMI_USERNAME=...
VOICEOPS_TELEPHONY_AMI_SECRET=...
```

VoiceOps carga este archivo al arrancar (`runtime_env.py`):

- `./.env` (desarrollo)
- `~/.config/inneros/voiceops.env` (producción InnerOS)
- `~/.inneros/voiceops.env` (alternativa)

### Verificación (en el servidor)

```bash
curl -s -H "Authorization: Bearer $HASS_TOKEN" http://192.168.1.4:8123/api/states | head
curl -s http://127.0.0.1:8765/api/ha/controls | jq '.truth, .entity_count, .controllable_count'
```

Esperado: `"LIVE"`, cientos de entidades, panel con badge LIVE.

## Servicio persistente en InnerOS (.4)

**No ejecutar en Windows PowerShell.** Los comandos van en una sesión **Linux** en el Intel host (`.4` / `ralphiia`).

Desde la laptop Windows, abrir sesión remota primero:

```powershell
ssh rlopez@192.168.1.4
# o vía Tailscale:
ssh rlopez@100.94.99.12
```

Luego en el servidor Linux:

```bash
# Si el repo ya existe, encontrar ruta real:
systemctl --user show inneros-voiceops-boson.service -p WorkingDirectory,ExecStart

# Deploy (clona si no existe, pull si ya existe):
bash -c "$(curl -fsSL https://raw.githubusercontent.com/Rafa-Innerchispa/inneros-voiceops-one-day-2026/hackathon/2026-09-18-boson-insforge/scripts/deploy_boson_14.sh)"
```

O con repo local en el servidor:

```bash
cd "$(systemctl --user show inneros-voiceops-boson.service -p WorkingDirectory --value 2>/dev/null || echo ~/inneros/inneros_core/workspaces/inneros-voiceops-one-day-2026)"
bash scripts/deploy_boson_14.sh
```

Ver plantillas: `deploy/inneros-voiceops-boson.service.example`, `deploy/voiceops.env.example`

Exponer vía Cloudflare tunnel existente (como otros servicios creatorcore.ai).

## Checklist “completamente funcional”

| Capacidad | Requisito |
|-----------|-----------|
| Telemetría LIVE | `HASS_TOKEN` o bridge `.4:8875` |
| Inventario HA completo en panel | `HASS_TOKEN` en host VoiceOps |
| Ejecutar luces / alarma / UniFi | `HASS_TOKEN` + aprobación verbal |
| Voz Boson | `BOSON_API_KEY` en `voiceops.env` |
| Telefonía UCM6104 LIVE | AMI en `.6:7777` (heredado del repo AssemblyAI) |
| Auditoría / HTR | Incluido en flujo gobernado |

## Relación con el VoiceOps de telefonía (hackathon AssemblyAI)

El repo **`inneros-voiceops-assemblyai`** es el que documenta:

- Grandstream UCM6104 (`docs/VOICEOPS_UCM6104_REMOTE_TELEPHONY_HANDOFF_2026-09-13.md`)
- política de llamadas Ecuador (`telephony_policy.py`)
- AMI read-only + SIP bridge
- Guardian event bridge + Voice Execution Permits

**Este repo contiene el mismo código de telefonía** (`grandstream_ami.py`, `live_telephony_provider.py`, etc.) y añade la capa Boson + HA actions. Es la evolución pedida ayer: mismo producto InnerOS, mejor panel, acciones reales, otra capa de voz para el hackathon Boson.

## Qué hace Rafael vs qué hace el agente

| Acción | Quién |
|--------|-------|
| Crear token en UI de Home Assistant | Rafael (1 min, una vez) |
| Pegar token en `~/.config/inneros/voiceops.env` en `.4` | Rafael o agente con acceso SSH |
| Código, panel HA, endpoints, tests | Repo (ya hecho) |
| systemd + tunnel + merge a repo canónico | Siguiente sprint ops |
