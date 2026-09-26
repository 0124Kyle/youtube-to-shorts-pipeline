# YouTube → 原創短影音：單指令流程

輸入一支 YouTube 影片網址，程式會自動取得音訊、在本機轉錄、挑選並改寫數個不同片段、搜尋並下載直式實拍素材，最後輸出帶來源標示及下方置中白色字幕的 9:16 **靜音審稿影片**。字幕依文字長度安排閱讀時間，沒有旁白或素材原音；不需語音 API 金鑰。素材搜尋與分鏡由腳本引導；無須逐支輸入 Pexels ID 或填素材標籤。輸出仍需人工核對事實、授權和畫面是否貼題，**不能視為已審核可直接發布**。

## 首次安裝（Windows PowerShell）

需要 Python 3.10+、`ffmpeg`、`ffprobe`、網路，以及 Gemini、Pexels 金鑰。先確認 `ffmpeg -version` 和 `ffprobe -version` 能執行；若尚未安裝 FFmpeg，可執行 `winget install --id Gyan.FFmpeg --exact --source winget` 並重新開啟終端機。

在**解壓後的專案根目錄**執行以下指令。直接呼叫虛擬環境的 Python，不需執行 PowerShell 啟用腳本：

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
notepad .env
```

如果從 GitHub 下載，請在專案根目錄新建 `.env`，並填入以下兩行；若使用下載的專案壓縮檔，則直接修改其中現成的 `.env`。`.env` 已被 `.gitignore` 排除，不會上傳到 GitHub。

```dotenv
GEMINI_API_KEY=填入你自己的金鑰
PEXELS_API_KEY=填入你自己的金鑰
```

如果你已經有填好金鑰的 `.env`，更新程式時保留原檔，不要用壓縮檔內的示意值覆蓋。不要分享 `.env`。首次下載或轉錄失敗時，若 yt-dlp 提示缺少 JavaScript runtime，另安裝 Node.js 或 Deno。

如果畫面說缺少套件，先用**同一個虛擬環境 Python**執行以下只讀檢查；它不會下載影片或呼叫付費 API：

```powershell
.\.venv\Scripts\python.exe run_pipeline.py --check
.\.venv\Scripts\python.exe -m pip --version
```

檢查結果會顯示實際 Python 路徑及缺少的模組。安裝與正式執行都要以 `.\.venv\Scripts\python.exe` 開頭；`py run_pipeline.py` 可能選用另一個 Python，導致「已安裝仍找不到套件」。

## 執行完整流程

```powershell
.\.venv\Scripts\python.exe run_pipeline.py --url "https://www.youtube.com/watch?v=KjAI9r8tnOs"
```

預設產生 **2 支**靜音審稿短影音，字幕閱讀速度係數為 `1.12`。如果只想先驗證一支並降低請求數，可加 `--count 1`；最多可用 `--count 3`。重跑相同網址與參數會重用已有輸出。若帳號無法使用預設 Gemini 模型，執行 `.\.venv\Scripts\python.exe check_models.py`，從清單挑一個支援文字生成的模型，在主指令後加 `--model 模型名稱`；換模型會產生新的 API 請求。

輸出在 `data/auto-shorts/KjAI9r8tnOs/`，檔名以 `_preview.mp4` 結尾；來源音訊、逐字稿、候選規劃及改寫腳本在 `data/KjAI9r8tnOs/`；各短片的素材來源、分鏡（選用旁白時還有語音快取）在 `data/auto-live/KjAI9r8tnOs/<候選ID>/`。素材來源記錄為 `footage_sources.json`，包含 Pexels 頁面與作者。程式若找不到適合的直式影片會停止並顯示對應的搜尋詞，不會自行用原始新聞畫面充數。

完成後逐支觀看，核對原來源與數字、字幕閱讀時間，以及素材畫面與授權。`review_status: needs_human_review` 表示只能用來審稿。需要檢查程式時執行 `.\.venv\Scripts\python.exe -m unittest discover -s tests -v`；測試使用模擬 API 回應，不會向雲端發出付費請求。

## 工具選擇與成本假設

| 步驟 | 選擇與控制成本的原因 |
| --- | --- |
| 擷取與轉錄 | `yt-dlp` 只下載音訊；`faster-whisper` 在本機轉錄，省去逐分鐘的雲端轉錄費，但使用你的網路、CPU 和磁碟。相同影片與轉錄設定會重用逐字稿。 |
| 挑選與改寫 | 本機先對不同時間窗評分，預設只選 2 段呼叫 Gemini，不會把整支影片的每句話都送去改寫。提示與模型的成功回應依雜湊快取；`candidates.json` 記錄估計的付費等值成本，實際依你的模型、額度和用量而異。 |
| 實拍素材 | 對每支腳本產生 2–3 個場景搜尋詞；每個場景至多做 2 次 Pexels 搜尋、最多下載 1 段影片。預設 2 支影片，整輪最多約 12 次搜尋及 6 段影片下載；搜尋回應快取 24 小時，影片重用。Pexels 有使用與 API 條款，審稿時須檢查。 |
| 字幕與影片 | 依字幕字數估計閱讀時間；FFmpeg 在本機剪輯、編碼，不呼叫語音 API，也不使用雲端影片生成。|

原報導只用於取材和核對；模型需改寫句構及敘事，影片字幕與畫面會標出原來源。程式會提示人工檢查連續相同文字和數字；如果需要數據圖表，應用已查證數據以程式重繪，不能使用新聞原片的圖表截圖。模型產生的搜尋詞和自動選到的影片也可能不貼題，公開前必須審查。

官方文件：[Pexels API](https://www.pexels.com/api/documentation/)、[Pexels 授權](https://www.pexels.com/license/)、[Gemini 定價](https://ai.google.dev/gemini-api/docs/pricing)
