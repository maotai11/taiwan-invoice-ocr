use std::path::PathBuf;
use std::collections::HashMap;

use chrono::Utc;
use tauri::State;
use uuid::Uuid;

use crate::error::AppError;
use crate::export::export_excel;
use crate::models::{
    EditRecord, ExportOptions, ExportResult, FileType, ImportResult, InvoiceFields, ProcessingState,
    ProcessingStatus, QueuedItem, RowRecord, RowRecordSummary, RowStatus, Source, Strategy,
};
use crate::ocr::{runtime_resource_root, run_ocr_pipeline};
use crate::state::AppState;
use crate::validation::validate_row;

#[tauri::command]
pub async fn import_files(state: State<'_, AppState>, paths: Vec<PathBuf>) -> Result<ImportResult, AppError> {
    if paths.is_empty() {
        return Err(AppError::Internal {
            message: "No input files.".to_string(),
            code: 9999,
        });
    }
    let job_id = Uuid::new_v4();
    let mut queued_items = Vec::new();
    let mut ids = Vec::new();

    for path in &paths {
        if !path.exists() {
            return Err(AppError::FileNotFound {
                path: path.to_string_lossy().to_string(),
                code: 1001,
            });
        }

        let ext = path
            .extension()
            .map(|e| e.to_string_lossy().to_ascii_lowercase())
            .unwrap_or_default();
        let file_type = if ext == "pdf" {
            FileType::Pdf
        } else if ["jpg", "jpeg", "png", "webp", "tiff", "tif", "heic"].contains(&ext.as_str()) {
            FileType::Image
        } else {
            return Err(AppError::InvalidFileType {
                file_type: ext,
                code: 1002,
            });
        };

        let id = Uuid::new_v4();
        let now = Utc::now();
        let mut row = RowRecord {
            id,
            source: Source {
                file_path: path.clone(),
                file_type,
                page_number: None,
                original_filename: path
                    .file_name()
                    .map(|f| f.to_string_lossy().to_string())
                    .unwrap_or_else(|| "unknown".to_string()),
            },
            status: RowStatus::Review,
            processing_state: ProcessingState::Done,
            matched_template: None,
            match_score: 0.0,
            strategy_used: Strategy::TemplateA,
            fields: InvoiceFields::default(),
            evidence: Default::default(),
            issues: vec![],
            edits: vec![],
            image_path: path.clone(),
            thumb_path: path.clone(),
            created_at: now,
            updated_at: now,
        };

        let project_root = runtime_resource_root();
        row.processing_state = ProcessingState::OcrRunning;
        let mut ocr_failed_issue: Option<crate::models::Issue> = None;
        match run_ocr_pipeline(&project_root, path) {
            Ok(ocr) => {
                row.processing_state = ProcessingState::Validating;
                row.fields = ocr.fields;
                row.evidence = ocr.evidence;
                row.match_score = ocr.match_score;
                row.processing_state = ProcessingState::Done;
            }
            Err(err) => {
                row.processing_state = ProcessingState::Failed {
                    error_code: err.error_code(),
                };
                row.status = RowStatus::Error;
                ocr_failed_issue = Some(crate::models::Issue {
                    code: crate::models::IssueCode::OcrLowConfidence,
                    severity: crate::models::Severity::Error,
                    field: None,
                    message: format!("OCR failed: {}", err),
                    suggestion: None,
                });
            }
        }

        row.issues = validate_row(&row);
        if let Some(issue) = ocr_failed_issue {
            row.issues.push(issue);
        }
        row.status = if row.issues.iter().any(|i| i.severity == crate::models::Severity::Error) {
            RowStatus::Error
        } else if row.issues.is_empty() {
            RowStatus::OK
        } else {
            RowStatus::Review
        };

        state.rows.write().insert(id, row.clone());
        ids.push(id);
        queued_items.push(QueuedItem {
            id,
            source: row.source,
            status: row.processing_state,
        });
    }

    state.jobs.write().insert(job_id, ids);
    Ok(ImportResult {
        job_id,
        total_files: paths.len() as u32,
        total_pages: paths.len() as u32,
        queued_items,
    })
}

#[tauri::command]
pub async fn run_ocr_for_row(state: State<'_, AppState>, row_id: Uuid) -> Result<RowRecord, AppError> {
    let mut rows = state.rows.write();
    let row = rows.get_mut(&row_id).ok_or_else(|| AppError::Internal {
        message: "Row not found".to_string(),
        code: 9999,
    })?;
    let project_root = runtime_resource_root();
    row.processing_state = ProcessingState::OcrRunning;
    let ocr = run_ocr_pipeline(&project_root, &row.image_path)?;
    row.fields = ocr.fields;
    row.evidence = ocr.evidence;
    row.match_score = ocr.match_score;
    row.issues = validate_row(row);
    row.processing_state = ProcessingState::Done;
    row.status = if row.issues.iter().any(|i| i.severity == crate::models::Severity::Error) {
        RowStatus::Error
    } else if row.issues.is_empty() {
        RowStatus::OK
    } else {
        RowStatus::Review
    };
    row.updated_at = Utc::now();
    Ok(row.clone())
}

#[tauri::command]
pub async fn get_processing_status(
    state: State<'_, AppState>,
    job_id: Uuid,
) -> Result<ProcessingStatus, AppError> {
    let jobs = state.jobs.read();
    let ids = jobs.get(&job_id).ok_or_else(|| AppError::Internal {
        message: "Job not found".to_string(),
        code: 9999,
    })?;
    let rows = state.rows.read();
    let total = ids.len() as u32;
    let completed = ids
        .iter()
        .filter(|id| rows.get(id).is_some_and(|r| matches!(r.processing_state, ProcessingState::Done)))
        .count() as u32;
    let failed = ids
        .iter()
        .filter(|id| rows.get(id).is_some_and(|r| matches!(r.processing_state, ProcessingState::Failed { .. })))
        .count() as u32;
    Ok(ProcessingStatus {
        job_id,
        total,
        completed,
        failed,
        current_item: None,
        eta_seconds: None,
    })
}

#[tauri::command]
pub async fn get_all_rows(state: State<'_, AppState>) -> Result<Vec<RowRecordSummary>, AppError> {
    let rows = state.rows.read();
    Ok(rows.values().map(RowRecord::to_summary).collect())
}

#[tauri::command]
pub async fn get_row_detail(state: State<'_, AppState>, row_id: Uuid) -> Result<RowRecord, AppError> {
    let rows = state.rows.read();
    rows.get(&row_id).cloned().ok_or_else(|| AppError::Internal {
        message: "Row not found".to_string(),
        code: 9999,
    })
}

#[tauri::command]
pub async fn update_field(
    state: State<'_, AppState>,
    row_id: Uuid,
    field: String,
    value: String,
    auto_learn: bool,
) -> Result<RowRecord, AppError> {
    let mut rows = state.rows.write();
    let row = rows.get_mut(&row_id).ok_or_else(|| AppError::Internal {
        message: "Row not found".to_string(),
        code: 9999,
    })?;

    let old_value = set_field_value(row, &field, &value);
    row.edits.push(EditRecord {
        field,
        old_value,
        new_value: value,
        edited_at: Utc::now(),
        auto_learn,
    });
    row.issues = validate_row(row);
    row.status = if row.issues.iter().any(|i| i.severity == crate::models::Severity::Error) {
        RowStatus::Error
    } else if row.issues.is_empty() {
        RowStatus::OK
    } else {
        RowStatus::Review
    };
    row.updated_at = Utc::now();
    Ok(row.clone())
}

#[tauri::command]
pub async fn set_row_status(
    state: State<'_, AppState>,
    row_id: Uuid,
    status: RowStatus,
) -> Result<RowRecordSummary, AppError> {
    let mut rows = state.rows.write();
    let row = rows.get_mut(&row_id).ok_or_else(|| AppError::Internal {
        message: "Row not found".to_string(),
        code: 9999,
    })?;
    row.status = status;
    row.updated_at = Utc::now();
    Ok(row.to_summary())
}

#[tauri::command]
pub async fn export_excel_command(
    state: State<'_, AppState>,
    options: ExportOptions,
) -> Result<ExportResult, AppError> {
    let rows: Vec<RowRecord> = state.rows.read().values().cloned().collect();
    export_excel(rows, &options)
}

#[tauri::command]
pub async fn rerun_extraction(
    state: State<'_, AppState>,
    row_id: Uuid,
    strategy: Strategy,
) -> Result<RowRecord, AppError> {
    let mut rows = state.rows.write();
    let row = rows.get_mut(&row_id).ok_or_else(|| AppError::Internal {
        message: "Row not found".to_string(),
        code: 9999,
    })?;
    row.strategy_used = strategy;
    row.processing_state = ProcessingState::Done;
    row.issues = validate_row(row);
    row.updated_at = Utc::now();
    Ok(row.clone())
}

fn set_field_value(row: &mut RowRecord, field: &str, value: &str) -> Option<String> {
    match field {
        "inv_no" => row.fields.inv_no.replace(value.to_string()),
        "inv_date" => {
            let old = row.fields.inv_date.map(|d| d.to_string());
            row.fields.inv_date = chrono::NaiveDate::parse_from_str(value, "%Y-%m-%d").ok();
            old
        }
        "seller_ubn" => row.fields.seller_ubn.replace(value.to_string()),
        "seller_name" => row.fields.seller_name.replace(value.to_string()),
        "buyer_ubn" => row.fields.buyer_ubn.replace(value.to_string()),
        "buyer_name" => row.fields.buyer_name.replace(value.to_string()),
        "total" => {
            let old = row.fields.total.map(|d| d.to_string());
            row.fields.total = value.parse().ok();
            old
        }
        _ => None,
    }
}

/// Save a UBN → company name mapping to data/ubn_memory.json.
/// Called from the frontend when the user manually corrects a company name.
#[tauri::command]
pub async fn save_memory_entry(ubn: String, name: String) -> Result<(), AppError> {
    if ubn.is_empty() || name.is_empty() {
        return Ok(());
    }
    let memory_path = runtime_resource_root().join("data").join("ubn_memory.json");
    if let Some(parent) = memory_path.parent() {
        std::fs::create_dir_all(parent).map_err(|e| AppError::Internal {
            message: format!("Cannot create data dir: {e}"),
            code: 9001,
        })?;
    }
    let mut memory: HashMap<String, String> = if memory_path.exists() {
        let raw = std::fs::read_to_string(&memory_path).unwrap_or_default();
        serde_json::from_str(&raw).unwrap_or_default()
    } else {
        HashMap::new()
    };
    memory.insert(ubn, name);
    let json = serde_json::to_string_pretty(&memory).map_err(|e| AppError::Internal {
        message: e.to_string(),
        code: 9001,
    })?;
    std::fs::write(&memory_path, json).map_err(|e| AppError::Internal {
        message: format!("Cannot write memory: {e}"),
        code: 9001,
    })?;
    Ok(())
}
