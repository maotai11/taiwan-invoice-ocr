# Taiwan Invoice OCR — 系統升級計畫書 v2.0

## 整體架構目標

```
目前架構：
  圖片 → PaddleOCR(文字) → 正則抽欄位 → Qwen Vision(名稱補強) → 表格

目標架構：
  圖片 → [分類器] 判斷發票類型
        ↓ 同類型有已學習 Template Region
        ├── 裁切精準區域 → PaddleOCR / Qwen 精準識別
        └── 無 Template → Qwen Vision(全欄位) + PaddleOCR(數字交叉驗證)
                                        ↓
                             UBN 記憶(v2) 補強名稱
                                        ↓
                             信心分數 + Review 旗標 → 表格
```

---

## Phase 1 — OCR 引擎重設計

### 目標
- Qwen Vision 辨識全欄位（發票號碼、日期、統編、金額、名稱）
- PaddleOCR + TrOCR 作為數字欄位的交叉驗證層
- 不匹配 → `review` 旗標 + 顯示兩組數值供使用者決定

### 1.1 Python 端 (`scripts/ocr_pipeline.py`)

**新增 `cross_validate_numbers()` 函式：**
```python
def cross_validate_numbers(qwen_result: dict, paddle_result: dict) -> dict:
    """
    比較 Qwen 和 PaddleOCR 對數字欄位的結果。
    fields: invoice_no, date, seller_ubn, buyer_ubn, sales_amount, tax, total
    回傳: { field: { value, confidence, mismatch: bool, paddle_val } }
    """
    NUMBER_FIELDS = ["invoice_no", "seller_ubn", "buyer_ubn", "sales_amount", "tax", "total"]
    result = {}
    for field in NUMBER_FIELDS:
        q_val = qwen_result.get(field, "")
        p_val = paddle_result.get(field, "")
        mismatch = bool(q_val and p_val and q_val != p_val)
        result[field] = {
            "value": q_val or p_val,
            "paddle_value": p_val,
            "mismatch": mismatch,
            "confidence": 0.6 if mismatch else (0.95 if q_val else 0.5)
        }
    return result
```

**修改 Pipeline 主流程：**
```python
# 1. PaddleOCR 全文
paddle_text = run_paddle_ocr(image_path)
paddle_fields = extract_fields_from_text(paddle_text)

# 2. Qwen Vision 全欄位（新版 prompt 改為結構化 JSON 輸出）
qwen_fields = run_qwen_vision_all_fields(image_path)

# 3. 數字交叉驗證
validated = cross_validate_numbers(qwen_fields, paddle_fields)

# 4. UBN 記憶補強
apply_ubn_memory(validated)

# 5. 組合最終結果 + review flags
```

**新版 Qwen prompt（結構化輸出）：**
```python
QWEN_FULL_PROMPT = """請辨識這張台灣發票，以 JSON 格式回傳以下欄位：
{
  "invoice_no": "發票號碼（2字母+8數字，如AB12345678）",
  "date": "日期（民國年/月/日，如113/05/20）",
  "seller_name": "賣方公司名稱",
  "seller_ubn": "賣方統一編號（8位數字）",
  "buyer_name": "買方公司名稱（若無則空字串）",
  "buyer_ubn": "買方統一編號（若無則空字串）",
  "sales_amount": "銷售額（純數字）",
  "tax": "稅額（純數字）",
  "total": "總計金額（純數字）"
}
只回傳 JSON，不要其他說明。"""
```

### 1.2 Rust 端新增型別 (`src-tauri/src/types.rs`)

```rust
#[derive(Serialize, Deserialize, Clone)]
pub struct CrossValidation {
    pub field: String,
    pub qwen_value: String,
    pub paddle_value: String,
    pub mismatch: bool,
    pub confidence: f32,
}

#[derive(Serialize, Deserialize, Clone)]
pub struct InvoiceRow {
    // ... 現有欄位 ...
    pub review: bool,              // 需要人工確認
    pub cross_validations: Vec<CrossValidation>,
    pub confidence_scores: HashMap<String, f32>,
}
```

### 1.3 前端 Review 旗標顯示 (`src/App.vue`)

- 表格列若 `review == true`，列底色顯示淡黃 `#fffbe6`
- `review` 欄位顯示 ⚠️ 圖示，hover 展開不匹配詳情

---

## Phase 2 — 發票類型分類器

### 台灣發票六大類型

| 類型 | 說明 | 關鍵特徵 |
|---|---|---|
| `三聯式` | 一般稅額計算用統一發票 | 賣方統編、買方統編、稅額欄 |
| `二聯式` | 小規模零售 | 只有賣方統編、無稅額分列 |
| `電子發票` | 財政部電子雲端發票 | "電子發票證明聯"字樣、條碼 |
| `收銀機` | 商店收銀機統一發票 | 收銀機字樣、品項列表 |
| `特種` | 特種稅額發票 | 特種統一發票字樣 |
| `手開` | 手寫發票 | 無列印痕跡、手寫筆跡 |

### 2.1 設定檔 (`config/keyword_weights.json`)

```json
{
  "三聯式": {
    "keywords": {
      "三聯式": 10,
      "買方統一編號": 8,
      "銷售額": 5,
      "稅額": 5,
      "買受人": 4
    },
    "min_score": 8
  },
  "電子發票": {
    "keywords": {
      "電子發票": 10,
      "證明聯": 8,
      "隨機碼": 6,
      "條碼": 3
    },
    "min_score": 10
  },
  "收銀機": {
    "keywords": {
      "收銀機": 10,
      "品名": 4,
      "數量": 4,
      "單價": 4
    },
    "min_score": 8
  },
  "二聯式": {
    "keywords": {
      "二聯式": 10,
      "存根聯": 5,
      "收執聯": 5
    },
    "min_score": 6,
    "fallback": true
  }
}
```

### 2.2 分類模組 (`scripts/invoice_classifier.py`)

```python
import json, re

def classify_invoice(ocr_text: str, keyword_weights_path: str) -> tuple[str, float]:
    """
    回傳 (invoice_type, confidence_score)
    """
    with open(keyword_weights_path) as f:
        weights = json.load(f)

    scores = {}
    for inv_type, config in weights.items():
        score = 0
        for kw, w in config["keywords"].items():
            if kw in ocr_text:
                score += w
        scores[inv_type] = score

    # 找最高分
    best_type = max(scores, key=scores.get)
    best_score = scores[best_type]
    min_score = weights[best_type].get("min_score", 5)

    if best_score >= min_score:
        confidence = min(best_score / (min_score * 2), 1.0)
        return best_type, confidence

    # fallback
    fallback = next((t for t, c in weights.items() if c.get("fallback")), "未知")
    return fallback, 0.3
```

### 2.3 整合到 Pipeline

```python
# 在 PaddleOCR 取得全文後
invoice_type, type_confidence = classify_invoice(paddle_text, keyword_weights_path)
result["invoice_type"] = invoice_type
result["type_confidence"] = type_confidence
```

---

## Phase 3 — Template Region Learning（位置記憶）

### 設計概念
當某類型發票 OCR 失敗時，使用者在圖片上框選欄位位置 → 系統記住相對百分比座標 → 未來同類型發票自動裁切精準區域送 OCR

### 3.1 資料格式 (`data/templates.json`)

```json
{
  "三聯式": {
    "version": 1,
    "created": "2025-01-01",
    "regions": {
      "invoice_no":    {"x": 0.55, "y": 0.05, "w": 0.30, "h": 0.06},
      "date":          {"x": 0.55, "y": 0.11, "w": 0.30, "h": 0.06},
      "seller_ubn":    {"x": 0.05, "y": 0.15, "w": 0.35, "h": 0.06},
      "buyer_ubn":     {"x": 0.05, "y": 0.22, "w": 0.35, "h": 0.06},
      "total":         {"x": 0.55, "y": 0.75, "w": 0.35, "h": 0.07}
    }
  }
}
```

### 3.2 Rust 命令 (`src-tauri/src/template.rs`)

```rust
#[tauri::command]
pub async fn save_template_region(
    invoice_type: String,
    field: String,
    region: RegionRect,    // {x, y, w, h} 相對比例
) -> Result<(), AppError> { ... }

#[tauri::command]
pub async fn get_templates() -> Result<HashMap<String, InvoiceTemplate>, AppError> { ... }

#[tauri::command]
pub async fn delete_template_region(
    invoice_type: String,
    field: String,
) -> Result<(), AppError> { ... }
```

### 3.3 前端 `RegionSelector.vue`

```
┌─────────────────────────────────────────┐
│  [圖片預覽區域]                          │
│                                         │
│  ╔══════════╗  ← 使用者拖曳選取框        │
│  ║ 發票號碼 ║    半透明藍色遮罩          │
│  ╚══════════╝                           │
│                                         │
│  欄位：[發票號碼 ▼]  [儲存此區域] [取消] │
└─────────────────────────────────────────┘
```

- Canvas 上監聽 `mousedown` / `mousemove` / `mouseup`
- 拖曳結束 → 計算相對比例 → 呼叫 `save_template_region`
- 已學習區域顯示為半透明色框標示（不同欄位不同顏色）

---

## Phase 4 — 記憶系統 v2

### 現有格式（v1）
```json
{ "12345678": "台積電股份有限公司" }
```

### 新格式（v2）
```json
{
  "12345678": {
    "name": "台積電股份有限公司",
    "invoice_type": "三聯式",
    "use_count": 15,
    "last_seen": "2025-05-20",
    "aliases": ["台積電", "TSMC"]
  }
}
```

### 4.1 Rust 記憶模組 (`src-tauri/src/memory.rs`)

```rust
pub struct MemoryEntry {
    pub name: String,
    pub invoice_type: Option<String>,
    pub use_count: u32,
    pub last_seen: String,     // ISO date
    pub aliases: Vec<String>,
}

pub async fn save_memory_entry_v2(
    ubn: String,
    name: String,
    invoice_type: Option<String>,
) -> Result<(), AppError> {
    // 讀取現有 → 更新 use_count + last_seen → 寫回
}

pub async fn migrate_v1_to_v2(memory_path: &Path) -> Result<(), AppError> {
    // 若 value 為 String（v1），轉為 MemoryEntry（v2）
}
```

### 4.2 模糊比對（近似公司名稱）

使用 Levenshtein 距離或 bigram 相似度，供使用者輸入不完整名稱時仍能搜到：
```rust
fn similarity_score(a: &str, b: &str) -> f32 {
    // bigram overlap
}
```

- 搜尋時若輸入名稱與記憶中某條目相似度 > 0.7 → 提示使用者「您是否要找：XXX（統編 YYYYYYYY）？」

---

## Phase 5 — 前端 UX 升級

### 5.1 新增元件

**`src/components/InvoiceTypeBadge.vue`**
```html
<span :class="`badge badge-${invoiceType}`">{{ invoiceType }}</span>
```
- 六種類型各有顏色徽章（三聯式=藍、電子發票=綠、收銀機=橘...）

**`src/components/ConfidenceBar.vue`**
```
信心值: ████████░░ 80%
```
- 分欄位顯示辨識信心分數（hover 展開）

**`src/components/TemplateManager.vue`**
- 列出所有已學習的 Template Region
- 可刪除單一欄位或整個類型的記憶
- 顯示各欄位座標百分比

### 5.2 更新型別定義 (`src/types/index.ts`)

```typescript
export interface CrossValidation {
  field: string
  qwenValue: string
  paddleValue: string
  mismatch: boolean
  confidence: number
}

export interface InvoiceRow {
  // ... 現有欄位 ...
  invoiceType: string
  typeConfidence: number
  review: boolean
  crossValidations: CrossValidation[]
  confidenceScores: Record<string, number>
}

export interface RegionRect {
  x: number; y: number; w: number; h: number
}

export interface InvoiceTemplate {
  version: number
  created: string
  regions: Record<string, RegionRect>
}
```

### 5.3 主視窗調整 (`src/App.vue`)

- 表格新增「類型」欄（顯示 InvoiceTypeBadge）
- 表格列若 `review == true`：底色 `#fffbe6`，⚠️ 圖示
- 右上角增加「範本管理」按鈕 → 開啟 TemplateManager
- 選取列後「標記範本」按鈕 → 開啟 RegionSelector（傳入對應圖片路徑）
- 信心分數 Tooltip：hover 欄位顯示 ConfidenceBar

---

## 實作順序與分批計畫

### Batch A（核心引擎，約 1-2 天）
1. `scripts/invoice_classifier.py` + `config/keyword_weights.json`
2. `scripts/ocr_pipeline.py`：Qwen 全欄位 prompt + `cross_validate_numbers()`
3. `src-tauri/src/types.rs`：新增 CrossValidation、更新 InvoiceRow
4. Pipeline 整合測試

### Batch B（記憶系統，約 0.5 天）
1. `src-tauri/src/memory.rs`：v2 格式 + 遷移函式
2. 更新 `commands.rs` 中的 `save_memory_entry` 命令
3. `src/utils/tauri.ts`：更新 API

### Batch C（Template Region，約 1-2 天）
1. `data/templates.json` 格式定義
2. `src-tauri/src/template.rs`：3 個 Tauri 命令
3. `src/components/RegionSelector.vue`：Canvas 拖曳 UI
4. Python 端：讀取 templates.json → 精準裁切圖片區域送 OCR

### Batch D（前端 UX，約 1 天）
1. `src/components/InvoiceTypeBadge.vue`
2. `src/components/ConfidenceBar.vue`
3. `src/components/TemplateManager.vue`
4. `src/App.vue`：整合所有新元件、review 高亮、類型欄位

---

## 版本號規劃

| 版本 | 內容 |
|---|---|
| v0.2.0 | 目前版本（PaddleOCR + Qwen 名稱 + UBN 記憶 + Excel 匯出）|
| v0.3.0 | Batch A+B（Qwen 全欄位 + 交叉驗證 + 分類器 + 記憶 v2）|
| v0.4.0 | Batch C（Template Region Learning）|
| v1.0.0 | Batch D（完整 UX + 所有功能穩定）|
