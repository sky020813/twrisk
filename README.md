# 台海風險指標追蹤表（網站版）

一個靜態網頁：每天自動抓 29 家權威媒體的台海相關報導，**把同一事件聚合**後依用語嚴重度換算風險讀數。
**訪客可自己勾選要採用哪些來源**，所有數字即時重算。

> **為什麼要聚合**：同一件事常被十家媒體各寫一則標題。若逐則計分，被廣泛報導的事件
> 會把數字整個拉偏。本表以「事件」為單位計分——標題正規化（去來源後綴、去標點、轉小寫）
> → 特徵（英文詞 + 中文雙字）→ Jaccard 相似度 ≥ 0.34 歸為同一事件，每件只算一次。
> 已知限制：**跨語言不會聚合**（英文與中文講同一件事仍是兩件），標題用詞差異極大時也不會。

## 內容
```
index.html                      ← 網頁本體（資料已內嵌，不須後端）
scripts/update.py               ← 抓取 + 評分 + 產生 index.html
scripts/template.html           ← 版面
scripts/twrisk_history.json     ← 每次更新的歷史數字
.github/workflows/daily.yml     ← 每天台北 08:00 抓取「並直接部署」
```

## 部署步驟（約 10 分鐘）

### 1. 建 repo
https://github.com/new → 名稱 `twrisk` → 選 **Public** → 不要初始化任何檔案 → Create。

> GitHub Free 方案的 Pages **只支援公開 repo**；私有 repo 要 Pro 以上。

### 2. 上傳檔案
在空 repo 點 `uploading an existing file`，把 `index.html`、`README.md`、`scripts\` 拖進去，Commit。

⚠️ **拖曳不會帶入 `.github` 資料夾**（點開頭會被 GitHub 忽略），workflow 要手動建，見第 3 步。

### 3. 建立 workflow
repo → `Add file` → **`Create new file`** → 在檔名欄位輸入：
```
.github/workflows/daily.yml
```
（打 `/` 會自動變成資料夾）→ 貼上本專案 `.github/workflows/daily.yml` 的內容 → Commit changes。

### 4. 開啟 Pages ← 關鍵：來源要選 GitHub Actions
repo → **Settings** → 左側 **Code, planning, and automation** 區塊 → 點 **Pages**
→ 「Build and deployment」→ Source 選 **`GitHub Actions`**
→ **不要**選 `Deploy from a branch`（原因見下）→ 選完即生效，不需按 Save。

### 5. 觸發第一次部署
`Actions` 頁籤 → 左側 `每日更新並部署台海風險追蹤表` → 右邊 **Run workflow**。
跑完後回 `Settings → Pages`，上方會出現網址，點 **Visit site**：
```
https://<你的帳號>.github.io/twrisk/
```

之後每天台北 08:00 會自動抓取並重新部署，**你的電腦不用開著**。

## 為什麼不用「Deploy from a branch」
GitHub 官方文件明確說明：

> Commits pushed by a GitHub Actions workflow that uses the `GITHUB_TOKEN` do not trigger a GitHub Pages build.

所以「workflow 改檔案 → push → Pages 自動重建」這條路**不會生效**，網站會永遠停在第一版。
把「產生」與「部署」放進同一支 workflow（本專案做法）才是正解。

## 兩個可能的問題
1. **雲端 IP 可能被 Google News 擋。** 一半來源靠 Google News（Reuters/AP/FT/The Economist 沒有公開 RSS）。
   若 Actions log 顯示大量來源失敗，告訴我，我改成以原生 RSS 為主的版本。
2. **首次部署要等 1–10 分鐘。** 出現 404 先等，不要急著改設定。

## 為什麼選 GitHub Pages
- 免費、沒有流量上限壓力、自帶 HTTPS。
- 內建 **Actions 排程**：每天在雲端跑一次抓取並直接部署，**不需要你的電腦開著**。
- 靜態網頁，不會因為後端掛掉而失效。

其他免費替代：Cloudflare Pages、Netlify、Vercel（都免費、都支援拖曳上傳，
但**沒有內建排程**，要自己接 CI 或本機推送）。

## 授權與注意
- 本頁僅顯示**標題與連結**，不重製內文；連結導向原站。
- 部分媒體（Reuters/AP/FT/The Economist 等）沒有公開 RSS，標題經 Google News 取得，
  點擊會先經過 Google 再轉到原站，部分內容有付費牆。
- 這是觀察工具，**不是預測**，也不代表任何政治立場。
