import json

with open("scratch/coordination_sync.json", encoding="utf-8") as f:
    data = json.load(f)

for k in ["10", "11"]:
    res = data.get(k, {}).get("result", {})
    if "content" in res:
        txt = res["content"][0]["text"]
        try:
            obj = json.loads(txt)
            msgs = obj.get("messages", [])
            print(f"=== INBOX {k} ({obj.get('agent', k)}) Count: {len(msgs)} ===")
            for m in msgs:
                print(
                    f"MsgID: {m.get('message_id')} | From: {m.get('from_agent')} | Title: {m.get('title')}"
                )
                print(f"Body:\n{m.get('body', '')}")
                print("-" * 50)
        except Exception as e:
            print(f"Error parsing json in {k}: {e}\nRaw text: {txt[:500]}")

summary_res = data.get("12", {}).get("result", {})
if "content" in summary_res:
    print("=== COORDINATION SUMMARY ===")
    print(summary_res["content"][0]["text"])
