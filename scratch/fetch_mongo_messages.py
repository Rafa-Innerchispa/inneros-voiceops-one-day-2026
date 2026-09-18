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

# List messages for antigravity inbox
p.stdin.write(
    json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 30,
            "method": "tools/call",
            "params": {
                "name": "list_agent_messages",
                "arguments": {"agent": "antigravity", "role": "inbox", "limit": 10},
            },
        }
    )
    + "\n"
)
p.stdin.flush()

# List messages for chatgpt outbox / messages sent to antigravity
p.stdin.write(
    json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 31,
            "method": "tools/call",
            "params": {
                "name": "list_agent_messages",
                "arguments": {"agent": "chatgpt", "role": "inbox", "limit": 10},
            },
        }
    )
    + "\n"
)
p.stdin.flush()

# Read coordination file 00_LEER_PRIMERO.md
p.stdin.write(
    json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 32,
            "method": "tools/call",
            "params": {
                "name": "read_coordination_file",
                "arguments": {"relative_path": "00_LEER_PRIMERO.md"},
            },
        }
    )
    + "\n"
)
p.stdin.flush()

time.sleep(5)
p.kill()
p.communicate()

with open("scratch/mongo_messages_dump.json", "w", encoding="utf-8") as f:
    json.dump(responses, f, indent=2, ensure_ascii=False)

print("Fetched mongo messages.")
