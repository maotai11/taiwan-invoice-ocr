# Taiwan Invoice OCR

台灣發票離線 OCR 辨識桌面工具
支援電子發票、統一發票圖片／PDF，自動抽取欄位並匯出 Excel。

---

## 下載與安裝（離線電腦適用）

前往 **[Releases 頁面](https://github.com/maotai11/taiwan-invoice-ocr/releases/latest)** 下載以下檔案：

### 必要下載（3 個檔案）

| 檔案 | 大小 | 說明 |
|---|---|---|
| `Taiwan.Invoice.OCR_x64-setup.exe` | ~150MB | **主程式安裝檔**，雙擊安裝 |
| `Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf` | ~1.8GB | Qwen 語言模型（辨識公司名稱用）|
| `mmproj-Qwen2.5-VL-3B-Instruct-f16.gguf` | ~1.3GB | Qwen 視覺模型（多模態辨識用）|

> **ocr_models 不需要另外下載** — 已內建在安裝檔中。

---

## 安裝步驟

**Step 1 — 安裝主程式**
```
雙擊 Taiwan.Invoice.OCR_x64-setup.exe → 下一步完成安裝
```

**Step 2 — 放置 Qwen 模型檔**

將下載的兩個 `.gguf` 檔放到以下路徑：
```
C:\Program Files\Taiwan Invoice OCR\models\qwen25vl3b\
    Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf
    mmproj-Qwen2.5-VL-3B-Instruct-f16.gguf
```

> 若找不到安裝路徑，在桌面捷徑按右鍵 → 「開啟檔案位置」即可找到。

**Step 3 — 啟動**
```
雙擊桌面捷徑「Taiwan Invoice OCR」
```

---

## 功能說明

| 功能 | 說明 |
|---|---|
| 匯入檔案 | 支援 JPG / PNG / PDF / WEBP / TIFF |
| 自動辨識 | PaddleOCR 抓數字／統編／發票號碼；Qwen Vision 抓公司名稱 |
| UBN 記憶 | 手動修正公司名稱後勾選「記住」，下次同統編自動帶入 |
| 雙擊編輯 | 表格任一欄位可雙擊手動修正 |
| 匯出 Excel | 右上角「匯出 Excel」→ 選擇儲存路徑 |
| 重跑 OCR | 選取列後按「重跑 OCR」重新辨識 |

---

## 辨識欄位

| 欄位 | 辨識引擎 |
|---|---|
| 發票號碼、日期 | PaddleOCR + 正則 |
| 賣方／買方統編 | PaddleOCR + 台灣統編 checksum 驗證 |
| 銷售額、稅額、總計 | PaddleOCR（無幻覺風險）|
| 賣方／買方公司名稱 | UBN 記憶優先 → Qwen Vision |

---

## 不需要安裝

- ❌ Python
- ❌ 任何 pip 套件
- ❌ 網路連線

安裝完成後完全離線運作。

---

## 電腦規格建議

| 項目 | 最低 | 建議 |
|---|---|---|
| 作業系統 | Windows 10 64-bit | Windows 11 |
| RAM | 8 GB | 16 GB |
| 硬碟空間 | 6 GB（含模型）| 10 GB |
| CPU | 4 核心 | 8 核心（Qwen 推論較快）|

---

## 目錄結構（安裝後）

```
C:\Program Files\Taiwan Invoice OCR\
  taiwan-invoice-ocr.exe
  config\
    ocr_config.json
  ocr_models\
    det\  rec\  cls\          ← PaddleOCR 模型（已內建）
  models\
    qwen25vl3b\
      Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf    ← 手動放置
      mmproj-Qwen2.5-VL-3B-Instruct-f16.gguf ← 手動放置
  scripts\
    ocr_pipeline.py
```
