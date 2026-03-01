use std::collections::HashMap;
use std::path::PathBuf;

use chrono::{DateTime, NaiveDate, Utc};
use rust_decimal::Decimal;
use serde::{Deserialize, Serialize};
use uuid::Uuid;

pub type FieldName = String;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RowRecord {
    pub id: Uuid,
    pub source: Source,
    pub status: RowStatus,
    pub processing_state: ProcessingState,
    pub matched_template: Option<TemplateRef>,
    pub match_score: f32,
    pub strategy_used: Strategy,
    pub fields: InvoiceFields,
    pub evidence: HashMap<FieldName, Evidence>,
    pub issues: Vec<Issue>,
    pub edits: Vec<EditRecord>,
    pub image_path: PathBuf,
    pub thumb_path: PathBuf,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Source {
    pub file_path: PathBuf,
    pub file_type: FileType,
    pub page_number: Option<u32>,
    pub original_filename: String,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq, Hash)]
pub enum FileType {
    Pdf,
    Image,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq, Hash)]
pub enum RowStatus {
    OK,
    Review,
    Error,
    Excluded,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
pub enum ProcessingState {
    Queued,
    OcrRunning,
    Extracting,
    Validating,
    Done,
    Failed { error_code: u32 },
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
pub enum Strategy {
    TemplateA,
    MlBasedB,
    QrCodeDirect,
    Hybrid,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct InvoiceFields {
    pub inv_no: Option<String>,
    pub inv_date: Option<NaiveDate>,
    pub seller_ubn: Option<String>,
    pub seller_name: Option<String>,
    pub buyer_ubn: Option<String>,
    pub buyer_name: Option<String>,
    pub net_amount: Option<Decimal>,
    pub tax: Option<Decimal>,
    pub total: Option<Decimal>,
    pub tax_type: Option<TaxType>,
    pub random_code: Option<String>,
    pub qr_verified: bool,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
pub enum TaxType {
    Taxable,
    ZeroTax,
    TaxExempt,
    Special,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Evidence {
    pub bbox: BoundingBox,
    pub raw_text: String,
    pub confidence: f32,
    pub anchor_used: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BoundingBox {
    pub x: f32,
    pub y: f32,
    pub width: f32,
    pub height: f32,
    pub rotation: f32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Issue {
    pub code: IssueCode,
    pub severity: Severity,
    pub field: Option<FieldName>,
    pub message: String,
    pub suggestion: Option<String>,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
pub enum IssueCode {
    UbnInvalidLength,
    UbnChecksumFailed,
    UbnOcrConfusion,
    InvNoInvalidFormat,
    InvNoOcrConfusion,
    AmountMismatch,
    AmountNegative,
    DateInvalid,
    DateFuture,
    TemplateLowConfidence,
    TemplateNotFound,
    QrDecodeFailed,
    QrChecksumMismatch,
    FieldMissing,
    OcrLowConfidence,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
pub enum Severity {
    Error,
    Warning,
    Info,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EditRecord {
    pub field: FieldName,
    pub old_value: Option<String>,
    pub new_value: String,
    pub edited_at: DateTime<Utc>,
    pub auto_learn: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TemplateRef {
    pub id: Uuid,
    pub name: String,
    pub invoice_type: InvoiceType,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
pub enum InvoiceType {
    ElectronicB2C,
    ElectronicB2B,
    TriplicateManual,
    DuplicateManual,
    CashRegister,
    GovReceipt,
    GovPaymentSlip,
}

#[derive(Debug, Serialize)]
pub struct ImportResult {
    pub job_id: Uuid,
    pub total_files: u32,
    pub total_pages: u32,
    pub queued_items: Vec<QueuedItem>,
}

#[derive(Debug, Serialize)]
pub struct QueuedItem {
    pub id: Uuid,
    pub source: Source,
    pub status: ProcessingState,
}

#[derive(Debug, Serialize)]
pub struct ProcessingStatus {
    pub job_id: Uuid,
    pub total: u32,
    pub completed: u32,
    pub failed: u32,
    pub current_item: Option<Uuid>,
    pub eta_seconds: Option<u32>,
}

#[derive(Debug, Serialize)]
pub struct RowRecordSummary {
    pub id: Uuid,
    pub status: RowStatus,
    pub source_label: String,
    pub thumb_url: String,
    pub template_name: Option<String>,
    pub score: f32,
    pub issue_count: u32,
    pub fields: InvoiceFieldsSummary,
}

#[derive(Debug, Serialize, Default)]
pub struct InvoiceFieldsSummary {
    pub inv_no: Option<String>,
    pub inv_date: Option<NaiveDate>,
    pub seller_ubn: Option<String>,
    pub seller_name: Option<String>,
    pub buyer_ubn: Option<String>,
    pub buyer_name: Option<String>,
    pub net_amount: Option<Decimal>,
    pub tax: Option<Decimal>,
    pub total: Option<Decimal>,
    pub tax_type: Option<TaxType>,
}

#[derive(Debug, Deserialize)]
pub struct ExportOptions {
    pub output_path: PathBuf,
    pub include_statuses: Vec<RowStatus>,
    pub include_thumbnail: bool,
    pub thumbnail_width: u32,
    pub column_order: Option<Vec<String>>,
}

#[derive(Debug, Serialize)]
pub struct ExportResult {
    pub output_path: PathBuf,
    pub total_rows: u32,
    pub exported_rows: u32,
    pub skipped_rows: u32,
    pub skipped_reasons: HashMap<RowStatus, u32>,
}

impl RowRecord {
    pub fn to_summary(&self) -> RowRecordSummary {
        let source_label = match self.source.file_type {
            FileType::Pdf => format!("PDF#{}", self.source.page_number.unwrap_or(1)),
            FileType::Image => "IMG".to_string(),
        };
        RowRecordSummary {
            id: self.id,
            status: self.status,
            source_label,
            thumb_url: self.thumb_path.to_string_lossy().to_string(),
            template_name: self.matched_template.as_ref().map(|t| t.name.clone()),
            score: self.match_score,
            issue_count: self.issues.len() as u32,
            fields: InvoiceFieldsSummary {
                inv_no: self.fields.inv_no.clone(),
                inv_date: self.fields.inv_date,
                seller_ubn: self.fields.seller_ubn.clone(),
                seller_name: self.fields.seller_name.clone(),
                buyer_ubn: self.fields.buyer_ubn.clone(),
                buyer_name: self.fields.buyer_name.clone(),
                net_amount: self.fields.net_amount,
                tax: self.fields.tax,
                total: self.fields.total,
                tax_type: self.fields.tax_type,
            },
        }
    }
}
