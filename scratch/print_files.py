import io
import json
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

with open("scratch/live_coordination_dump.json", encoding="utf-8") as f:
    data = json.load(f)

for req_id in ["20", "21", "22"]:
    print(f"\n===================== FILE {req_id} =====================")
    res = data.get(req_id, {})
    if "result" in res:
        content = res["result"].get("content", [{}])[0].get("text", "")
        try:
            parsed = json.loads(content)
            print(parsed.get("content", content))
        except Exception:
            print(content)
