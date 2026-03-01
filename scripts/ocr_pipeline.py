#!/usr/bin/env python
"""
Taiwan Invoice OCR Pipeline  v2.0
----------------------------------
Pipeline:
  1. PaddleOCR  → text lines (all fields, reliable on numbers)
  2. UBN memory → fill known company names instantly
  3. Qwen2.5-VL → multimodal: extract names from image (only if memory miss)
  4. Validation → UBN checksum, amount sanity
"""
import argparse
import base64
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class OcrLine:
    text: str
    confidence: float
    bbox: list[float]  # [x, y, w, h, rotation]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def to_bbox(points: list[list[float]]) -> list[float]:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    x_min, y_min = min(xs), min(ys)
    x_max, y_max = max(xs), max(ys)
    return [float(x_min), float(y_min), float(x_max - x_min), float(y_max - y_min), 0.0]


def resolve_path(raw: str, root: Path) -> Path:
    p = Path(raw)
    return p if p.is_absolute() else root / p


def validate_ubn(ubn: str) -> bool:
    """Taiwan 8-digit UBN checksum validation."""
    if not re.fullmatch(r"\d{8}", ubn):
        return False
    weights = [1, 2, 1, 2, 1, 2, 4, 1]
    total = sum((int(d) * w) // 10 + (int(d) * w) % 10 for d, w in zip(ubn, weights))
    return total % 10 == 0 or (ubn[6] == "7" and (total + 1) % 10 == 0)


def parse_date(raw: str) -> str | None:
    text = raw.replace(".", "/").replace("-", "/")
    m = re.search(r"(\d{3,4})/(\d{1,2})/(\d{1,2})", text)
    if not m:
        return None
    year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if year < 1911:
        year += 1911
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None
    return f"{year:04d}-{month:02d}-{day:02d}"


# ---------------------------------------------------------------------------
# PaddleOCR
# ---------------------------------------------------------------------------

def local_model_dirs() -> tuple[str, str, str]:
    os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
    root = Path(__file__).resolve().parent.parent
    det, rec, cls = root / "ocr_models" / "det", root / "ocr_models" / "rec", root / "ocr_models" / "cls"
    missing = [str(p) for p in [det, rec, cls] if not p.exists()]
    if missing:
        raise RuntimeError("Missing OCR model folders: " + ", ".join(missing))
    return str(det), str(rec), str(cls)


def run_paddle_ocr(image_path: str) -> list[OcrLine]:
    from paddleocr import PaddleOCR
    det, rec, cls = local_model_dirs()
    ocr = PaddleOCR(
        text_detection_model_dir=det,
        text_recognition_model_dir=rec,
        textline_orientation_model_dir=cls,
        use_textline_orientation=True,
    )
    raw = ocr.predict(image_path)
    lines: list[OcrLine] = []
    if not raw:
        return lines
    first = raw[0]
    for pts, text, conf in zip(
        first.get("dt_polys", []) or [],
        first.get("rec_texts", []) or [],
        first.get("rec_scores", []) or [],
    ):
        pt = pts.tolist() if hasattr(pts, "tolist") else pts
        lines.append(OcrLine(text=text.strip(), confidence=float(conf), bbox=to_bbox(pt)))
    return lines


# ---------------------------------------------------------------------------
# UBN Memory (data/ubn_memory.json)
# ---------------------------------------------------------------------------

def load_ubn_memory(project_root: Path) -> dict[str, str]:
    path = project_root / "data" / "ubn_memory.json"
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Qwen 2.5-VL Vision — names only (no numbers, avoids hallucination)
# ---------------------------------------------------------------------------

def run_qwen_vision_names(
    image_path: str,
    cfg: dict[str, Any],
    project_root: Path,
) -> tuple[str | None, str | None]:
    """Extract seller_name and buyer_name via Qwen2.5-VL multimodal."""
    if not cfg.get("enabled", False):
        return None, None

    model_path = resolve_path(cfg.get("model_path", ""), project_root)
    mmproj_path = resolve_path(cfg.get("mmproj_path", ""), project_root)

    if not model_path.exists():
        sys.stderr.write(f"[warn] Qwen model not found: {model_path}\n")
        return None, None
    if not mmproj_path.exists():
        sys.stderr.write(f"[warn] Qwen mmproj not found: {mmproj_path}\n")
        return None, None

    try:
        from llama_cpp import Llama
        from llama_cpp.llama_chat_format import Qwen2VLChatHandler

        ext = Path(image_path).suffix.lower().lstrip(".")
        mime = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "webp": "webp"}.get(ext, "jpeg")
        with open(image_path, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode()

        chat_handler = Qwen2VLChatHandler(clip_model_path=str(mmproj_path))
        llm = Llama(
            model_path=str(model_path),
            chat_handler=chat_handler,
            n_ctx=int(cfg.get("n_ctx", 2048)),
            n_threads=int(cfg.get("n_threads", 6)),
            verbose=False,
        )

        prompt = (
            "這是一張台灣電子發票或統一發票。"
            "請從圖片中找出賣方（銷售人）公司名稱和買方（購買人）公司名稱。"
            '只輸出 JSON，不要其他文字：{"seller_name": "名稱或null", "buyer_name": "名稱或null"}'
        )
        result = llm.create_chat_completion(
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/{mime};base64,{img_b64}"}},
                    {"type": "text", "text": prompt},
                ],
            }],
            temperature=0.1,
            max_tokens=80,
        )
        content = result["choices"][0]["message"]["content"]
        m = re.search(r"\{.*\}", content, re.DOTALL)
        if m:
            d = json.loads(m.group(0))
            seller = d.get("seller_name") or None
            buyer = d.get("buyer_name") or None
            # Reject if looks like hallucination (too short or generic)
            if seller and len(seller) < 2:
                seller = None
            if buyer and len(buyer) < 2:
                buyer = None
            return seller, buyer
    except Exception as e:
        sys.stderr.write(f"[warn] Qwen Vision failed: {e}\n")

    return None, None


# ---------------------------------------------------------------------------
# Field extraction (PaddleOCR text → structured fields)
# ---------------------------------------------------------------------------

def extract_fields(lines: list[OcrLine]) -> dict[str, Any]:
    texts = [line.text for line in lines]
    full = "\n".join(texts)
    full_upper = full.upper()

    # --- Invoice number ---
    inv_no = None
    m = re.search(r"\b([A-Z]{2})\s*[-—]?\s*(\d{8})\b", full_upper)
    if m:
        inv_no = f"{m.group(1)}{m.group(2)}"

    # --- Date ---
    inv_date = None
    for text in texts:
        d = parse_date(text)
        if d:
            inv_date = d
            break

    # --- UBN (with checksum validation) ---
    all_8digit = re.findall(r"\b\d{8}\b", full)
    valid_ubns = [u for u in all_8digit if validate_ubn(u)]

    seller_ubn = _find_ubn_near_keyword(texts, ["賣方", "銷售人", "賣方統編", "賣方統一編號"])
    buyer_ubn  = _find_ubn_near_keyword(texts, ["買方", "購買人", "買方統編", "買方統一編號"])
    if not seller_ubn and len(valid_ubns) >= 1:
        seller_ubn = valid_ubns[0]
    if not buyer_ubn and len(valid_ubns) >= 2:
        buyer_ubn = valid_ubns[1]

    # --- Company names (text-based fallback; Vision will override if enabled) ---
    seller_name = _find_name_near_keyword(texts, ["賣方", "銷售人", "賣方名稱"])
    buyer_name  = _find_name_near_keyword(texts, ["買方", "購買人", "買方名稱"])

    # --- Amounts (keyword-aware, PaddleOCR is reliable for numbers) ---
    net_amount, tax, total = _extract_amounts(texts, full)

    # --- Tax type ---
    tax_type = "Taxable"
    if "免稅" in full:
        tax_type = "TaxExempt"
    elif re.search(r"零稅率|0%稅率", full):
        tax_type = "ZeroTax"

    # --- Random code ---
    random_code = None
    m_rc = re.search(r"隨機碼[：:]\s*(\d{4})", full)
    if m_rc:
        random_code = m_rc.group(1)
    else:
        m_rc = re.search(r"\b(\d{4})\b", full)
        if m_rc:
            random_code = m_rc.group(1)

    return {
        "inv_no": inv_no,
        "inv_date": inv_date,
        "seller_ubn": seller_ubn,
        "seller_name": seller_name,
        "buyer_ubn": buyer_ubn,
        "buyer_name": buyer_name,
        "net_amount": net_amount,
        "tax": tax,
        "total": total,
        "tax_type": tax_type,
        "random_code": random_code,
        "qr_verified": False,
    }


def _find_ubn_near_keyword(texts: list[str], keywords: list[str]) -> str | None:
    for idx, text in enumerate(texts):
        if any(k in text for k in keywords):
            for source in [text] + texts[idx + 1: idx + 3]:
                for candidate in re.findall(r"\b\d{8}\b", source):
                    if validate_ubn(candidate):
                        return candidate
    return None


def _find_name_near_keyword(texts: list[str], keywords: list[str]) -> str | None:
    for idx, text in enumerate(texts):
        if any(k in text for k in keywords):
            # Check same line first (keyword: name on same line)
            rest = re.sub("|".join(re.escape(k) for k in keywords), "", text).strip(" ：:")
            if rest and not re.fullmatch(r"[\d\s\-\/]+", rest) and len(rest) >= 2:
                return rest
            # Then next few lines
            for j in range(idx + 1, min(idx + 4, len(texts))):
                candidate = texts[j].strip()
                if candidate and not re.fullmatch(r"[\d\s\-\/]+", candidate) and len(candidate) >= 2:
                    return candidate
    return None


def _extract_amounts(texts: list[str], full: str) -> tuple[str | None, str | None, str | None]:
    net_amount = tax = total = None
    for text in texts:
        nums = re.findall(r"\d{1,3}(?:,\d{3})*(?:\.\d+)?", text)
        if not nums:
            continue
        amt = nums[0].replace(",", "")
        if any(k in text for k in ["銷售額", "未稅", "淨額", "稅前", "應稅銷售"]):
            net_amount = amt
        elif any(k in text for k in ["稅額", "營業稅", "加值稅"]):
            tax = amt
        elif any(k in text for k in ["總計", "合計", "總額", "應收", "含稅", "發票金額", "小計"]):
            total = amt
    # Fallback: last 3 positive integers in doc
    if not (net_amount and tax and total):
        all_nums = [a.replace(",", "") for a in re.findall(r"\b\d{1,3}(?:,\d{3})*\b", full)]
        positives = [a for a in all_nums if int(a) > 0]
        if not net_amount and len(positives) >= 3:
            net_amount = positives[-3]
        if not tax and len(positives) >= 2:
            tax = positives[-2]
        if not total and positives:
            total = positives[-1]
    return net_amount, tax, total


# ---------------------------------------------------------------------------
# Evidence builder
# ---------------------------------------------------------------------------

def build_evidence(fields: dict[str, Any], lines: list[OcrLine]) -> dict[str, Any]:
    evidence = {}
    for key, value in fields.items():
        if value in (None, "", False):
            continue
        value_text = str(value)
        hit = next((line for line in lines if value_text in line.text), None)
        if hit is None:
            continue
        evidence[key] = {
            "bbox": hit.bbox,
            "raw_text": hit.text,
            "confidence": hit.confidence,
            "anchor_used": "paddleocr",
        }
    return evidence


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--project-root", default=None)
    args = parser.parse_args()

    image_path = Path(args.input)
    if not image_path.exists():
        raise FileNotFoundError(f"Input not found: {image_path}")

    with open(args.config, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    project_root = Path(args.project_root).resolve() if args.project_root else Path(__file__).resolve().parent.parent

    # 1. PaddleOCR
    lines = run_paddle_ocr(str(image_path))
    if not lines:
        raise RuntimeError("PaddleOCR produced no text lines.")

    # 2. Extract fields (PaddleOCR text — reliable for numbers/UBN/inv_no)
    fields = extract_fields(lines)

    # 3. UBN memory — fill known company names instantly (no AI needed)
    memory = load_ubn_memory(project_root)
    if fields.get("seller_ubn") and fields["seller_ubn"] in memory:
        fields["seller_name"] = memory[fields["seller_ubn"]]
        sys.stderr.write(f"[info] Memory hit: {fields['seller_ubn']} → {fields['seller_name']}\n")
    if fields.get("buyer_ubn") and fields["buyer_ubn"] in memory:
        fields["buyer_name"] = memory[fields["buyer_ubn"]]
        sys.stderr.write(f"[info] Memory hit: {fields['buyer_ubn']} → {fields['buyer_name']}\n")

    # 4. Qwen Vision — only for names still missing (avoids hallucination on numbers)
    needs_seller = not fields.get("seller_name")
    needs_buyer  = not fields.get("buyer_name")
    if (needs_seller or needs_buyer) and cfg.get("qwen", {}).get("enabled", False):
        vis_seller, vis_buyer = run_qwen_vision_names(str(image_path), cfg["qwen"], project_root)
        if needs_seller and vis_seller:
            fields["seller_name"] = vis_seller
        if needs_buyer and vis_buyer:
            fields["buyer_name"] = vis_buyer

    # 5. Evidence + score
    evidence = build_evidence(fields, lines)
    match_score = min(1.0, sum(l.confidence for l in lines) / max(1, len(lines)))

    sys.stdout.write(json.dumps({
        "fields": fields,
        "evidence": evidence,
        "match_score": round(match_score, 4),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        sys.stderr.write(str(exc) + "\n")
        raise
