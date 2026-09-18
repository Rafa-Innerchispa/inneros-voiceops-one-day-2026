import io
import json
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

with open("scratch/live_coordination_dump.json", encoding="utf-8") as f:
    data = json.load(f)

for req_id in ["20", "21", "22", "23", "24"]:
    print(f"===================== Response {req_id} =====================")
    res = data.get(req_id, {})
    if "result" in res:
        content = res["result"].get("content", [{}])[0].get("text", "")
        try:
            parsed = json.loads(content)
            if "content" in parsed:
                print(parsed["content"])
            elif "messages" in parsed:
                for m in parsed["messages"]:
                    print(
                        f"MsgID: {m.get('message_id')} | From: {m.get('from_agent')} | Title: {m.get('title')}"
                    )
                    print(f"Body:\n{m.get('body')}\n")
            else:
                print(json.dumps(parsed, indent=2, ensure_ascii=False)[:1000])
        except Exception as e:
            print(f"Raw string:\n{content[:1500]}")
    elif "error" in res:
        print("ERROR:", res["error"])
