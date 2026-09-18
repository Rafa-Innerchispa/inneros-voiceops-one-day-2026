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
        line_clean = line.strip()
        if line_clean:
            try:
                data = json.loads(line_clean)
                req_id = data.get("id")
                if req_id is not None:
                    responses[req_id] = data
            except Exception:
                pass


t = threading.Thread(target=reader, daemon=True)
t.start()

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

# 3. Call poll_agent_inbox for ANTIGRAVITY
p.stdin.write(
    json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 10,
            "method": "tools/call",
            "params": {"name": "poll_agent_inbox", "arguments": {"agent": "ANTIGRAVITY"}},
        }
    )
    + "\n"
)
p.stdin.flush()

# 4. Call poll_agent_inbox for CHATGPT
p.stdin.write(
    json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 11,
            "method": "tools/call",
            "params": {"name": "poll_agent_inbox", "arguments": {"agent": "CHATGPT"}},
        }
    )
    + "\n"
)
p.stdin.flush()

# 5. Call search with query ops_97ea15c01e2d
p.stdin.write(
    json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 12,
            "method": "tools/call",
            "params": {
                "name": "search",
                "arguments": {"query": "ops_97ea15c01e2d"},
            },
        }
    )
    + "\n"
)
p.stdin.flush()

time.sleep(5)
p.kill()
p.communicate()

with open("scratch/mcp_coordination_results.json", "w", encoding="utf-8") as f:
    json.dump(responses, f, indent=2, ensure_ascii=False)

print(f"Done. Collected responses for IDs: {list(responses.keys())}")
