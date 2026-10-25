# 台海風險指標追蹤表（網站版）

一個靜態網頁：每天自動抓 29 家權威媒體的台海相關報導，依用語嚴重度換算風險讀數。
**訪客可自己勾選要採用哪些來源**，所有數字即時重算。

## 內容
```
index.html                      ← 網頁本體（資料已內嵌，不須後端）
scripts/update.py               ← 抓取 + 評分 + 產生 index.html
scripts/template.html           ← 版面
scripts/twrisk_history.json     ← 每次更新的歷史數字
.github/workflows/daily.yml     ← 每天台北 08:00 自動跑一次並提交
```

## 部署步驟（約 3 分鐘）
1. 到 GitHub 建一個新的 **Public** repo，名稱例如 `twrisk`。
2. 把這個資料夾的**全部內容**上傳（含隱藏的 `.github` 資料夾）。
   - 用網頁上傳：`Add file` → `Upload files`，把整個資料夾拖進去。
     **注意**：GitHub 網頁拖曳不會帶入 `.github/workflows/`，需改用下面任一方式。
   - 或用命令列：
     ```bash
     cd twrisk-site
     git init && git add -A && git commit -m "init"
     git branch -M main
     git remote add origin https://github.com/<你的帳號>/twrisk.git
     git push -u origin main
     ```
3. repo → **Settings → Pages** → Source 選 `Deploy from a branch`，
   Branch 選 `main` / 資料夾 `/(root)` → Save。
4. 等 1～2 分鐘，網址就是 `https://<你的帳號>.github.io/twrisk/`。
5. repo → **Actions** 頁籤 → 選 `每日更新台海風險追蹤表` → `Run workflow`，
   手動跑一次確認可以自動更新。

## 為什麼選 GitHub Pages
- 免費、沒有流量上限壓力、自帶 HTTPS。
- 內建 **Actions 排程**：每天在雲端跑一次抓取並提交，**不需要你的電腦開著**。
- 靜態網頁，不會因為後端掛掉而失效。

其他免費替代：Cloudflare Pages、Netlify、Vercel（都免費、都支援拖曳上傳，
但**沒有內建排程**，要自己接 CI 或本機推送）。

## 授權與注意
- 本頁僅顯示**標題與連結**，不重製內文；連結導向原站。
- 部分媒體（Reuters/AP/FT/The Economist 等）沒有公開 RSS，標題經 Google News 取得，
  點擊會先經過 Google 再轉到原站，部分內容有付費牆。
- 這是觀察工具，**不是預測**，也不代表任何政治立場。
