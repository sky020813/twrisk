# -*- coding: utf-8 -*-
"""共機／共艦每日活動量：從公開報導抽取國防部公布的架次與艘次。

為什麼要獨立成模組：抽取規則很容易漏掉中文的各種寫法（「6艘共艦」「共艦6艘」
「船艦15艘」），必須能單獨測試、反覆調校，不能埋在主管線裡。

資料性質與限制（畫面上也必須寫）：
  * 來源是媒體轉述國防部的公布數字，非官方 API。
  * 國防部於每日上午公布「前一日」的偵獲數量，故報告日 ≠ 活動日。
  * 同一日的不同報導可能給出不同數字（不同時間窗或更正），此處取「最多來源一致」的值。
  * 公務船（海警、公務船）與軍艦分開記錄，不合併。
"""
import re, ssl, urllib.request, urllib.parse, xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from datetime import timedelta, timezone

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
TW = timezone(timedelta(hours=8))

# ---- 抽取規則 ----
# 關鍵：中文的數字可能在詞前或詞後，且「5艘共艦8艘公務船」這種串接會讓
# 「共艦<數字>」誤吃到公務船的數字。因此**先試「數字在前」的寫法**，
# 且「共艦<數字>」一律要求後面接「艘／艘次」。
P_AIR = [
    r"(\d+)\s*架次?\s*(?:共機|中共軍機|大陸軍機|軍機)",     # 23架次共機
    r"(?:共機|中共軍機|大陸軍機|軍機)\s*(\d+)\s*架次?",       # 共機29架次
    r"(?:共機|中共軍機|大陸軍機|軍機)\s*(\d+)\s*架\b",        # 共機3架
]
P_SHIP = [
    r"(\d+)\s*艘次?\s*(?:共艦|中共軍艦|大陸軍艦|軍艦)",       # 5艘共艦（優先，避免吃到公務船）
    r"(?:共艦|中共軍艦|大陸軍艦|軍艦)\s*(\d+)\s*艘次?",       # 共艦6艘次
    r"(?:船艦|艦艇)\s*(\d+)\s*艘", r"(\d+)\s*艘次?\s*(?:船艦|艦艇)",
]
P_OFFICIAL = [r"公務船\s*(\d+)\s*艘次?", r"(\d+)\s*艘次?\s*公務船"]
P_AIR0 = [r"未偵獲\s*共機", r"未偵獲\s*(?:中共|大陸)?軍機", r"共機.{0,8}?(?:未|無).{0,4}(?:擾|進入)",
          r"\bno Chinese (?:aircraft|planes|warplanes)\b",
          r"(?:did not|didn't) detect.{0,14}(?:aircraft|planes)"]

# 英文：軍艦必須是 naval vessel / warship / PLAN vessel，避免把 official ships（公務船）算進來；
# 但 "N ships" 若前面沒有 official／public 字樣，就是軍艦（"9 official ships" 不會被誤抓，
# 因為數字後面接的是 official 而不是 ships）。
EN_AIR = [r"(\d+)\s+(?:Chinese|PLA|PLAN)\s+(?:military\s+)?(?:aircraft|warplanes|planes|fighters)",
          r"(\d+)\s+military\s+aircraft",
          r"(\d+)\s+(?:aircraft|warplanes|fighters).{0,24}(?:near|around)\s+Taiwan"]
EN_SHIP = [r"(\d+)\s+(?:Chinese\s+|PLA\s+|PLAN\s+)?(?:naval vessels?|navy ships?|warships?|warship)",
           r"(\d+)\s+(?:Chinese|PLA|PLAN)\s+(?:ships?|vessels?)",
           r"(\d+)\s+ships?\b(?!\s+(?:official|public))",
           r"(\d+)\s+(?:naval vessels?|warships?).{0,24}(?:near|around)\s+Taiwan"]
EN_OFFICIAL = [r"(\d+)\s+official\s+ships?"]


def _first(text, pats):
    for p in pats:
        m = re.search(p, text, re.I)
        if m:
            return int(m.group(1))
    return None


def parse_title(title):
    """回傳 (air, ship, official, ok)。ok=False 表示這則標題沒提供可用的數字組合。"""
    air = _first(title, P_AIR)
    ship = _first(title, P_SHIP)
    off = _first(title, P_OFFICIAL)
    if air is None:
        air = _first(title, EN_AIR)
    if ship is None:
        ship = _first(title, EN_SHIP)
    if off is None:
        off = _first(title, EN_OFFICIAL)
    # 明確的「未偵獲共機」→ 0 架次
    if air is None and any(re.search(p, title, re.I) for p in P_AIR0):
        air = 0
    ok = (air is not None) or (ship is not None)
    return air, ship, off, ok


def gnews(q, days=7, zh=True):
    hl, gl, ceid = ("zh-TW", "TW", "TW:zh-Hant") if zh else ("en-US", "US", "US:en")
    return ("https://news.google.com/rss/search?q=" + urllib.parse.quote("%s when:%dd" % (q, days))
            + "&hl=" + hl + "&gl=" + gl + "&ceid=" + ceid)


def fetch_items(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30, context=CTX) as r:
        raw = r.read()
    out = []
    try:
        root = ET.fromstring(raw)
    except Exception:
        return out
    for it in root.iter("item"):
        t = (it.findtext("title") or "").strip()
        p = (it.findtext("pubDate") or "").strip()
        s = ""
        e = it.find("source")
        if e is not None and e.text:
            s = e.text.strip()
        out.append({"t": t, "p": p, "s": s})
    return out


QUERIES = [
    ("共機 架次 共艦 艘次", 7, True),
    ("偵獲 共機 共艦 台海 周邊 擾台", 7, True),
    ("Taiwan detects Chinese aircraft ships", 8, False),
    ("Taiwan tracks Chinese aircraft naval vessels", 8, False),
]


def report_date(pub):
    try:
        dt = parsedate_to_datetime(pub).astimezone(TW)
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return None


def collect(days=None):
    """抓一輪，回傳 {日期: {air, ship, official, n, srcs, titles}}。

    同一天多筆報導時，取「最多來源一致的 (air, ship) 組合」為準。
    """
    rows = []
    for q, d, zh in QUERIES:
        try:
            for it in fetch_items(gnews(q, d, zh)):
                air, ship, off, ok = parse_title(it["t"])
                day = report_date(it["p"])
                if ok and day:
                    rows.append({"day": day, "air": air, "ship": ship, "off": off,
                                 "t": it["t"], "s": it["s"]})
        except Exception:
            pass
    by = {}
    for r in rows:
        by.setdefault(r["day"], []).append(r)

    daily = {}
    for day, rs in by.items():
        votes = {}
        for r in rs:
            key = (r["air"], r["ship"])
            v = votes.setdefault(key, {"n": 0, "off": [], "titles": [], "srcs": set()})
            v["n"] += 1
            if r["off"] is not None:
                v["off"].append(r["off"])
            v["titles"].append(r["t"])
            if r["s"]:
                v["srcs"].add(r["s"])
        # 取票數最多；同票取 (機+艦) 較大者（較完整的那份報告）
        best = sorted(votes.items(), key=lambda kv: (-kv[1]["n"], -(sum(x or 0 for x in kv[0]))))[0]
        (air, ship), v = best
        offs = v["off"]
        daily[day] = {
            "air": air, "ship": ship,
            "official": max(set(offs), key=offs.count) if offs else None,
            "n": v["n"], "srcs": sorted(v["srcs"])[:4],
            "title": v["titles"][0],
        }
    return daily


if __name__ == "__main__":
    d = collect()
    print("抓到 %d 天" % len(d))
    for day in sorted(d):
        x = d[day]
        print("  %s  機 %-4s 艦 %-4s 公務船 %-4s (%d 則一致)  %s"
              % (day, x["air"], x["ship"], x["official"], x["n"], x["title"][:60]))
