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

calls = [
    (
        20,
        "read_coordination_file",
        {"relative_path": "HUB/ESTADO_VIVO.md", "max_chars": 12000},
    ),
    (
        21,
        "read_coordination_file",
        {"relative_path": "chatgpt/INBOX.md", "max_chars": 12000},
    ),
    (
        22,
        "read_coordination_file",
        {"relative_path": "antigravity/INBOX.md", "max_chars": 12000},
    ),
    (
        23,
        "poll_agent_inbox",
        {"agent": "ANTIGRAVITY", "limit": 10, "auto_ack": False},
    ),
    (
        24,
        "poll_agent_inbox",
        {"agent": "CHATGPT", "limit": 10, "auto_ack": False},
    ),
]

for req_id, name, args in calls:
    req = {
        "jsonrpc": "2.0",
        "id": req_id,
        "method": "tools/call",
        "params": {"name": name, "arguments": args},
    }
    p.stdin.write(json.dumps(req) + "\n")
    p.stdin.flush()
    time.sleep(0.5)

time.sleep(4)
p.kill()
p.communicate()

with open("scratch/live_coordination_dump.json", "w", encoding="utf-8") as f:
    json.dump(responses, f, indent=2, ensure_ascii=False)

print("Fetched all files and inboxes.")
