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

# 2. Initialized
p.stdin.write(
    json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})
    + "\n"
)
p.stdin.flush()
time.sleep(1)

# 3. Poll ANTIGRAVITY inbox
p.stdin.write(
    json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 10,
            "method": "tools/call",
            "params": {
                "name": "poll_agent_inbox",
                "arguments": {
                    "agent": "ANTIGRAVITY",
                    "limit": 20,
                    "auto_ack": False,
                },
            },
        }
    )
    + "\n"
)
p.stdin.flush()

# 4. Poll CHATGPT inbox
p.stdin.write(
    json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 11,
            "method": "tools/call",
            "params": {
                "name": "poll_agent_inbox",
                "arguments": {
                    "agent": "CHATGPT",
                    "limit": 20,
                    "auto_ack": False,
                },
            },
        }
    )
    + "\n"
)
p.stdin.flush()

# 5. Get coordination summary
p.stdin.write(
    json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 12,
            "method": "tools/call",
            "params": {
                "name": "get_coordination_summary",
                "arguments": {"limit": 10},
            },
        }
    )
    + "\n"
)
p.stdin.flush()

time.sleep(6)
p.kill()
p.communicate()

with open("scratch/coordination_sync.json", "w", encoding="utf-8") as f:
    json.dump(responses, f, indent=2, ensure_ascii=False)

print("Sync completed.")
