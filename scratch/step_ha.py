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


def call_tool(req_id, name, args):
    req = {
        "jsonrpc": "2.0",
        "id": req_id,
        "method": "tools/call",
        "params": {"name": name, "arguments": args},
    }
    p.stdin.write(json.dumps(req) + "\n")
    p.stdin.flush()
    # wait for response
    for _ in range(20):
        if req_id in responses:
            break
        time.sleep(0.3)


call_tool(
    1,
    "ha_get_entity",
    {"entity_id": "alarm_control_panel.panel_home_ralphi_panel_home_ralphi"},
)
call_tool(2, "ha_get_entity", {"entity_id": "device_tracker.nvr_dahua"})
call_tool(
    3, "ha_get_entity", {"entity_id": "sensor.breaker_phase_a_voltage"}
)
call_tool(
    4,
    "ha_get_entity",
    {"entity_id": "sensor.inneros_pi01_solar_battery_capacity"},
)

time.sleep(2)
p.kill()
p.communicate()

with open("scratch/ha_step_test.json", "w", encoding="utf-8") as f:
    json.dump(responses, f, indent=2, ensure_ascii=False)

print("Responses:", list(responses.keys()))
