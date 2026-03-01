use std::collections::HashMap;

use serde::{Deserialize, Serialize};

use crate::error::AppError;
use crate::ocr::runtime_resource_root;

/// Relative bounding box (0.0–1.0) within the invoice image.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RegionRect {
    pub x: f32,
    pub y: f32,
    pub w: f32,
    pub h: f32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct InvoiceTemplate {
    pub version: u32,
    /// field_name -> RegionRect
    pub regions: HashMap<String, RegionRect>,
}

/// Root format of data/templates.json
/// invoice_type (string) -> InvoiceTemplate
type TemplateMap = HashMap<String, InvoiceTemplate>;

fn templates_path() -> std::path::PathBuf {
    runtime_resource_root().join("data").join("templates.json")
}

fn load_templates() -> Result<TemplateMap, AppError> {
    let path = templates_path();
    if !path.exists() {
        return Ok(HashMap::new());
    }
    let raw = std::fs::read_to_string(&path).map_err(|e| AppError::Internal {
        message: format!("Cannot read templates.json: {e}"),
        code: 9010,
    })?;
    serde_json::from_str(&raw).map_err(|e| AppError::Internal {
        message: format!("Invalid templates.json: {e}"),
        code: 9011,
    })
}

fn save_templates(map: &TemplateMap) -> Result<(), AppError> {
    let path = templates_path();
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|e| AppError::Internal {
            message: format!("Cannot create data dir: {e}"),
            code: 9012,
        })?;
    }
    let json = serde_json::to_string_pretty(map).map_err(|e| AppError::Internal {
        message: e.to_string(),
        code: 9013,
    })?;
    std::fs::write(&path, json).map_err(|e| AppError::Internal {
        message: format!("Cannot write templates.json: {e}"),
        code: 9014,
    })
}

/// Save (or overwrite) a single field region for an invoice type.
#[tauri::command]
pub async fn save_template_region(
    invoice_type: String,
    field: String,
    region: RegionRect,
) -> Result<(), AppError> {
    if invoice_type.is_empty() || field.is_empty() {
        return Err(AppError::Internal {
            message: "invoice_type and field must not be empty".to_string(),
            code: 9015,
        });
    }
    let mut map = load_templates()?;
    let template = map.entry(invoice_type).or_insert_with(|| InvoiceTemplate {
        version: 1,
        regions: HashMap::new(),
    });
    template.regions.insert(field, region);
    save_templates(&map)
}

/// Return all templates (all invoice types).
#[tauri::command]
pub async fn get_templates() -> Result<TemplateMap, AppError> {
    load_templates()
}

/// Delete a single field region. If the invoice type has no regions left, remove it entirely.
#[tauri::command]
pub async fn delete_template_region(invoice_type: String, field: String) -> Result<(), AppError> {
    let mut map = load_templates()?;
    if let Some(template) = map.get_mut(&invoice_type) {
        template.regions.remove(&field);
        if template.regions.is_empty() {
            map.remove(&invoice_type);
        }
    }
    save_templates(&map)
}
