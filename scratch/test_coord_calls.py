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

# 1. Initialize
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

# Call get_coordination_live
p.stdin.write(
    json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 100,
            "method": "tools/call",
            "params": {"name": "get_coordination_live", "arguments": {}},
        }
    )
    + "\n"
)
p.stdin.flush()

# Call poll_agent_inbox with only required args
p.stdin.write(
    json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 101,
            "method": "tools/call",
            "params": {
                "name": "poll_agent_inbox",
                "arguments": {"agent": "ANTIGRAVITY"},
            },
        }
    )
    + "\n"
)
p.stdin.flush()

# Call read_coordination_file for HUB/ESTADO_VIVO.md
p.stdin.write(
    json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 102,
            "method": "tools/call",
            "params": {
                "name": "read_coordination_file",
                "arguments": {"relative_path": "HUB/ESTADO_VIVO.md"},
            },
        }
    )
    + "\n"
)
p.stdin.flush()

time.sleep(5)
p.kill()
p.communicate()

with open("scratch/coord_test_out.json", "w", encoding="utf-8") as f:
    json.dump(responses, f, indent=2, ensure_ascii=False)

print("Finished testing calls:", list(responses.keys()))
