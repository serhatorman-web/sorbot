"""Nokta atışı örnekleri (son 2 gün, her kategori için en yeni sinyal) + botun gördüğü kanallar."""
import json, os, sys, time, urllib.request
sys.path.insert(0, ".")
import scanner as S
import sniper as SN

tok = os.environ.get("TELEGRAM_TOKEN", "")
if tok:
    try:
        with urllib.request.urlopen(f"https://api.telegram.org/bot{tok}/getUpdates?allowed_updates=%5B%22channel_post%22%2C%22my_chat_member%22%2C%22message%22%5D", timeout=20) as r:
            js = json.load(r)
        chats = {}
        for u in js.get("result", []):
            for k in ("channel_post", "my_chat_member", "message"):
                ch = (u.get(k) or {}).get("chat")
                if ch:
                    chats[ch["id"]] = (ch.get("title") or ch.get("username"), ch.get("type"))
        for cid, (t, ty) in chats.items():
            print(f"CHN| {cid} · {t} · {ty}")
        print(f"CHN| toplam {len(chats)} sohbet")
    except Exception as e:  # noqa: BLE001
        print("CHN| hata", str(e).replace(tok, "***"))

base = S.load_json(S.CONFIG_PATH, None)
api = S.Binance()
now_ms = int(time.time() * 1000)
for tf in ("15m", "1h"):
    cfg = S.apply_tf_profile(base, tf) if tf != "1h" else base
    sc = cfg["sniper"]
    rules = sc["rules"][tf]
    uni, *_ = S.build_universe(api, cfg)
    uni = [m for m in uni if m["type"] == "COIN"]
    tf_ms = S.TF_MS[tf]
    found = {}
    n_all = 0
    for m in uni:
        try:
            cs = S.parse_klines(api.get("/fapi/v1/klines", {"symbol": m["symbol"], "interval": tf, "limit": 500}), now_ms)
        except Exception:  # noqa: BLE001
            continue
        o, h, l, c, v = ([x[k] for x in cs] for k in ("o", "h", "l", "c", "v"))
        x = SN.features(o, h, l, c, v)
        look = 192 if tf == "15m" else 48
        cs4 = None
        for i in range(len(c) - look, len(c)):
            for sig in SN.setups(o, h, l, c, v, i, x):
                rc = rules.get(sig["rule"])
                if not rc or not rc.get("enabled"):
                    continue
                if cs4 is None:
                    cs4 = S.parse_klines(api.get("/fapi/v1/klines", {"symbol": m["symbol"], "interval": "4h", "limit": 400}), now_ms)
                t_close = cs[i]["t"] + tf_ms
                htf = SN.htf_trend([y for y in cs4 if y["t"] + 14400000 <= t_close][-260:])
                if rc.get("htf") and htf != sig["d"]:
                    continue
                n_all += 1
                cat = SN.RULES[sig["rule"]][0]
                if cat in found and found[cat][0] >= t_close:
                    continue
                lv = SN.levels(c[i], sig["d"], sig["stop"], x["a"][i], rc.get("min_stop_pct", 0))
                tc = S.datetime.fromtimestamp(t_close / 1000, S.TR_TZ).strftime("%d.%m.%Y %H:%M")
                msg = SN.message(S.display_name(m), {"15m": "15dk", "1h": "1 saat"}[tf], sig, lv,
                                 lambda p, pr=m.get("precision"): S.fmt_price(p, pr), tc, htf, rc)
                # sonrası ne oldu (kontrol için)
                d, e = sig["d"], lv["entry"]
                best, stp = 0, False
                for k in range(i + 1, len(c)):
                    if (l[k] <= lv["stop"]) if d == 1 else (h[k] >= lv["stop"]):
                        stp = True
                        break
                    best = max(best, sum(1 for tp in lv["tp"] if ((h[k] >= tp) if d == 1 else (l[k] <= tp))))
                    if best == 3:
                        break
                res = (f"TP{best} oldu" if best else "") + (" sonra stop" if stp and best else "stop" if stp else "") or "henüz açık"
                found[cat] = (t_close, msg, res)
    print(f"EX| ===== {tf}: son {'2 gün' if tf == '15m' else '2 gün'} içinde {n_all} sinyal ({len(uni)} coin) =====")
    for cat, (t, msg, res) in found.items():
        print(f"EX| --- {cat} (sonrası: {res}) ---")
        for ln in msg.splitlines():
            print("EX| " + ln)
