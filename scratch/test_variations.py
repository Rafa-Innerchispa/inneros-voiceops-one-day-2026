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

# Variations:
variations = [
    # 1. standard
    {
        "id": 10,
        "name": "tools/call",
        "params": {
            "name": "read_coordination_file",
            "arguments": {"relative_path": "HUB/ESTADO_VIVO.md"},
        },
    },
    # 2. string args
    {
        "id": 11,
        "name": "tools/call",
        "params": {
            "name": "read_coordination_file",
            "arguments": json.dumps({"relative_path": "HUB/ESTADO_VIVO.md"}),
        },
    },
    # 3. no arguments key
    {
        "id": 12,
        "name": "tools/call",
        "params": {
            "name": "read_coordination_file",
            "relative_path": "HUB/ESTADO_VIVO.md",
        },
    },
    # 4. direct call
    {
        "id": 13,
        "name": "read_coordination_file",
        "params": {"relative_path": "HUB/ESTADO_VIVO.md"},
    },
    # 5. call with get_coordination_summary
    {
        "id": 14,
        "name": "tools/call",
        "params": {
            "name": "get_coordination_summary",
            "arguments": {"limit": 5},
        },
    },
]

for v in variations:
    req = {
        "jsonrpc": "2.0",
        "id": v["id"],
        "method": v["name"],
        "params": v["params"],
    }
    p.stdin.write(json.dumps(req) + "\n")
    p.stdin.flush()
    time.sleep(0.5)

time.sleep(4)
p.kill()
p.communicate()

for req_id, resp in responses.items():
    print(f"ID {req_id}:", json.dumps(resp, ensure_ascii=False)[:300])
