"""Pump/Dump radarı kontrolü: son DAYS günün 1s mumlarında radar canlıdaki gibi (12 saat bekleme, taramada en
fazla 3) yeniden çalıştırılır; her uyarı kuralına göre ayrıca kontrol edilir ve sonrasında ne olduğu ölçülür."""
import sys, time, statistics as st
from collections import Counter, defaultdict
sys.path.insert(0, ".")
import scanner as S

DAYS = 14
cfg = S.load_json(S.CONFIG_PATH, None)
rc, pdc = cfg["pump_radar"], cfg["pump_dump"]
mc = rc["momentum"]
api = S.Binance()
now = int(time.time() * 1000)
uni, *_ = S.build_universe(api, cfg)
uni = [m for m in uni if m["type"] in rc.get("types", ["COIN"])]
N = DAYS * 24
events = []
for m in uni:
    sym = m["symbol"]
    try:
        cs = S.parse_klines(api.get("/fapi/v1/klines", {"symbol": sym, "interval": "1h", "limit": 499 + N}), now)
        oi = api.get("/futures/data/openInterestHist", {"symbol": sym, "period": "1h", "limit": 500})
    except Exception:  # noqa: BLE001
        continue
    if len(cs) < 400:
        continue
    oi = [(int(x["timestamp"]), float(x["sumOpenInterestValue"])) for x in oi]
    f = S.compute_features(cs, cfg)
    c = f["c"]
    for i in range(len(c) - N, len(c)):
        t_close = cs[i]["t"] + 3600000
        pts = [v for ts, v in oi if ts <= t_close][-5:]
        oi_chg = (pts[-1] / pts[0] - 1) if len(pts) >= 2 and pts[0] > 0 else None
        chg24 = (c[i] / c[i - 24] - 1) * 100
        pd = S.pump_dump_analysis(f, cfg, chg24, i)
        for rd in S.pump_radar(f, i, pd, chg24, cfg, oi_chg, None):
            events.append({"t": t_close, "sym": sym, "meta": m, "rd": rd, "f": f, "i": i, "pd": pd, "oi": oi_chg,
                           "chg24": chg24})
print(f"RD| {len(uni)} sembol · son {DAYS} gün · ham aday {len(events)}")

# canlıdaki gibi: 12 saat bekleme (sembol+yön), taramada en fazla 3 (skora göre)
by_t = defaultdict(list)
for e in events:
    by_t[e["t"]].append(e)
last, sent = {}, []
for t in sorted(by_t):
    lst = sorted(by_t[t], key=lambda e: -e["rd"]["score"])
    k = 0
    for e in lst:
        key = f"{e['sym']}|{e['rd']['dir']}"
        if key in last and t - last[key] < rc.get("cooldown_hours", 12) * 3600000:
            continue
        if k >= rc.get("max_per_run", 3):
            continue
        last[key] = t
        k += 1
        sent.append(e)

NAME = {("start", "long"): "🚀 PUMP SİNYALİ", ("start", "short"): "💥 DUMP SİNYALİ",
        ("early", "long"): "👀 PUMP ERKEN UYARI", ("early", "short"): "👀 DUMP ERKEN UYARI",
        ("momentum", "long"): "⚡ PUMP HAREKETİ", ("momentum", "short"): "⚡ DUMP HAREKETİ",
        ("reversal", "short"): "🔻 PUMP SONRASI DÖNÜŞ"}


def check(e):
    """Kuralı ham değerlerle tekrar kontrol et: ihlal listesi."""
    rd, pd, f, i = e["rd"], e["pd"], e["f"], e["i"]
    s = 1 if rd["dir"] == "long" else -1
    bad = []
    late = pd["chg3"] * s >= pdc["already_pumped_3h"] or e["chg24"] / 100 * s >= pdc["already_pumped_24h"]
    if rd["kind"] == "start":
        if not (pd["brk_up"] if s == 1 else pd["brk_dn"]): bad.append("kırılım yok")
        if not pd["vol_spike"]: bad.append("hacim patlaması yok")
        if not pd["squeeze"]: bad.append("sıkışma yok")
        if late: bad.append("geç (zaten pump/dump olmuş)")
        if rd["score"] < rc.get("min_score", 70): bad.append("skor düşük")
    elif rd["kind"] == "early":
        if not (pd["accumulation"] if s == 1 else pd["distribution"]): bad.append("birikim/dağıtım yok")
        if not pd["squeeze"]: bad.append("sıkışma yok")
        if (pd["brk_up"] if s == 1 else pd["brk_dn"]): bad.append("kırılım olmuş")
        if late: bad.append("geç")
        if e["oi"] is None or e["oi"] < 0.05: bad.append("OI artışı yok")
        if rd["score"] < rc.get("min_score_early", 55): bad.append("skor düşük")
    elif rd["kind"] == "momentum":
        o, h, l, c, v, a = f["o"], f["h"], f["l"], f["c"], f["v"], f["atr"]
        vr = v[i] / f["vol_ma"][i - 1]
        ext = max(h[i - 48:i]) if s == 1 else min(l[i - 48:i])
        rng = (h[i] - l[i]) or 1e-12
        pos = (c[i] - l[i]) / rng if s == 1 else (h[i] - c[i]) / rng
        if vr < mc["volume_x"]: bad.append(f"hacim {vr:.1f}x")
        if (c[i] - ext) * s <= 0: bad.append("48 mum zirve/dip kırılmadı")
        if (c[i] - o[i]) * s / a[i] < mc["body_atr"]: bad.append("gövde küçük")
        if pos < mc["close_pos"]: bad.append("kapanış uçta değil")
        if rd["dir"] not in mc["directions"]: bad.append("yön kapalı")
    elif rd["kind"] == "reversal" and not rc.get("reversal", {}).get("enabled"):
        bad.append("dönüş kapalıyken geldi")
    return bad


groups = defaultdict(list)
for e in sent:
    groups[(e["rd"]["kind"], e["rd"]["dir"])].append(e)
for key in NAME:
    E = groups.get(key, [])
    if not E:
        print(f"RD| {NAME[key]}: 0 uyarı")
        continue
    viol = [(e["sym"], check(e)) for e in E]
    viol = [x for x in viol if x[1]]
    s = 1 if key[1] == "long" else -1
    mv = {h: [] for h in (4, 24)}
    tp1 = stp = 0
    for e in E:
        f, i = e["f"], e["i"]
        c = f["c"]
        for h in (4, 24):
            if i + h < len(c):
                mv[h].append((c[i + h] / c[i] - 1) * 100 * s)
        if key[0] != "early":
            entry, sl, tps, _ = S.levels({"f": f, "i": i}, key[1], cfg)
            for k in range(i + 1, min(len(c), i + 49)):
                if (f["l"][k] <= sl) if s == 1 else (f["h"][k] >= sl):
                    stp += 1
                    break
                if (f["h"][k] >= tps[0]) if s == 1 else (f["l"][k] <= tps[0]):
                    tp1 += 1
                    break
    line = f"RD| {NAME[key]}: {len(E)} uyarı ({len(E) / DAYS:.1f}/gün) · kural ihlali {len(viol)}"
    for h in (4, 24):
        if mv[h]:
            line += (f" · {h}s sonra doğru yönde %{100 * sum(x > 0 for x in mv[h]) / len(mv[h]):.0f}"
                     f" ort {st.mean(mv[h]):+.2f}%")
    if key[0] != "early" and (tp1 + stp):
        line += f" · TP1 önce %{100 * tp1 / (tp1 + stp):.0f} ({tp1}/{tp1 + stp}), stop önce {stp}"
    print(line)
    for sym, b in viol[:5]:
        print(f"RD|    ihlal: {sym} {b}")
    for e in E[-3:]:
        tt = S.datetime.fromtimestamp(e["t"] / 1000, S.TR_TZ).strftime("%d.%m %H:%M")
        print(f"RD|    örnek: {tt} {e['sym']} skor {e['rd']['score']} · {' · '.join(e['rd']['reasons'])}")
    # mesaj oluşturma kontrolü (son uyarı)
    e = E[-1]
    res = {"meta": e["meta"], "f": e["f"], "i": e["i"], "pd": e["pd"], "chg24": e["chg24"]}
    try:
        msg = S.build_radar_message(res, e["rd"], cfg, S.datetime.now(S.timezone.utc))
        head = [x for x in msg.splitlines() if x.strip()][1]
        ok = NAME[key].split(" ", 1)[1] in head
        lv = [x for x in msg.splitlines() if x.startswith(("<b>Stop", "<b>TP1"))]
        print(f"RD|    mesaj: başlık {'doğru' if ok else 'YANLIŞ'} → {head} · {' / '.join(lv)}")
    except Exception as ex:  # noqa: BLE001
        print(f"RD|    mesaj oluşturulamadı: {type(ex).__name__}: {ex}")
print(f"RD| gönderilecek toplam {len(sent)} · bekleme/sınır yüzünden elenen {len(events) - len(sent)}")
