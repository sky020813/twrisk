# -*- coding: utf-8 -*-
"""台海風險指標追蹤表 — 自動更新器（多來源版）

抓取 29 個全球權威媒體 + 台灣媒體的台海相關報導：
  * 有原生 RSS 的來源優先走 RSS（不經 Google）
  * 沒有 RSS 的（Reuters/AP/FT/Economist…）走 Google News 的 site: 查詢
每則報導標上「來源 id + 關鍵詞分級」，結果內嵌進 HTML。
評分（嚴重度佔比、層級）在瀏覽器端依「使用者勾選的來源」即時計算。
"""
import json, os, re, ssl, subprocess, time, urllib.request, urllib.parse, xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta

HERE      = os.path.dirname(os.path.abspath(__file__))
# 輸出位置可用環境變數覆寫：本機預設桌面，雲端 CI（GitHub Actions）可指向 repo 內的 index.html
OUT_HTML  = os.environ.get("TWRISK_HTML", r"C:\Users\Kai\Desktop\台海風險指標追蹤表.html")
OUT_PDF   = os.environ.get("TWRISK_PDF",  r"C:\Users\Kai\Desktop\台海風險指標追蹤表.pdf")
HIST_JSON = os.environ.get("TWRISK_HIST", os.path.join(HERE, "twrisk_history.json"))
LATEST    = os.path.join(HERE, "latest.json")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
TW = timezone(timedelta(hours=8))

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

# ============ 關鍵詞分級（英文一律加詞界，避免 awareness→war、罷工/地震→strike）============
TIER = [
    ("警示", [
        (r"核武|核彈|nuclear (weapon|strike|war)", "核武"),
        (r"封鎖|blockad", "封鎖"),
        (r"入侵|invasi", "入侵"),
        (r"登陸|amphibious|beach ?head", "登陸"),
        (r"開戰|宣戰|declare war", "開戰"),
        (r"撤僑|evacuat", "撤僑"),
        (r"動員|mobilis|mobiliz", "動員"),
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

RELEVANT = ["台海", "台灣", "臺灣", "共軍", "解放軍", "習近平", "台北", "兩岸", "中共",
            "taiwan", "taipei", "pla ", "beijing", "cross-strait", "strait", "china"]


def gnews(domain, term, days, lang):
    if lang == "zh":
        hl, gl, ceid = "zh-TW", "TW", "TW:zh-Hant"
    else:
        hl, gl, ceid = "en-US", "US", "US:en"
    q = "site:%s %s when:%dd" % (domain, term, days)
    return ("https://news.google.com/rss/search?q=" + urllib.parse.quote(q)
            + "&hl=" + hl + "&gl=" + gl + "&ceid=" + ceid)


def fetch(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "application/rss+xml,application/xml,text/xml,*/*"})
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


def relevant(text):
    low = text.lower()
    return any(k.lower() in low for k in RELEVANT)


now = datetime.now(TW)
arts, src_meta, errors = [], [], []

for sid, name, cat, domain, lang, rss in SOURCES:
    got, via = [], ""
    if rss:                                    # 1) 原生 RSS 優先
        try:
            got = [x for x in parse(fetch(rss)) if relevant(x["title"])]
            if got:
                via = "rss"
        except Exception as e:
            errors.append("%s(rss): %s" % (name, str(e)[:70]))
        time.sleep(0.8)
    if not got:                                # 2) 沒有 RSS 或 RSS 失敗 → Google News
        term = "台海" if lang == "zh" else "Taiwan"
        days = 3 if lang == "zh" else 7
        try:
            got = [x for x in parse(fetch(gnews(domain, term, days, lang))) if relevant(x["title"])]
            if got:
                via = "gnews"
        except Exception as e:
            errors.append("%s(gnews): %s" % (name, str(e)[:70]))
        time.sleep(1.2)

    got = got[:40]
    src_meta.append({"id": sid, "name": name, "cat": cat, "n": len(got), "via": via,
                     "ok": bool(got), "url": "https://" + domain})
    for x in got:
        k, w = tier_of(x["title"])
        arts.append({"t": x["title"], "l": x["link"], "s": sid, "k": k, "w": w, "p": (x["pub"] or "")[:22]})

seen, uniq = set(), []                          # 去重（同標題只留一則）
for a in arts:
    key = re.sub(r"\W+", "", a["t"].lower())[:60]
    if key in seen:
        continue
    seen.add(key); uniq.append(a)

c_hi  = sum(1 for a in uniq if a["k"] == "警示")
c_mid = sum(1 for a in uniq if a["k"] == "注意")
c_cal = sum(1 for a in uniq if a["k"] == "緩和")
N = len(uniq)
heat = round(100.0 * (c_hi * 3 + c_mid) / (3.0 * max(1, N)))
if   c_hi >= 8 and heat >= 20: level = "高"
elif c_hi >= 4 and heat >= 12: level = "升高"
elif c_hi >= 1 or heat >= 6:   level = "注意"
else:                          level = "相對平穩"

ok_src = [s for s in src_meta if s["ok"]]

hist = []
if os.path.exists(HIST_JSON):
    try:
        hist = json.load(open(HIST_JSON, encoding="utf-8"))
    except Exception:
        hist = []
hist.append({"ts": now.strftime("%Y-%m-%d %H:%M"), "n": N, "hi": c_hi, "mid": c_mid, "heat": heat,
             "level": level, "src_ok": len(ok_src), "src_all": len(src_meta)})
hist = hist[-90:]
json.dump(hist, open(HIST_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

uniq.sort(key=lambda a: a["p"], reverse=True)
DATA = {"ts": now.strftime("%Y-%m-%d %H:%M"), "sources": src_meta, "arts": uniq,
        "errors": errors[:12], "hist": hist[-14:]}

tpl = open(os.path.join(HERE, "template.html"), encoding="utf-8").read()
open(OUT_HTML, "w", encoding="utf-8").write(tpl.replace("/*__DATA__*/", json.dumps(DATA, ensure_ascii=False)))

name_of = {s["id"]: s["name"] for s in src_meta}
json.dump({"ts": DATA["ts"], "level": level, "heat": heat, "n": N, "hi": c_hi, "mid": c_mid,
           "hi_titles":  [a["t"] + "（" + name_of.get(a["s"], a["s"]) + "）" for a in uniq if a["k"] == "警示"][:5],
           "mid_titles": [a["t"] + "（" + name_of.get(a["s"], a["s"]) + "）" for a in uniq if a["k"] == "注意"][:5]},
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
    else:
        print("找不到 Chrome，略過 PDF")
except Exception as e:
    print("PDF 產生失敗:", str(e)[:120])

print("更新時間", DATA["ts"])
print("來源 %d/%d 成功；抓到 %d 則（警示 %d／注意 %d／緩和 %d）；佔比 %d%% → %s"
      % (len(ok_src), len(src_meta), N, c_hi, c_mid, c_cal, heat, level))
print("各來源:", ", ".join("%s=%d(%s)" % (s["name"], s["n"], s["via"] or "-") for s in src_meta))
if errors:
    print("失敗/警告 %d 筆:" % len(errors), "; ".join(errors[:8]))
print("已寫入:", OUT_HTML)
