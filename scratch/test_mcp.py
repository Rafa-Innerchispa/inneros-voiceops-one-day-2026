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

received_messages = []


def reader():
    for line in p.stdout:
        line_clean = line.strip()
        if line_clean:
            print("RECV:", line_clean[:100])
            received_messages.append(line_clean)


t = threading.Thread(target=reader, daemon=True)
t.start()

# 1. Initialize
init_req = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "antigravity-ide", "version": "1.0.0"},
    },
}
p.stdin.write(json.dumps(init_req) + "\n")
p.stdin.flush()
time.sleep(2)

# 2. Initialized notification
init_notif = {"jsonrpc": "2.0", "method": "notifications/initialized"}
p.stdin.write(json.dumps(init_notif) + "\n")
p.stdin.flush()
time.sleep(1)

# 3. List tools
tools_req = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
p.stdin.write(json.dumps(tools_req) + "\n")
p.stdin.flush()
time.sleep(3)

p.kill()
stdout_rest, stderr = p.communicate()

with open("scratch/mcp_full_dump.json", "w", encoding="utf-8") as f:
    json.dump(received_messages, f, indent=2)

print(f"Done. Collected {len(received_messages)} messages.")
