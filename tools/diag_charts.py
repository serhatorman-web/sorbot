"""Grafik kanalı kontrolü: bot kanala resim gönderebiliyor mu? (token yazdırılmaz)"""
import json, os, sys, urllib.request, urllib.parse
sys.path.insert(0, ".")
import scanner as S

tok = os.environ.get("TELEGRAM_TOKEN", "")
cfg = S.load_json(S.CONFIG_PATH, None)
chat = cfg["telegram"].get("charts_chat_id")


def call(m, **p):
    url = f"https://api.telegram.org/bot{tok}/{m}?" + urllib.parse.urlencode(p)
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            return json.load(r)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "err": str(e).replace(tok, "***")}


me = call("getMe")
print("CH| token var:", bool(tok), "· bot:", me.get("result", {}).get("username"))
c = call("getChat", chat_id=chat)
print("CH| kanal:", chat, "·", c.get("result", {}).get("title"), "· tür:", c.get("result", {}).get("type"), "· hata:", c.get("err") or c.get("description"))
m = call("getChatMember", chat_id=chat, user_id=me.get("result", {}).get("id"))
r = m.get("result", {})
print("CH| botun yetkisi:", r.get("status"), "· mesaj gönderebilir:", r.get("can_post_messages"), "· hata:", m.get("err") or m.get("description"))
n = S.Notifier()
print("CH| Notifier grafik kanalı:", n.charts_chat)
