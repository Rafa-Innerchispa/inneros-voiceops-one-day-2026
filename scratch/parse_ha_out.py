import io
import json
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
with open("scratch/ha_query_out.json", encoding="utf-8") as f:
    data = json.load(f)

for req_id in ["101", "102", "103", "104", "105", "106", "107"]:
    print(f"\n===================== Response {req_id} =====================")
    res = data.get(req_id, {})
    if "result" in res:
        content = res["result"].get("content", [{}])[0].get("text", "")
        try:
            parsed = json.loads(content)
            if isinstance(parsed, list):
                print(f"List with {len(parsed)} items:")
                for item in parsed[:15]:
                    print(" -", item)
            elif isinstance(parsed, dict):
                print(json.dumps(parsed, indent=2, ensure_ascii=False)[:1000])
        except Exception:
            print(content[:1000])
    elif "error" in res:
        print("ERROR:", res["error"])
