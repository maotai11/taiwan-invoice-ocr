import base64
import json
import os
import re
from typing import Any, Dict, List, Tuple

import cv2
import numpy as np
import requests
from paddleocr import PaddleOCR

LLAMA_URL = "http://127.0.0.1:8080/v1/chat/completions"
TIMEOUT = 120
LOW_CONF_TH = 0.60

UBN_RE = re.compile(r"\b\d{8}\b")
DATE_RE = re.compile(r"(\d{3,4})[./-](\d{1,2})[./-](\d{1,2})")
MONEY_RE = re.compile(r"(?<!\d)(\d{1,3}(?:,\d{3})*|\d+)(?:\.\d{1,2})?(?!\d)")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
OCR_MODELS_DIR = os.path.join(PROJECT_ROOT, "ocr_models")


def create_paddle_ocr() -> PaddleOCR:
    os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
    det_dir = os.path.join(OCR_MODELS_DIR, "det")
    rec_dir = os.path.join(OCR_MODELS_DIR, "rec")
    cls_dir = os.path.join(OCR_MODELS_DIR, "cls")
    missing = [p for p in [det_dir, rec_dir, cls_dir] if not os.path.isdir(p)]
    if missing:
        raise RuntimeError(
            "Missing local OCR model folders. Please prepare:\n"
            f"{det_dir}\n{rec_dir}\n{cls_dir}"
        )
    return PaddleOCR(
        text_detection_model_dir=det_dir,
        text_recognition_model_dir=rec_dir,
        textline_orientation_model_dir=cls_dir,
        use_textline_orientation=True,
    )


def img_to_b64_png(img_bgr: np.ndarray) -> str:
    ok, buf = cv2.imencode(".png", img_bgr)
    if not ok:
        raise RuntimeError("encode png failed")
    return base64.b64encode(buf.tobytes()).decode()


def bbox_from_poly(poly4: List[List[float]]) -> List[int]:
    xs = [p[0] for p in poly4]
    ys = [p[1] for p in poly4]
    return [int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))]


def clamp_bbox(b: List[int], w: int, h: int) -> List[int]:
    x1, y1, x2, y2 = b
    x1 = max(0, min(x1, w - 1))
    y1 = max(0, min(y1, h - 1))
    x2 = max(0, min(x2, w - 1))
    y2 = max(0, min(y2, h - 1))
    if x2 < x1:
        x1, x2 = x2, x1
    if y2 < y1:
        y1, y2 = y2, y1
    return [x1, y1, x2, y2]


def expand_bbox(b: List[int], pad: int, w: int, h: int) -> List[int]:
    return clamp_bbox([b[0] - pad, b[1] - pad, b[2] + pad, b[3] + pad], w, h)


def crop(img: np.ndarray, b: List[int]) -> np.ndarray:
    h, w = img.shape[:2]
    x1, y1, x2, y2 = clamp_bbox(b, w, h)
    return img[y1 : y2 + 1, x1 : x2 + 1].copy()


def run_paddle(ocr: PaddleOCR, img_bgr: np.ndarray) -> Dict[str, Any]:
    res = ocr.predict(img_bgr)
    blocks = []
    i = 0
    if not res:
        return {"text_blocks": blocks}
    first = res[0]
    polys = first.get("dt_polys", []) or []
    texts = first.get("rec_texts", []) or []
    scores = first.get("rec_scores", []) or []
    for poly, text, conf in zip(polys, texts, scores):
        poly_list = poly.tolist() if hasattr(poly, "tolist") else poly
        blocks.append(
            {
                "id": f"b{i}",
                "text": text,
                "conf": conf,
                "bbox": bbox_from_poly(poly_list),
            }
        )
        i += 1
    return {"text_blocks": blocks}


def ubn_checksum_ok(ubn: str) -> bool:
    if not ubn or not re.fullmatch(r"\d{8}", ubn):
        return False
    w = [1, 2, 1, 2, 1, 2, 4, 1]
    s = 0
    for i, ch in enumerate(ubn):
        p = int(ch) * w[i]
        s += p // 10 + p % 10
    if s % 10 == 0:
        return True
    if ubn[6] == "7" and (s + 1) % 10 == 0:
        return True
    return False


def extract_fields_mvp(ocr_json: Dict[str, Any]) -> Dict[str, Any]:
    blocks = ocr_json["text_blocks"]
    all_text = "\n".join([b["text"] for b in blocks])

    ubn = None
    for m in UBN_RE.finditer(all_text):
        ubn = m.group(0)
        break

    date = None
    dm = DATE_RE.search(all_text)
    if dm:
        y, mo, d = dm.group(1), dm.group(2), dm.group(3)
        date = f"{y}-{int(mo):02d}-{int(d):02d}"

    monies = []
    for b in blocks:
        t = b["text"].replace("，", ",")
        for m in MONEY_RE.finditer(t):
            v = m.group(0).replace(",", "")
            try:
                monies.append((float(v), b["id"], b["bbox"], b["conf"]))
            except Exception:
                pass

    total = monies[-1][0] if monies else None
    total_src = monies[-1][1] if monies else None
    total_bbox = monies[-1][2] if monies else None

    return {
        "fields": {
            "buyer_ubn": {"value": ubn, "source_block_ids": []},
            "date": {"value": date, "source_block_ids": []},
            "total": {"value": total, "source_block_ids": [total_src] if total_src else []},
        },
        "hints": {"total_bbox": total_bbox},
    }


def validate(fields_pack: Dict[str, Any], ocr_json: Dict[str, Any]) -> Dict[str, Any]:
    f = fields_pack["fields"]
    issues = []

    ubn = f["buyer_ubn"]["value"]
    if ubn is None:
        issues.append({"field": "buyer_ubn", "problem": "missing"})
    elif not ubn_checksum_ok(ubn):
        issues.append({"field": "buyer_ubn", "problem": "checksum_fail", "value": ubn})

    date = f["date"]["value"]
    if date is None:
        issues.append({"field": "date", "problem": "missing"})

    total = f["total"]["value"]
    if total is None:
        issues.append({"field": "total", "problem": "missing"})
    elif total < 0 or total > 10_000_000:
        issues.append({"field": "total", "problem": "out_of_range", "value": total})

    low = [b for b in ocr_json["text_blocks"] if b["conf"] < LOW_CONF_TH]
    if low:
        issues.append({"field": "_ocr", "problem": "low_conf_blocks", "count": len(low)})

    return {"ok": len(issues) == 0, "issues": issues}


QWEN_AUDIT_PROMPT = r"""
你是「OCR校對員」。不可以猜數字、不可以直接改欄位值。
你只負責指出：哪個欄位可能亂碼/遺漏，並給需要重跑OCR的區域bbox（像素座標）。

只輸出JSON：
{
  "re_ocr_requests":[
    {"reason":"...", "bbox":[x1,y1,x2,y2]}
  ]
}

規則：
- bbox 必須在圖片範圍內
- 優先針對有問題的欄位（統編/日期/總額）
"""


def qwen_audit(
    img_bgr: np.ndarray,
    ocr_json: Dict[str, Any],
    fields_pack: Dict[str, Any],
    report: Dict[str, Any],
) -> Dict[str, Any]:
    payload = {
        "model": "local-qwen",
        "messages": [
            {"role": "system", "content": "只輸出 JSON，不要多餘文字。"},
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": img_to_b64_png(img_bgr)},
                    {"type": "text", "text": QWEN_AUDIT_PROMPT},
                    {"type": "text", "text": "OCR_JSON=" + json.dumps(ocr_json, ensure_ascii=False)},
                    {"type": "text", "text": "FIELDS=" + json.dumps(fields_pack, ensure_ascii=False)},
                    {"type": "text", "text": "REPORT=" + json.dumps(report, ensure_ascii=False)},
                ],
            },
        ],
        "temperature": 0.0,
    }
    r = requests.post(LLAMA_URL, json=payload, timeout=TIMEOUT)
    r.raise_for_status()
    content = r.json()["choices"][0]["message"]["content"]
    if isinstance(content, dict):
        return content
    return json.loads(content)


def merge_if_better(
    fields_before: Dict[str, Any],
    report_before: Dict[str, Any],
    fields_after: Dict[str, Any],
    report_after: Dict[str, Any],
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    logs = []
    b = len(report_before["issues"])
    a = len(report_after["issues"])
    merged = json.loads(json.dumps(fields_before))
    if a < b:
        for k, v in fields_after["fields"].items():
            ov = fields_before["fields"][k]["value"]
            nv = v["value"]
            if nv is not None and nv != ov:
                merged["fields"][k]["value"] = nv
                merged["fields"][k]["source_block_ids"] = v.get("source_block_ids", [])
                logs.append({"field": k, "old": ov, "new": nv, "why": f"issues {b}->{a}"})
    return merged, logs


def process(image_path: str) -> Dict[str, Any]:
    img = cv2.imread(image_path)
    if img is None:
        raise RuntimeError(f"Cannot read {image_path}")

    ocr = create_paddle_ocr()

    ocr1 = run_paddle(ocr, img)
    fields1 = extract_fields_mvp(ocr1)
    rep1 = validate(fields1, ocr1)

    out = {
        "image": image_path,
        "ocr_1": ocr1,
        "fields_1": fields1,
        "report_1": rep1,
        "patches": [],
        "final": None,
    }

    if rep1["ok"]:
        out["final"] = fields1
        out["final_report"] = rep1
        out["merge_logs"] = []
        return out

    audit = qwen_audit(img, ocr1, fields1, rep1)
    reqs = audit.get("re_ocr_requests", [])[:2]

    fields_cur = fields1
    rep_cur = rep1
    merge_logs_all = []

    h, w = img.shape[:2]

    for req in reqs:
        bbox = req.get("bbox")
        if not bbox or len(bbox) != 4:
            continue
        bbox = clamp_bbox(bbox, w, h)
        bbox = expand_bbox(bbox, 20, w, h)

        crop_img = crop(img, bbox)
        ocr2 = run_paddle(ocr, crop_img)
        fields2 = extract_fields_mvp(ocr2)
        rep2 = validate(fields2, ocr2)

        merged, logs = merge_if_better(fields_cur, rep_cur, fields2, rep2)

        out["patches"].append(
            {
                "reason": req.get("reason", ""),
                "bbox": bbox,
                "ocr_crop": ocr2,
                "fields_crop": fields2,
                "report_crop": rep2,
                "merge_logs": logs,
            }
        )

        if logs:
            fields_cur = merged
            rep_cur = rep2
            merge_logs_all.extend(logs)

    out["final"] = fields_cur
    out["final_report"] = rep_cur
    out["merge_logs"] = merge_logs_all
    return out


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python invoice_pipeline.py <image_path>")
        raise SystemExit(1)

    res = process(sys.argv[1])
    with open("result_full.json", "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)

    with open("result.json", "w", encoding="utf-8") as f:
        json.dump(res["final"], f, ensure_ascii=False, indent=2)

    print("Wrote result.json and result_full.json")
    print(json.dumps(res["final"], ensure_ascii=False, indent=2))
