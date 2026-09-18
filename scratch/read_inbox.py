import json

with open("scratch/mcp_coordination_results.json", encoding="utf-8") as f:
    data = json.load(f)

for k in ["10", "11"]:
    if k in data and "result" in data[k]:
        txt = data[k]["result"]["content"][0]["text"]
        inbox = json.loads(txt)
        msgs = inbox.get("messages", [])
        role = inbox.get("role", k)
        print(f"=== INBOX {k} ({role}) Total: {len(msgs)} ===")
        for m in msgs[:6]:
            print(
                "ID:",
                m.get("message_id"),
                "| From:",
                m.get("from_agent"),
                "| Title:",
                m.get("title"),
            )
            print("Body:", m.get("body", "")[:300])
            print("-----------------------------------------")
