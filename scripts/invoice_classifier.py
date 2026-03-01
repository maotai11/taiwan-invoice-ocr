"""
invoice_classifier.py
---------------------
Keyword-weight scoring to classify Taiwan invoice type from OCR text.
Supports 6 types: 三聯式 / 二聯式 / 電子發票 / 收銀機 / 特種 / 手開

Usage:
    from invoice_classifier import classify_invoice
    inv_type, confidence = classify_invoice(ocr_text, keyword_weights_path)
"""
from __future__ import annotations

import json
from pathlib import Path


def classify_invoice(ocr_text: str, keyword_weights_path: str | Path) -> tuple[str, float]:
    """
    Return (invoice_type, confidence) where confidence is 0.0-1.0.
    Falls back to the type marked "fallback": true if no type exceeds its min_score.
    """
    try:
        with open(keyword_weights_path, "r", encoding="utf-8") as f:
            weights_cfg: dict = json.load(f)
    except Exception:
        return "未知", 0.0

    scores: dict[str, float] = {}
    for inv_type, cfg in weights_cfg.items():
        score = 0.0
        for kw, w in cfg.get("keywords", {}).items():
            if kw in ocr_text:
                score += w
        scores[inv_type] = score

    # Best scoring type
    best_type = max(scores, key=scores.get)  # type: ignore[arg-type]
    best_score = scores[best_type]
    min_score = weights_cfg[best_type].get("min_score", 5)

    if best_score >= min_score:
        # Normalise: cap at 2x the min_score → 100%
        confidence = min(best_score / (min_score * 2.0), 1.0)
        return best_type, confidence

    # Fallback to the type flagged as default
    fallback = next(
        (t for t, c in weights_cfg.items() if c.get("fallback")),
        "二聯式",
    )
    return fallback, 0.3
