import io
import json
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
with open("scratch/mongo_messages_dump.json", encoding="utf-8") as f:
    data = json.load(f)

for req_id in ["30", "31", "32"]:
    print(f"\n===================== Response {req_id} =====================")
    res = data.get(req_id, {})
    if "result" in res:
        content = res["result"].get("content", [{}])[0].get("text", "")
        try:
            parsed = json.loads(content)
            if isinstance(parsed, list):
                for m in parsed:
                    print(
                        f"MsgID: {m.get('message_id')} | From: {m.get('from_agent')} -> To: {m.get('target_agent')} | Title: {m.get('title')}"
                    )
                    print("Body:\n" + str(m.get("body", ""))[:1500])
                    print("-" * 50)
            elif isinstance(parsed, dict) and "messages" in parsed:
                for m in parsed["messages"]:
                    print(
                        f"MsgID: {m.get('message_id')} | From: {m.get('from_agent')} -> To: {m.get('target_agent')} | Title: {m.get('title')}"
                    )
                    print("Body:\n" + str(m.get("body", ""))[:1500])
                    print("-" * 50)
            else:
                print(str(parsed)[:2000])
        except Exception:
            print(content[:2000])
