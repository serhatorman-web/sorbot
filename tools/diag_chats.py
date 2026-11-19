"""Botun gördüğü kanallar (getUpdates) – token yazdırılmaz."""
import json, os, urllib.request

tok = os.environ.get("TELEGRAM_TOKEN", "")
url = f"https://api.telegram.org/bot{tok}/getUpdates?allowed_updates=%5B%22channel_post%22%2C%22my_chat_member%22%2C%22message%22%5D"
try:
    with urllib.request.urlopen(url, timeout=20) as r:
        js = json.load(r)
    chats = {}
    for u in js.get("result", []):
        for k in ("channel_post", "my_chat_member", "message"):
            ch = (u.get(k) or {}).get("chat")
            if ch:
                chats[ch["id"]] = (ch.get("title") or ch.get("username"), ch.get("type"))
    for cid, (t, ty) in chats.items():
        print(f"CHN| {cid} · {t} · {ty}")
    print(f"CHN| toplam {len(chats)}")
except Exception as e:  # noqa: BLE001
    print("CHN| hata", str(e).replace(tok, "***"))
