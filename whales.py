"""
Balina takibi (BTC ve ETH)
==========================
1) Zincir üstü büyük transferler (son çalıştırmadan beri yeni bloklar)
   - BTC: blockchain.info tam blok verisi; bir işlemin en büyük çıktısı eşik üstüyse
     (para üstü çıktıları şişirmesin diye toplam yerine en büyük çıktı kullanılır)
   - ETH: herkese açık Ethereum RPC; doğrudan ETH transferleri (ERC-20/WETH dahil değil)
2) Binance emir defteri: fiyata yakın (±%0.5) alış/satış likiditesi ve en büyük duvar
   (vadeli + spot). Not: Binance tek seferde fiyata en yakın 1000 kademeyi verir.

Not: Zincir üstü transfer = alış/satış değildir; büyük oyuncuların fon hareketini gösterir.
"""

import json
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
ETH_RPCS = ("https://ethereum-rpc.publicnode.com", "https://eth.drpc.org")
ETH_BLOCKS_PER_HOUR = 300


def _get(url, data=None, timeout=30):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA, "Accept": "application/json",
                                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


# --------------------------------------------------------------------------- #
# BTC zincir üstü
# --------------------------------------------------------------------------- #
def btc_transfers(btc_price, min_usd, last_height, max_blocks=10):
    """Döner: (transfer listesi, işlenen en yüksek blok)."""
    blocks = _get("https://mempool.space/api/v1/blocks")            # son ~15 blok
    blocks = sorted(blocks, key=lambda b: b["height"])
    if last_height:
        new = [b for b in blocks if b["height"] > last_height]
    else:
        cutoff = time.time() - 3600
        new = [b for b in blocks if b["timestamp"] >= cutoff]
    new = new[-max_blocks:]
    min_btc = min_usd / btc_price

    def scan(b):
        blk = _get(f"https://blockchain.info/rawblock/{b['id']}", timeout=60)
        out = []
        for tx in blk.get("tx", [])[1:]:                            # ilk işlem: madenci ödülü
            vals = [o.get("value", 0) / 1e8 for o in tx.get("out", [])]
            if vals and max(vals) >= min_btc:
                parents = {i.get("prev_out", {}).get("tx_index") for i in tx.get("inputs", [])}
                out.append({"hash": tx["hash"], "amount": max(vals), "usd": max(vals) * btc_price,
                            "time": blk.get("time", b["timestamp"]), "height": b["height"],
                            "tx_index": tx.get("tx_index"), "parents": parents - {None}})
        return out

    transfers = []
    with ThreadPoolExecutor(max_workers=3) as ex:
        for res in ex.map(scan, new):
            transfers += res
    # Zincirleme aktarım: önceki büyük transferin çıktısını harcayan ve miktarı ±%5 aynı olan
    # işlem aynı coin'lerin yeniden taşınmasıdır -> tekrar sayma
    by_index = {t["tx_index"]: t for t in transfers if t["tx_index"] is not None}
    unique = []
    for t in transfers:
        if any(p in by_index and abs(by_index[p]["amount"] - t["amount"]) <= 0.05 * t["amount"]
               for p in t["parents"]):
            continue
        unique.append(t)
    top_height = max((b["height"] for b in new), default=last_height)
    return sorted(unique, key=lambda x: -x["usd"]), top_height


# --------------------------------------------------------------------------- #
# ETH zincir üstü
# --------------------------------------------------------------------------- #
def _rpc(method, params):
    last_err = None
    for url in ETH_RPCS:
        try:
            body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
            res = _get(url, body)
            if "result" in res:
                return res["result"]
            last_err = res.get("error")
        except Exception as e:  # noqa: BLE001
            last_err = e
    raise RuntimeError(f"ETH RPC hatası: {last_err}")


def eth_transfers(eth_price, min_usd, last_block, max_blocks=360):
    latest = int(_rpc("eth_blockNumber", []), 16)
    start = (last_block + 1) if last_block else latest - ETH_BLOCKS_PER_HOUR
    start = max(start, latest - max_blocks)
    min_eth = min_usd / eth_price

    def scan(n):
        blk = _rpc("eth_getBlockByNumber", [hex(n), True])
        out = []
        for tx in blk.get("transactions", []):
            v = int(tx.get("value", "0x0"), 16) / 1e18
            if v >= min_eth:
                out.append({"hash": tx["hash"], "amount": v, "usd": v * eth_price,
                            "from": tx.get("from"), "to": tx.get("to"), "time": int(blk["timestamp"], 16)})
        return out

    transfers = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        for res in ex.map(scan, range(start, latest + 1)):
            transfers += res
    return sorted(transfers, key=lambda x: -x["usd"]), latest


# --------------------------------------------------------------------------- #
# Binance emir defteri
# --------------------------------------------------------------------------- #
def orderbook(api, symbol, bucket, band=0.005):
    """Vadeli + spot emir defterinde fiyata yakın likidite ve en büyük duvarlar."""
    out = {}
    fut = api.get("/fapi/v1/depth", {"symbol": symbol, "limit": 1000})
    spot = _get(f"https://data-api.binance.vision/api/v3/depth?symbol={symbol}&limit=1000")
    for name, book in (("Vadeli", fut), ("Spot", spot)):
        bids = [(float(p), float(q)) for p, q in book["bids"]]
        asks = [(float(p), float(q)) for p, q in book["asks"]]
        if not bids or not asks:
            continue
        mid = (bids[0][0] + asks[0][0]) / 2
        lo, hi = mid * (1 - band), mid * (1 + band)
        bid_usd = sum(p * q for p, q in bids if p >= lo)
        ask_usd = sum(p * q for p, q in asks if p <= hi)

        def wall(levels):
            buckets = {}
            for p, q in levels:
                k = round(p / bucket) * bucket
                buckets[k] = buckets.get(k, 0) + p * q
            return max(buckets.items(), key=lambda kv: kv[1]) if buckets else (None, 0)

        out[name] = {"mid": mid, "bid_usd": bid_usd, "ask_usd": ask_usd,
                     "bid_wall": wall(bids), "ask_wall": wall(asks),
                     "range": (bids[-1][0], asks[-1][0])}
    return out
