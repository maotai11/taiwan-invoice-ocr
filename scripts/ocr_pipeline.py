#!/usr/bin/env python
"""
Taiwan Invoice OCR Pipeline  v3.0
----------------------------------
Pipeline:
  1. PaddleOCR     -> text lines (reliable for numbers)
  2. Classifier    -> detect invoice type (keyword weights)
  3. UBN memory    -> fill known company names instantly
  4. Qwen2.5-VL   -> extract ALL fields from image (full structured JSON)
  5. Cross-validate-> compare Qwen vs PaddleOCR on number fields
                     mismatch -> review=True, keep PaddleOCR value (safer)
  6. Output        -> fields + evidence + invoice_type + review flag
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


def normalise_amount(v: str | None) -> str | None:
    """Remove commas and trailing .0 from amount strings."""
    if not v:
        return None
    s = str(v).replace(",", "").strip()
    try:
        f = float(s)
        return str(int(f)) if f == int(f) else s
    except ValueError:
        return s if s else None


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


_paddle_ocr_instance = None


def get_paddle_ocr():
    global _paddle_ocr_instance
    if _paddle_ocr_instance is None:
        from paddleocr import PaddleOCR
        det, rec, cls = local_model_dirs()
        _paddle_ocr_instance = PaddleOCR(
            text_detection_model_dir=det,
            text_recognition_model_dir=rec,
            textline_orientation_model_dir=cls,
            use_textline_orientation=True,
        )
    return _paddle_ocr_instance


def run_paddle_ocr(image_path: str) -> list[OcrLine]:
    ocr = get_paddle_ocr()
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
    """Returns ubn -> name mapping, supporting both v1 (str) and v2 (dict) formats."""
    path = project_root / "data" / "ubn_memory.json"
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        result = {}
        for ubn, val in raw.items():
            if isinstance(val, str):
                result[ubn] = val          # v1
            elif isinstance(val, dict):
                result[ubn] = val.get("name", "")  # v2
        return result
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Template Region Learning
# ---------------------------------------------------------------------------

def load_templates(project_root: Path) -> dict:
    """Load data/templates.json. Returns empty dict if missing or unreadable."""
    path = project_root / "data" / "templates.json"
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        sys.stderr.write(f"[warn] Failed to load templates.json: {e}\n")
        return {}


def parse_template_field(field: str, text: str) -> Any:
    """Coerce raw OCR text from a cropped region into the typed field value."""
    if not text:
        return None
    if field in ("seller_ubn", "buyer_ubn"):
        digits = re.sub(r"\D", "", text)
        return digits if validate_ubn(digits) else None
    elif field in ("net_amount", "tax", "total"):
        return normalise_amount(text)
    elif field == "inv_no":
        m = re.search(r"([A-Z]{2})\s*(\d{8})", text.upper())
        return f"{m.group(1)}{m.group(2)}" if m else None
    elif field == "inv_date":
        return parse_date(text)
    else:
        return text.strip() or None


def extract_fields_from_template(
    image_path: str,
    regions: dict[str, dict],
) -> dict[str, Any]:
    """
    For each region in the template, crop the image and run PaddleOCR.
    Returns {field: value} only for fields where OCR produced a usable result.
    """
    import tempfile
    try:
        from PIL import Image
    except ImportError:
        sys.stderr.write("[warn] PIL not available; skipping template region OCR\n")
        return {}

    try:
        img = Image.open(image_path).convert("RGB")
    except Exception as e:
        sys.stderr.write(f"[warn] Cannot open image for template crop: {e}\n")
        return {}

    W, H = img.size
    result: dict[str, Any] = {}

    for field, region in regions.items():
        x = int(region["x"] * W)
        y = int(region["y"] * H)
        w = max(int(region["w"] * W), 4)
        h = max(int(region["h"] * H), 4)
        crop = img.crop((x, y, x + w, y + h))

        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".png")
        try:
            import os as _os
            _os.close(tmp_fd)
            crop.save(tmp_path)
            lines = run_paddle_ocr(tmp_path)
            if lines:
                raw_text = " ".join(l.text for l in lines).strip()
                value = parse_template_field(field, raw_text)
                if value is not None:
                    result[field] = value
                    sys.stderr.write(f"[template] {field}: {value!r}  (from crop {x},{y} {w}x{h})\n")
        except Exception as e:
            sys.stderr.write(f"[warn] Template crop OCR failed for {field}: {e}\n")
        finally:
            try:
                import os as _os
                _os.unlink(tmp_path)
            except OSError:
                pass

    return result


# ---------------------------------------------------------------------------
# Qwen 2.5-VL Vision — ALL fields (v3.0)
# ---------------------------------------------------------------------------

# Full structured JSON prompt (all invoice fields)
_QWEN_PROMPT_PARTS = [
    "\u8acb\u8fa8\u8b58\u9019\u5f35\u53f0\u7063\u767c\u7968\uff0c\u4ee5 JSON \u683c\u5f0f\u56de\u50b3\u4ee5\u4e0b\u6b04\u4f4d\uff0c\u672a\u627e\u5230\u7684\u6b04\u4f4d\u586b null\uff1a\n",
    "{\"inv_no\":\"\u767c\u7968\u865f\u78bc(2\u5b57\u6bcd+8\u6578\u5b57\u5982AB12345678)\",\"inv_date\":\"\u65e5\u671f(\u6c11\u570b\u5e74/\u6708/\u65e5\u5982113/05/20)\",",
    "\"seller_name\":\"\u8ce3\u65b9\u516c\u53f8\u540d\u7a31\",\"seller_ubn\":\"\u8ce3\u65b9\u7d71\u4e00\u7de8\u865f(8\u4f4d\u6578\u5b57)\",",
    "\"buyer_name\":\"\u8cb7\u65b9\u516c\u53f8\u540d\u7a31(\u500b\u4eba\u8cb7\u65b9\u586b null)\",\"buyer_ubn\":\"\u8cb7\u65b9\u7d71\u4e00\u7de8\u865f(8\u4f4d\u6578\u5b57\u6216 null)\",",
    "\"net_amount\":\"\u92b7\u552e\u984d(\u7d14\u6578\u5b57)\",\"tax\":\"\u7a05\u984d(\u7d14\u6578\u5b57)\",\"total\":\"\u7e3d\u8a08\u91d1\u984d(\u7d14\u6578\u5b57)\"}\n",
    "\u53ea\u56de\u50b3 JSON\uff0c\u4e0d\u8981\u5176\u4ed6\u8aaa\u660e\u3002",
]
QWEN_FULL_PROMPT = "".join(_QWEN_PROMPT_PARTS)


def run_qwen_vision_all_fields(
    image_path: str,
    cfg: dict[str, Any],
    project_root: Path,
) -> dict[str, Any]:
    """Extract ALL invoice fields via Qwen2.5-VL multimodal. Returns partial dict on failure."""
    if not cfg.get("enabled", False):
        return {}

    model_path = resolve_path(cfg.get("model_path", ""), project_root)
    mmproj_path = resolve_path(cfg.get("mmproj_path", ""), project_root)

    if not model_path.exists():
        sys.stderr.write(f"[warn] Qwen model not found: {model_path}\n")
        return {}
    if not mmproj_path.exists():
        sys.stderr.write(f"[warn] Qwen mmproj not found: {mmproj_path}\n")
        return {}

    try:
        from llama_cpp import Llama
        from llama_cpp.llama_chat_format import Qwen25VLChatHandler

        ext = Path(image_path).suffix.lower().lstrip(".")
        mime = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "webp": "webp"}.get(ext, "jpeg")
        with open(image_path, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode()

        chat_handler = Qwen25VLChatHandler(clip_model_path=str(mmproj_path))
        llm = Llama(
            model_path=str(model_path),
            chat_handler=chat_handler,
            n_ctx=int(cfg.get("n_ctx", 4096)),
            n_threads=int(cfg.get("n_threads", 6)),
            verbose=False,
        )

        result = llm.create_chat_completion(
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/{mime};base64,{img_b64}"}},
                    {"type": "text", "text": QWEN_FULL_PROMPT},
                ],
            }],
            temperature=0.1,
            max_tokens=int(cfg.get("max_tokens", 512)),
        )
        content = result["choices"][0]["message"]["content"]
        m = re.search(r"\{.*\}", content, re.DOTALL)
        if not m:
            sys.stderr.write(f"[warn] Qwen no JSON: {content[:120]}\n")
            return {}

        raw: dict = json.loads(m.group(0))

        def cs(v: Any) -> str | None:
            if not v or str(v).lower() in ("null", "none", ""):
                return None
            return str(v).strip() or None

        def cn(v: Any) -> str | None:
            s = cs(v)
            return s if s and len(s) >= 2 else None

        def cu(v: Any) -> str | None:
            s = re.sub(r"\D", "", str(v or ""))
            return s if validate_ubn(s) else None

        return {
            "inv_no": cs(raw.get("inv_no")),
            "inv_date": parse_date(str(raw.get("inv_date") or "")),
            "seller_name": cn(raw.get("seller_name")),
            "seller_ubn": cu(raw.get("seller_ubn")),
            "buyer_name": cn(raw.get("buyer_name")),
            "buyer_ubn": cu(raw.get("buyer_ubn")),
            "net_amount": normalise_amount(cs(raw.get("net_amount"))),
            "tax": normalise_amount(cs(raw.get("tax"))),
            "total": normalise_amount(cs(raw.get("total"))),
        }

    except Exception as e:
        sys.stderr.write(f"[warn] Qwen Vision failed: {e}\n")
        return {}


# ---------------------------------------------------------------------------
# Cross-validation (Qwen vs PaddleOCR on number fields)
# ---------------------------------------------------------------------------

NUMBER_FIELDS = ["inv_no", "seller_ubn", "buyer_ubn", "net_amount", "tax", "total"]


def cross_validate_numbers(
    paddle_fields: dict[str, Any],
    qwen_fields: dict[str, Any],
) -> tuple[dict[str, Any], bool, list[dict]]:
    """
    PaddleOCR is primary (reliable). If Qwen disagrees -> review=True.
    If PaddleOCR is missing a field -> fill from Qwen.
    Returns (merged_fields, review, cross_validations_list).
    """
    merged = dict(paddle_fields)
    review = False
    cross_validations: list[dict] = []
    for field in NUMBER_FIELDS:
        p_val = paddle_fields.get(field)
        q_val = qwen_fields.get(field)
        if p_val and q_val and p_val != q_val:
            review = True
            cross_validations.append({"field": field, "paddle_val": p_val, "qwen_val": q_val})
            sys.stderr.write(
                f"[cross-val] {field}: paddle={p_val!r}  qwen={q_val!r}  -> MISMATCH\n"
            )
        elif not p_val and q_val:
            merged[field] = q_val
    return merged, review, cross_validations


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
        "net_amount": normalise_amount(net_amount),
        "tax": normalise_amount(tax),
        "total": normalise_amount(total),
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

def _find_evidence_line(value_text: str, lines: list[OcrLine]) -> "OcrLine | None":
    """
    Match priority (highest to lowest):
      1. Exact full-line match
      2. Non-digit boundary match — prevents "45" matching inside "12345678"
      3. Substring fallback (original behaviour, last resort)
    For numeric values the boundary pattern is (?<!\\d)value(?!\\d).
    For text values we fall straight through to substring.
    """
    # 1. Exact match
    for line in lines:
        if line.text == value_text:
            return line
    # 2. Boundary match (most useful for short numbers)
    pat = r"(?<!\d)" + re.escape(value_text) + r"(?!\d)"
    for line in lines:
        if re.search(pat, line.text):
            return line
    # 3. Substring fallback
    for line in lines:
        if value_text in line.text:
            return line
    return None


def build_evidence(fields: dict[str, Any], lines: list[OcrLine]) -> dict[str, Any]:
    evidence = {}
    for key, value in fields.items():
        if value in (None, "", False):
            continue
        value_text = str(value)
        hit = _find_evidence_line(value_text, lines)
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

    project_root = (
        Path(args.project_root).resolve() if args.project_root
        else Path(__file__).resolve().parent.parent
    )

    # 1. PaddleOCR
    lines = run_paddle_ocr(str(image_path))
    if not lines:
        raise RuntimeError("PaddleOCR produced no text lines.")
    full_text = "\n".join(l.text for l in lines)

    # 2. Classify invoice type
    invoice_type = "\u672a\u77e5"
    type_confidence = 0.0
    kw_path = project_root / "config" / "keyword_weights.json"
    if kw_path.exists():
        try:
            from invoice_classifier import classify_invoice
            invoice_type, type_confidence = classify_invoice(full_text, kw_path)
            sys.stderr.write(f"[info] Invoice type: {invoice_type} ({type_confidence:.2f})\n")
        except Exception as e:
            sys.stderr.write(f"[warn] Classifier failed: {e}\n")

    # 3. Extract fields (PaddleOCR text — reliable for numbers/UBN/inv_no)
    paddle_fields = extract_fields(lines)

    # 3b. Template region learning — precision crop for known invoice types
    templates = load_templates(project_root)
    if invoice_type in templates:
        regions = templates[invoice_type].get("regions", {})
        if regions:
            template_fields = extract_fields_from_template(str(image_path), regions)
            hit_count = len(template_fields)
            if hit_count:
                sys.stderr.write(
                    f"[info] Template '{invoice_type}': {hit_count}/{len(regions)} fields overridden\n"
                )
                paddle_fields.update(template_fields)

    # 4. UBN memory — fill known company names instantly
    memory = load_ubn_memory(project_root)
    for ubn_f, name_f in [("seller_ubn", "seller_name"), ("buyer_ubn", "buyer_name")]:
        ubn = paddle_fields.get(ubn_f)
        if ubn and ubn in memory:
            paddle_fields[name_f] = memory[ubn]
            sys.stderr.write(f"[info] Memory hit: {ubn} -> {memory[ubn]}\n")

    # 5. Qwen Vision — only when PaddleOCR confidence is below threshold
    qwen_fields: dict[str, Any] = {}
    if cfg.get("qwen", {}).get("enabled", False):
        preliminary_score = min(1.0, sum(l.confidence for l in lines) / max(1, len(lines)))
        qwen_threshold = float(cfg.get("qwen", {}).get("threshold", 0.7))
        if preliminary_score < qwen_threshold:
            sys.stderr.write(
                f"[info] PaddleOCR score {preliminary_score:.3f} < {qwen_threshold}, running Qwen...\n"
            )
            qwen_fields = run_qwen_vision_all_fields(str(image_path), cfg["qwen"], project_root)
        else:
            sys.stderr.write(
                f"[info] Qwen skipped (PaddleOCR score {preliminary_score:.3f} >= {qwen_threshold})\n"
            )

    # 6. Cross-validate numbers; Qwen fills missing; Qwen wins on name fields
    review = False
    cross_validations: list[dict] = []
    if qwen_fields:
        paddle_fields, review, cross_validations = cross_validate_numbers(paddle_fields, qwen_fields)
        for nf in ("seller_name", "buyer_name"):
            if qwen_fields.get(nf) and not paddle_fields.get(nf):
                paddle_fields[nf] = qwen_fields[nf]

    # 7. Annotate with invoice type
    paddle_fields["invoice_type"] = invoice_type
    paddle_fields["type_confidence"] = type_confidence

    # 8. Evidence + score
    evidence = build_evidence(paddle_fields, lines)
    match_score = min(1.0, sum(l.confidence for l in lines) / max(1, len(lines)))

    sys.stdout.write(json.dumps({
        "fields": paddle_fields,
        "evidence": evidence,
        "match_score": round(match_score, 4),
        "review": review,
        "cross_validations": cross_validations,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        sys.stderr.write(str(exc) + "\n")
        raise
