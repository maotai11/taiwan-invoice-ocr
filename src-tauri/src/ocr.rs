use std::path::{Path, PathBuf};
use std::process::Command;

use chrono::NaiveDate;
use rust_decimal::Decimal;
use serde::Deserialize;

use crate::error::AppError;
use crate::models::{BoundingBox, CrossValidation, Evidence, FieldName, InvoiceFields};

#[derive(Debug, Deserialize)]
struct PythonCrossValidation {
    field: String,
    paddle_val: String,
    qwen_val: String,
}

#[derive(Debug, Deserialize)]
struct PythonOcrOutput {
    fields: PythonFields,
    evidence: std::collections::HashMap<FieldName, PythonEvidence>,
    match_score: f32,
    #[serde(default)]
    review: bool,
    #[serde(default)]
    cross_validations: Vec<PythonCrossValidation>,
}

#[derive(Debug, Deserialize)]
struct PythonFields {
    inv_no: Option<String>,
    inv_date: Option<String>,
    seller_ubn: Option<String>,
    seller_name: Option<String>,
    buyer_ubn: Option<String>,
    buyer_name: Option<String>,
    net_amount: Option<String>,
    tax: Option<String>,
    total: Option<String>,
    tax_type: Option<String>,
    random_code: Option<String>,
    qr_verified: Option<bool>,
    invoice_type: Option<String>,
    #[serde(default)]
    type_confidence: f32,
}

#[derive(Debug, Deserialize)]
struct PythonEvidence {
    bbox: [f32; 5],
    raw_text: String,
    confidence: f32,
    anchor_used: Option<String>,
}

pub struct OcrResult {
    pub fields: InvoiceFields,
    pub evidence: std::collections::HashMap<FieldName, Evidence>,
    pub match_score: f32,
    pub review: bool,
    pub cross_validations: Vec<CrossValidation>,
}

/// Resolve the project/resource root directory at runtime.
/// In production (Tauri installed app), scripts/ and config/ sit next to the exe.
/// In development (cargo run), fall back to CARGO_MANIFEST_DIR parent.
pub fn runtime_resource_root() -> PathBuf {
    if let Ok(exe) = std::env::current_exe() {
        if let Some(exe_dir) = exe.parent() {
            // Production: scripts/ is bundled next to the exe
            if exe_dir.join("scripts").exists() {
                return exe_dir.to_path_buf();
            }
            // Tauri dev: exe is at target/debug/ or target/release/
            // Go up to find the project root (where scripts/ lives)
            if let Some(target_dir) = exe_dir.parent() {
                // target/debug -> target -> project root
                if let Some(project_dir) = target_dir.parent() {
                    if project_dir.join("scripts").exists() {
                        return project_dir.to_path_buf();
                    }
                }
            }
        }
    }
    // Final fallback: compile-time CARGO_MANIFEST_DIR parent (src-tauri/../)
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap_or(Path::new("."))
        .to_path_buf()
}

/// Find Python executable: check PATH first, then common Windows locations.
fn find_python() -> String {
    for candidate in &["python", "python3"] {
        if Command::new(candidate)
            .arg("--version")
            .output()
            .map(|o| o.status.success())
            .unwrap_or(false)
        {
            return candidate.to_string();
        }
    }
    // Try %USERPROFILE%\AppData\Local\Programs\Python\PythonXXX
    if let Ok(profile) = std::env::var("USERPROFILE") {
        for ver in &["Python312", "Python311", "Python310", "Python39"] {
            let path = format!(r"{}\AppData\Local\Programs\Python\{}\python.exe", profile, ver);
            if Path::new(&path).exists() {
                return path;
            }
        }
    }
    "python".to_string()
}

pub fn run_ocr_pipeline(project_root: &Path, input: &Path) -> Result<OcrResult, AppError> {
    let config = project_root.join("config").join("ocr_config.json");
    if !config.exists() {
        return Err(AppError::Internal {
            message: format!("OCR config not found: {}", config.to_string_lossy()),
            code: 9999,
        });
    }

    // Prefer bundled standalone EXE (no Python required on target machine).
    // Falls back to `python ocr_pipeline.py` for development.
    let bundled_exe = project_root.join("ocr_pipeline").join("ocr_pipeline.exe");
    let (program, pre_args): (String, Vec<String>) = if bundled_exe.exists() {
        (bundled_exe.to_string_lossy().to_string(), vec![])
    } else {
        let script = project_root.join("scripts").join("ocr_pipeline.py");
        if !script.exists() {
            return Err(AppError::Internal {
                message: format!(
                    "OCR engine not found. Expected bundled EXE at: {}\nor script at: {}",
                    bundled_exe.to_string_lossy(),
                    script.to_string_lossy()
                ),
                code: 9999,
            });
        }
        (find_python(), vec![script.to_string_lossy().to_string()])
    };

    let mut cmd = Command::new(&program);
    cmd.args(&pre_args)
        .arg("--input")
        .arg(input)
        .arg("--config")
        .arg(&config)
        .arg("--project-root")
        .arg(project_root);

    let output = cmd.output().map_err(|e| AppError::OcrFailed {
            reason: format!("Failed to launch OCR engine ({}): {}", program, e),
            code: 2002,
        })?;

    if !output.status.success() {
        return Err(AppError::OcrFailed {
            reason: String::from_utf8_lossy(&output.stderr).to_string(),
            code: 2002,
        });
    }

    let parsed: PythonOcrOutput =
        serde_json::from_slice(&output.stdout).map_err(|e| AppError::OcrFailed {
            reason: format!("Invalid OCR JSON: {e}\nstdout: {}", String::from_utf8_lossy(&output.stdout)),
            code: 2002,
        })?;

    Ok(OcrResult {
        fields: map_fields(parsed.fields),
        evidence: parsed
            .evidence
            .into_iter()
            .map(|(k, v)| {
                (
                    k,
                    Evidence {
                        bbox: BoundingBox {
                            x: v.bbox[0],
                            y: v.bbox[1],
                            width: v.bbox[2],
                            height: v.bbox[3],
                            rotation: v.bbox[4],
                        },
                        raw_text: v.raw_text,
                        confidence: v.confidence,
                        anchor_used: v.anchor_used,
                    },
                )
            })
            .collect(),
        match_score: parsed.match_score,
        review: parsed.review,
        cross_validations: parsed
            .cross_validations
            .into_iter()
            .map(|c| CrossValidation {
                field: c.field,
                paddle_val: c.paddle_val,
                qwen_val: c.qwen_val,
            })
            .collect(),
    })
}

fn map_fields(raw: PythonFields) -> InvoiceFields {
    InvoiceFields {
        inv_no: raw.inv_no,
        inv_date: raw
            .inv_date
            .and_then(|v| NaiveDate::parse_from_str(&v, "%Y-%m-%d").ok()),
        seller_ubn: raw.seller_ubn,
        seller_name: raw.seller_name,
        buyer_ubn: raw.buyer_ubn,
        buyer_name: raw.buyer_name,
        net_amount: parse_decimal(raw.net_amount),
        tax: parse_decimal(raw.tax),
        total: parse_decimal(raw.total),
        tax_type: raw.tax_type.and_then(parse_tax_type),
        random_code: raw.random_code,
        qr_verified: raw.qr_verified.unwrap_or(false),
        invoice_type: raw.invoice_type,
        type_confidence: raw.type_confidence,
    }
}

fn parse_decimal(value: Option<String>) -> Option<Decimal> {
    value.and_then(|v| v.replace(',', "").parse::<Decimal>().ok())
}

fn parse_tax_type(value: String) -> Option<crate::models::TaxType> {
    match value.to_lowercase().as_str() {
        "taxable" => Some(crate::models::TaxType::Taxable),
        "zerotax" | "zero_tax" | "zero" => Some(crate::models::TaxType::ZeroTax),
        "taxexempt" | "tax_exempt" | "exempt" => Some(crate::models::TaxType::TaxExempt),
        "special" => Some(crate::models::TaxType::Special),
        _ => None,
    }
}
