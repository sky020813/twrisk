# -*- coding: utf-8 -*-
"""台海風險觀測儀表板 — 自動更新器（事件聚合版）

抓 29 家來源 → 關鍵詞分級 → **同一事件聚合**（多家報導只算一件）→ 產生網頁。

為什麼要聚合：同一件事常被 10 家媒體各寫一則標題，若逐則計分，報導量大的事件
會把「嚴重度佔比」整個拉偏。改成以「事件」為單位，才反映真正的訊號強度。

聚合方式（無外部套件）：
  1. 標題正規化：去掉尾部來源後綴、去標點、轉小寫
  2. 特徵集：英文用詞（去停用詞）＋中文用字元 bigram
  3. 相似度：Jaccard
  4. 貪婪分群：與群內任一成員相似度 >= THRESH 即歸為同一事件（取最大值，避免漂移）
"""
import json, os, re, ssl, subprocess, sys, time, urllib.request, urllib.parse, xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta

HERE      = os.path.dirname(os.path.abspath(__file__))
# 註：本機輸出檔名沿用建立時的名稱（桌面上的檔案不因網站改版而更名）；
# 雲端（GitHub Actions）一律以 TWRISK_HTML=index.html 覆寫，故與此無關。
OUT_HTML  = os.environ.get("TWRISK_HTML", r"C:\Users\Kai\Desktop\台海風險指標追蹤表.html")
OUT_PDF   = os.environ.get("TWRISK_PDF",  r"C:\Users\Kai\Desktop\台海風險指標追蹤表.pdf")
HIST_JSON = os.environ.get("TWRISK_HIST", os.path.join(HERE, "twrisk_history.json"))
LATEST    = os.path.join(HERE, "latest.json")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
TW = timezone(timedelta(hours=8))

THRESH = 0.34        # 相似度門檻（以實測資料調校：0.26 會併到財報樣板、0.38 又太保守）

# ============ 來源清單 (id, 名稱, 分類, 網域, 語言, 原生RSS) ============
SOURCES = [
    ("reuters",   "Reuters",              "國際通訊社", "reuters.com",         "en", None),
    ("ap",        "AP",                   "國際通訊社", "apnews.com",          "en", None),
    ("afp",       "AFP",                  "國際通訊社", "afp.com",             "en", None),
    ("bloomberg", "Bloomberg",            "國際通訊社", "bloomberg.com",       "en", None),
    ("bbc",       "BBC",                  "國際媒體",   "bbc.com",             "en", "https://feeds.bbci.co.uk/news/world/asia/rss.xml"),
    ("guardian",  "The Guardian",         "國際媒體",   "theguardian.com",     "en", "https://www.theguardian.com/world/rss"),
    ("aljazeera", "Al Jazeera",           "國際媒體",   "aljazeera.com",       "en", "https://www.aljazeera.com/xml/rss/all.xml"),
    ("dw",        "DW 德國之聲",           "國際媒體",   "dw.com",              "en", "https://rss.dw.com/rdf/rss-en-world"),
    ("nyt",       "New York Times",       "國際媒體",   "nytimes.com",         "en", "https://rss.nytimes.com/services/xml/rss/nyt/World.xml"),
    ("wapo",      "Washington Post",      "國際媒體",   "washingtonpost.com",  "en", None),
    ("wsj",       "Wall Street Journal",  "國際媒體",   "wsj.com",             "en", None),
    ("ft",        "Financial Times",      "國際媒體",   "ft.com",              "en", None),
    ("economist", "The Economist",        "國際媒體",   "economist.com",       "en", None),
    ("cnn",       "CNN",                  "國際媒體",   "cnn.com",             "en", None),
    ("nikkei",    "Nikkei Asia",          "亞洲",       "asia.nikkei.com",     "en", None),
    ("scmp",      "SCMP 南華早報",         "亞洲",       "scmp.com",            "en", None),
    ("st",        "Straits Times",        "亞洲",       "straitstimes.com",    "en", None),
    ("cnaasia",   "CNA 新加坡",            "亞洲",       "channelnewsasia.com", "en", None),
    ("nhk",       "NHK",                  "亞洲",       "www3.nhk.or.jp",      "jp", "https://www3.nhk.or.jp/rss/news/cat0.xml"),
    ("diplomat",  "The Diplomat",         "專業智庫",   "thediplomat.com",     "en", "https://thediplomat.com/feed/"),
    ("fp",        "Foreign Policy",       "專業智庫",   "foreignpolicy.com",   "en", None),
    ("lowyin",    "Lowy Institute",       "專業智庫",   "lowyinstitute.org",   "en", None),
    ("tw_cna",    "中央社",                "台灣",       "cna.com.tw",          "zh", "https://feeds.feedburner.com/rsscna/intworld"),
    ("tw_focus",  "Focus Taiwan",         "台灣",       "focustaiwan.tw",      "en", None),
    ("tw_news",   "Taiwan News",          "台灣",       "taiwannews.com.tw",   "en", None),
    ("tw_ltn",    "自由時報",              "台灣",       "ltn.com.tw",          "zh", "https://news.ltn.com.tw/rss/all.xml"),
    ("tw_udn",    "聯合報",                "台灣",       "udn.com",             "zh", "https://udn.com/rssfeed/news/2/6638?ch=news"),
    ("tw_pts",    "公視新聞",              "台灣",       "news.pts.org.tw",     "zh", None),
    ("tw_report", "報導者",                "台灣",       "twreporter.org",      "zh", None),
]

# ============ 關鍵詞分級 ============
TIER = [
    ("警示", [
        (r"核武|核彈|nuclear (weapon|strike|war)", "核武"),
        (r"封鎖|blockad", "封鎖"),
        (r"入侵|invasi", "入侵"),
        (r"登陸|amphibious|beach ?head", "登陸"),
        (r"開戰|宣戰|declare war", "開戰"),
        # 只認「撤離本國僑民」；颱風／水災的居民疏散（evacuated）不算，否則天氣新聞會誤判成最高級
        (r"撤僑|撤離僑民|evacuat\w*\s+(its\s+|the\s+)?(citizens|nationals|expatriates|foreigners)"
         r"|(citizens|nationals|expatriates)\s+evacuat", "撤僑"),
        (r"動員令|軍事動員|military mobilis|troop mobilis|general mobilis", "動員"),
        (r"飛彈|導彈|missile", "飛彈"),
        (r"制裁|sanction", "制裁"),
        (r"禁航|禁飛|no[- ]fly|airspace clos", "禁航"),
        (r"空襲|air ?strike|military strike|missile strike|strikes? on", "打擊"),
        (r"斬首|decapitat", "斬首"),
        (r"實彈|live[- ]fire", "實彈"),
        (r"斷鏈|斷糧|供應鏈中斷", "斷鏈"),
    ]),
    ("注意", [
        (r"軍演|演習|\bmilitary (drill|exercise)|war ?games?", "軍演"),
        (r"動員|mobilis|mobiliz", "動員"),
        (r"擾台|incursion", "擾台"),
        (r"中線|median line", "中線"),
        (r"海警|coast guard", "海警"),
        (r"灰色地帶|gr[ae]y[- ]zone", "灰色地帶"),
        (r"緊張|tension", "緊張"),
        (r"衝突|conflict|\bwar\b|\bwars\b", "衝突"),
        (r"擴軍|arms race|build ?up|buildup", "擴軍"),
        (r"戰備|combat readiness", "戰備"),
        (r"後備|reservist", "後備"),
        (r"巡邏|patrol", "巡邏"),
        (r"越線|cross(ed|ing)? the (median|strait)", "越線"),
        (r"\bdrills?\b", "演訓"),
    ]),
    ("緩和", [
        (r"交流|exchange", "交流"),
        (r"會談|對話|\btalks?\b|dialogue", "會談"),
        (r"和平|\bpeace", "和平"),
        (r"磋商|consultation|互訪", "磋商"),
    ]),
]
RANK = {"警示": 3, "注意": 2, "緩和": 1, "一般": 0}

RELEVANT = ["台海", "台灣", "臺灣", "共軍", "解放軍", "習近平", "台北", "兩岸", "中共",
            "taiwan", "taipei", "pla ", "beijing", "cross-strait", "strait", "china"]

STOP = set("""the a an of to in on for and or with as at by from is are was were be been it its this
that these those will would can could may might has have had not no new says say said after before
over under into out up down about than then also more most very s t re ve ll d m""".split())


# ---- 非新聞雜訊：股價報價頁、分類頁、市場摘要頁等 ----
JUNK_PAT = re.compile(
    r"(?i)(stock|share)\s+(price\s+)?quote"
    r"|\bquote\b[^a-z]{0,4}(taipei|taiwan)"
    r"|financials|annual report|exchange rates?|market summary|weather forecast"
    r"|earnings call|financial results|third quarter \d{4} results|to (report|host) .{0,30}(results|earnings)"
    r"|schedules? .{0,24}(earnings|results)"
    r"|^(china|taiwan|asia|asia pacific|world|business|markets?|politics|opinion|tech)\s*[-–—|｜]\s*"
)


def junk(title):
    if JUNK_PAT.search(title):
        return True
    t = norm_title(title)
    latin = len([w for w in t.split() if w not in STOP and len(w) > 1])
    cjk = len([ch for ch in t if "\u4e00" <= ch <= "\u9fff"])
    return (latin + cjk / 2.0) < 2.5      # 「China - AP News」這類分類頁


# ============ 取資料 ============
def gnews(domain, term, days, lang):
    hl, gl, ceid = ("zh-TW", "TW", "TW:zh-Hant") if lang == "zh" else ("en-US", "US", "US:en")
    q = "site:%s %s when:%dd" % (domain, term, days)
    return ("https://news.google.com/rss/search?q=" + urllib.parse.quote(q)
            + "&hl=" + hl + "&gl=" + gl + "&ceid=" + ceid)


def fetch(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": "application/rss+xml,application/xml,text/xml,*/*"})
    with urllib.request.urlopen(req, timeout=30, context=CTX) as r:
        return r.read()


def parse(xml_bytes):
    out = []
    try:
        root = ET.fromstring(xml_bytes)
    except Exception:
        return out
    for it in root.iter("item"):
        def g(tag):
            e = it.find(tag)
            return (e.text or "").strip() if e is not None else ""
        out.append({"title": g("title"), "link": g("link"), "pub": g("pubDate")})
    return out


def tier_of(text):
    for name, pats in TIER:
        for rx, label in pats:
            if re.search(rx, text, re.I):
                return name, label
    return "一般", ""


def core_title(t):
    """去掉尾部的「 - Taiwan News」等來源標記。

    一定要在「相關性檢查」之前呼叫：否則媒體名本身就會讓無關內容過關
    （例：某公司財報新聞的尾綴是「- Taiwan News」，只因含 Taiwan 而被收進來）。
    """
    t = re.sub(r"<[^>]+>", "", t)
    for _ in range(2):
        t = re.sub(r"\s*[-–—|｜]\s*[^-–—|｜]{2,28}$", "", t)
    return t.strip()


def relevant(text):
    low = core_title(text).lower()
    return any(k.lower() in low for k in RELEVANT)


# ============ 事件聚合 ============
def norm_title(t):
    t = re.sub(r"<[^>]+>", "", t)
    for _ in range(2):                                    # 去掉 "- Reuters"、"｜太報 | 要聞"
        t = re.sub(r"\s*[-–—|｜]\s*[^-–—|｜]{2,28}$", "", t)
    t = t.lower()
    t = re.sub(r"[^\w\u4e00-\u9fff]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def sig_of(title):
    t = norm_title(title)
    s = {"w:" + w for w in t.split() if w not in STOP and len(w) > 1}
    zh = "".join(ch for ch in t if "\u4e00" <= ch <= "\u9fff")
    for i in range(len(zh) - 1):
        s.add("z:" + zh[i:i + 2])
    return s


def jac(a, b):
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return inter / (len(a) + len(b) - inter)


def cluster_articles(arts, thr=THRESH):
    """貪婪分群：與群內「任一成員」相似度 >= thr 就歸為同一事件。

    只取「最大相似度」比較、不累積群特徵，避免鏈式漂移（A併B、B併C，
    最後 A 和 C 明明不同事件卻同群）。
    """
    sigs = [sig_of(a["t"]) for a in arts]
    clusters = []
    for i, a in enumerate(arts):
        s = sigs[i]
        best, bs = None, 0.0
        for c in clusters:
            for m in c["sigs"]:
                v = jac(s, m)
                if v > bs:
                    best, bs = c, v
        if best is not None and bs >= thr:
            best["sigs"].append(s)
            best["members"].append(a)
        else:
            clusters.append({"sigs": [s], "members": [a]})
    return clusters


def pick_rep(members):
    """挑群內最居中（與其他成員平均相似度最高）的一則當代表標題。"""
    if len(members) == 1:
        return members[0]
    sigs = [sig_of(m["t"]) for m in members]
    best, bi = -1.0, 0
    for i, s in enumerate(sigs):
        avg = sum(jac(s, sigs[j]) for j in range(len(sigs)) if j != i) / (len(sigs) - 1)
        if avg > best:
            best, bi = avg, i
    return members[bi]


# ================= 主流程 =================
now = datetime.now(TW)
arts, src_meta, errors = [], [], []

for sid, name, cat, domain, lang, rss in SOURCES:
    got, via = [], ""
    if rss:
        try:
            got = [x for x in parse(fetch(rss)) if relevant(x["title"])]
            if got:
                via = "rss"
        except Exception as e:
            errors.append("%s(rss): %s" % (name, str(e)[:70]))
        time.sleep(0.8)
    if not got:
        term = "台海" if lang == "zh" else "Taiwan"
        days = 3 if lang == "zh" else 7
        try:
            got = [x for x in parse(fetch(gnews(domain, term, days, lang))) if relevant(x["title"])]
            if got:
                via = "gnews"
        except Exception as e:
            errors.append("%s(gnews): %s" % (name, str(e)[:70]))
        time.sleep(1.2)
    got = [x for x in got if not junk(x["title"])][:40]
    src_meta.append({"id": sid, "name": name, "cat": cat, "n": len(got), "via": via,
                     "ok": bool(got), "url": "https://" + domain})
    for x in got:
        k, w = tier_of(x["title"])
        arts.append({"t": x["title"], "l": x["link"], "s": sid, "k": k, "w": w, "p": (x["pub"] or "")[:32]})

# 標題完全相同的先去重（跨來源同一則）
seen, uniq = set(), []
for a in arts:
    key = re.sub(r"\W+", "", a["t"].lower())[:60]
    if key in seen:
        continue
    seen.add(key); uniq.append(a)


# 語料清洗：Google News 對 site: 查詢不一定嚴格遵守 when: 時間篩選，偶爾回傳多年前的
# 舊文（實測出現 2014、2015、2016、2017、2020 年的文章）。這些舊文會混進分母、讓指數
# 失真，因此只保留近 8 天內的報導。無法解析日期者一律保留（寧可留著，不可誤刪）。
def _pubdate(s):
    s = (s or "").strip()
    if not s:
        return None
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(s).astimezone(TW).strftime("%Y-%m-%d")
    except Exception:
        m = re.search(r"(\d{4})-(\d{2})-(\d{2})", s)
        return m.group(0) if m else None


CUT = (now - timedelta(days=8)).strftime("%Y-%m-%d")
_drop = [a for a in uniq if (_pubdate(a.get("p")) or CUT) < CUT]
uniq = [a for a in uniq if (_pubdate(a.get("p")) or CUT) >= CUT]

uniq.sort(key=lambda a: a["p"], reverse=True)
for i, a in enumerate(uniq):
    a["i"] = i

clusters = cluster_articles(uniq)
clusters.sort(key=lambda c: (-max(RANK[m["k"]] for m in c["members"]),
                             -len(c["members"]),
                             min(m["p"] for m in c["members"])))

events = []
for ci, c in enumerate(clusters):
    # 群內再用「正規化標題」去重：同一則被不同來源轉載時，卡片上不重複列出
    seen_norm, ms = set(), []
    for m in c["members"]:
        k = norm_title(m["t"])[:70]
        if k in seen_norm:
            continue
        seen_norm.add(k); ms.append(m)
    rep = pick_rep(ms)
    events.append({
        "rep": rep["t"],
        "repLink": rep["l"],
        "srcs": sorted({m["s"] for m in ms}),
        "members": [m["i"] for m in ms],
        "tier": max((m["k"] for m in ms), key=lambda k: RANK[k]),
        "kw": next((m["w"] for m in ms if RANK[m["k"]] == max(RANK[x["k"]] for x in ms)), ""),
        "p": min(m["p"] for m in ms),
    })

# 以「事件」為單位統計（基準值；使用者勾選後在瀏覽器端重算）
n_hi  = sum(1 for e in events if e["tier"] == "警示")
n_mid = sum(1 for e in events if e["tier"] == "注意")
n_cal = sum(1 for e in events if e["tier"] == "緩和")
NE = len(events)
heat = round(100.0 * (n_hi * 3 + n_mid) / (3.0 * max(1, NE)))
if   n_hi >= 8 and heat >= 20: level = "高"
elif n_hi >= 4 and heat >= 12: level = "升高"
elif n_hi >= 1 or heat >= 6:   level = "注意"
else:                          level = "相對平穩"

multi = sum(1 for e in events if len(e["srcs"]) > 1)
ok_src = [s for s in src_meta if s["ok"]]

hist = []
if os.path.exists(HIST_JSON):
    try:
        hist = json.load(open(HIST_JSON, encoding="utf-8"))
    except Exception:
        hist = []
hist.append({"ts": now.strftime("%Y-%m-%d %H:%M"), "n": len(uniq), "ev": NE, "hi": n_hi,
             "mid": n_mid, "cal": n_cal, "gen": NE - n_hi - n_mid - n_cal,
             "heat": heat, "level": level,
             "src_ok": len(ok_src), "src_all": len(src_meta)})
hist = hist[-90:]
json.dump(hist, open(HIST_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

# ================= 共機／共艦每日活動量（國防部公布，媒體轉述）=================
PLA_JSON = os.path.join(HERE, "pla_history.json")
pla_new, pla_err = {}, ""
try:
    sys.path.insert(0, HERE)
    import pla as plamod
    pla_new = plamod.collect()
except Exception as e:
    pla_err = str(e)[:140]

pla_hist = {}
if os.path.exists(PLA_JSON):
    try:
        pla_hist = json.load(open(PLA_JSON, encoding="utf-8"))
    except Exception:
        pla_hist = {}
for d, v in (pla_new or {}).items():                      # 新資料覆蓋舊資料（投票結果較新）
    old = pla_hist.get(d)
    if (not old) or (v.get("n", 0) >= old.get("n", 0)):
        pla_hist[d] = v
try:
    json.dump(pla_hist, open(PLA_JSON, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1, sort_keys=True)
except Exception as e:
    pla_err = (pla_err + " / " + str(e))[:140]

pla_series = [dict(pla_hist[k], day=k) for k in sorted(pla_hist)]
pla_latest = pla_series[-1] if pla_series else None

# 危機指數的兩種算法 ─────────────────────────────────────────────
# (a) 執行時快照：同一天若多次更新取平均。缺點是要「等本站累積」，過去沒有值。
day_heat = {}
for x in hist:
    d = (x.get("ts") or "")[:10]
    day_heat.setdefault(d, []).append(x.get("heat", 0))
day_heat = {d: round(sum(v) / len(v), 1) for d, v in day_heat.items()}

# (b) 以「發文日」回算：把抓到的語料庫按每則報導的發文日分組，逐日算嚴重度佔比。
#     這樣過去幾天立刻有值，不必等累積；也讓「同日配對」在時間上更對齊。
#     （_pubdate 定義於上方語料清洗處，此處沿用。）
day_bucket = {}
for a in uniq:
    d = _pubdate(a.get("p"))
    if not d:
        continue
    b = day_bucket.setdefault(d, {"n": 0, "hi": 0, "mid": 0})
    b["n"] += 1
    if a["k"] == "警示":
        b["hi"] += 1
    elif a["k"] == "注意":
        b["mid"] += 1
day_index = {d: round(100.0 * (v["hi"] * 3 + v["mid"]) / (3.0 * max(1, v["n"])))
             for d, v in day_bucket.items()}

# 配對（以「公布日」對齊；國防部公布的是前一日活動，畫面上會註明這個時間差）
# 指數優先採「以發文日回算」的值，沒有才退回執行時快照。
pairs = []
for x in pla_series:
    d = x["day"]
    hv = day_index.get(d, day_heat.get(d))
    if hv is not None:
        pairs.append({"d": d, "tot": (x.get("air") or 0) + (x.get("ship") or 0),
                      "air": x.get("air"), "ship": x.get("ship"), "heat": hv,
                      "src": "pubdate" if d in day_index else "snapshot"})


def pearson(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    dx = sum((a - mx) ** 2 for a in xs)
    dy = sum((b - my) ** 2 for b in ys)
    if dx == 0 or dy == 0:
        return None
    return num / (dx * dy) ** 0.5


PLA = {"series": pla_series[-60:], "latest": pla_latest, "pairs": pairs,
       "dayIndex": day_index, "dayHeat": day_heat,
       "r": pearson([p["tot"] for p in pairs], [p["heat"] for p in pairs]),
       "n_pairs": len(pairs), "err": pla_err}

DATA = {"ts": now.strftime("%Y-%m-%d %H:%M"), "sources": src_meta, "arts": uniq,
        "events": events, "errors": errors[:12], "hist": hist[-14:], "pla": PLA}

tpl = open(os.path.join(HERE, "template.html"), encoding="utf-8").read()
open(OUT_HTML, "w", encoding="utf-8").write(tpl.replace("/*__DATA__*/", json.dumps(DATA, ensure_ascii=False)))

name_of = {s["id"]: s["name"] for s in src_meta}
json.dump({"ts": DATA["ts"], "level": level, "heat": heat, "n": len(uniq), "ev": NE,
           "hi": n_hi, "mid": n_mid,
           "hi_titles":  [e["rep"] + "（" + "、".join(name_of.get(x, x) for x in e["srcs"][:3]) + "）"
                          for e in events if e["tier"] == "警示"][:5],
           "mid_titles": [e["rep"] + "（" + "、".join(name_of.get(x, x) for x in e["srcs"][:3]) + "）"
                          for e in events if e["tier"] == "注意"][:5]},
          open(LATEST, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
try:
    if os.path.exists(CHROME):
        subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-first-run",
                        "--no-pdf-header-footer",
                        "--user-data-dir=" + os.path.join(HERE, "chrome-prof"),
                        "--print-to-pdf=" + OUT_PDF,
                        "file:///" + OUT_HTML.replace("\\", "/")],
                       capture_output=True, timeout=240)
        print("PDF 已更新")
except Exception as e:
    print("PDF 產生失敗:", str(e)[:120])

print("更新時間", DATA["ts"])
print("來源 %d/%d 成功；報導 %d 則 → 聚合為 %d 個事件（警示 %d／注意 %d／緩和 %d）"
      % (len(ok_src), len(src_meta), len(uniq), NE, n_hi, n_mid, n_cal))
print("其中 %d 個事件有 2 家以上報導；佔比 %d%% → %s" % (multi, heat, level))
if pla_latest:
    print("共機／共艦：%s 公布　機 %s 架次、艦 %s 艘次、公務船 %s 艘次（%d 則報導一致）"
          % (pla_latest["day"], pla_latest.get("air"), pla_latest.get("ship"),
             pla_latest.get("official"), pla_latest.get("n", 0)))
    print("累積 %d 天；可配對的日期 %d 天；皮爾森 r = %s"
          % (len(pla_series), PLA["n_pairs"], ("%.3f" % PLA["r"]) if PLA["r"] is not None else "尚無法計算"))
if pla_err:
    print("共機／共艦 抓取警告:", pla_err)
print("各來源:", ", ".join("%s=%d" % (s["name"], s["n"]) for s in src_meta))
print("\n--- 最大的聚合群（檢查有沒有過度合併）---")
for e in sorted(events, key=lambda x: -len(x["members"]))[:5]:
    if len(e["members"]) < 2:
        break
    print("・(%d 則) [%s] %s" % (len(e["members"]), e["tier"], e["rep"][:70]))
    for j in e["members"][1:7]:
        print("      ← %s ｜ %s" % (name_of.get(uniq[j]["s"], "?"), uniq[j]["t"][:64]))
print("\n--- 其他聚合群抽樣 ---")
for e in [x for x in events if len(x["members"]) > 1][:6]:
    print("・[%s] (%d 則) %s" % (e["tier"], len(e["members"]), e["rep"][:70]))
if errors:
    print("失敗/警告 %d 筆:" % len(errors), "; ".join(errors[:6]))
