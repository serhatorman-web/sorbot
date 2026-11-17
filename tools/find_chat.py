import json, os, urllib.request
tok = os.environ["TELEGRAM_TOKEN"]
d = json.load(urllib.request.urlopen(f"https://api.telegram.org/bot{tok}/getUpdates?allowed_updates=%5B%22channel_post%22,%22my_chat_member%22,%22message%22%5D", timeout=30))
seen = {}
for u in d.get("result", []):
    for k in ("channel_post", "my_chat_member", "message"):
        if k in u:
            c = u[k]["chat"]; seen[c["id"]] = (c.get("type"), c.get("title"))
main = os.environ.get("TELEGRAM_CHAT_ID", "")
for cid, (t, title) in seen.items():
    print("CHAT", cid, t, title, "(MEVCUT)" if str(cid) == main else "")
print("ok", d.get("ok"), len(d.get("result", [])))
