"""Botun gördüğü kanalları listeler (geçici). Token yazdırılmaz."""
import json, os, urllib.request
tok = os.environ["TELEGRAM_TOKEN"]
r = json.load(urllib.request.urlopen(f"https://api.telegram.org/bot{tok}/getUpdates?allowed_updates=%5B%22channel_post%22%2C%22my_chat_member%22%2C%22message%22%5D", timeout=30))
seen = {}
for u in r.get("result", []):
    for k in ("channel_post", "message", "my_chat_member"):
        ch = (u.get(k) or {}).get("chat")
        if ch:
            seen[ch["id"]] = (ch.get("type"), ch.get("title") or ch.get("username"))
for cid, (t, title) in seen.items():
    print("CHAT", cid, t, title)
print("toplam", len(seen))
