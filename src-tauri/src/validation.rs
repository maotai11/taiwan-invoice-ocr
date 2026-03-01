use chrono::Utc;
use regex::Regex;
use rust_decimal::Decimal;

use crate::models::{Issue, IssueCode, RowRecord, Severity, TaxType};

pub fn validate_row(row: &RowRecord) -> Vec<Issue> {
    let mut issues = vec![];
    issues.extend(validate_inv_no(row));
    issues.extend(validate_ubn(row));
    issues.extend(validate_amount(row));
    issues.extend(validate_date(row));
    issues
}

fn validate_ubn(row: &RowRecord) -> Vec<Issue> {
    let mut issues = vec![];
    for (field_name, value) in [
        ("seller_ubn", row.fields.seller_ubn.as_deref()),
        ("buyer_ubn", row.fields.buyer_ubn.as_deref()),
    ] {
        if let Some(ubn) = value {
            if ubn.is_empty() {
                continue;
            }
            if ubn.len() != 8 {
                issues.push(Issue {
                    code: IssueCode::UbnInvalidLength,
                    severity: Severity::Error,
                    field: Some(field_name.to_string()),
                    message: format!("統編長度應為 8 碼，目前為 {} 碼", ubn.len()),
                    suggestion: None,
                });
            } else if !ubn.chars().all(|c| c.is_ascii_digit()) {
                issues.push(Issue {
                    code: IssueCode::UbnOcrConfusion,
                    severity: Severity::Error,
                    field: Some(field_name.to_string()),
                    message: "統編應全為數字".to_string(),
                    suggestion: Some(suggest_ocr_fix(ubn)),
                });
            }
        }
    }
    issues
}

fn validate_inv_no(row: &RowRecord) -> Vec<Issue> {
    let mut issues = vec![];
    let re = Regex::new(r"^[A-Z]{2}\d{8}$").expect("regex must compile");
    match row.fields.inv_no.as_deref() {
        Some(inv_no) => {
            if !re.is_match(inv_no) {
                issues.push(Issue {
                    code: IssueCode::InvNoInvalidFormat,
                    severity: Severity::Error,
                    field: Some("inv_no".to_string()),
                    message: "發票號碼格式不符（應為 2 碼英文 + 8 碼數字）".to_string(),
                    suggestion: None,
                });
            }
        }
        None => issues.push(Issue {
            code: IssueCode::FieldMissing,
            severity: Severity::Error,
            field: Some("inv_no".to_string()),
            message: "缺少發票號碼".to_string(),
            suggestion: None,
        }),
    }
    issues
}

fn validate_amount(row: &RowRecord) -> Vec<Issue> {
    let mut issues = vec![];
    let net = row.fields.net_amount;
    let tax = row.fields.tax;
    let total = row.fields.total;
    let tolerance = Decimal::ONE;

    match (net, tax, total) {
        (Some(n), Some(t), Some(tot)) => {
            let expected = n + t;
            let diff = (expected - tot).abs();
            if diff > tolerance {
                issues.push(Issue {
                    code: IssueCode::AmountMismatch,
                    severity: Severity::Error,
                    field: None,
                    message: format!("金額關係不符: {} + {} != {}", n, t, tot),
                    suggestion: Some(format!("建議總計: {}", expected)),
                });
            }
        }
        (Some(n), None, Some(tot)) if row.fields.tax_type == Some(TaxType::TaxExempt) && n != tot => {
            issues.push(Issue {
                code: IssueCode::AmountMismatch,
                severity: Severity::Warning,
                field: None,
                message: "免稅單據預期 net_amount = total".to_string(),
                suggestion: None,
            });
        }
        _ => {}
    }
    issues
}

fn validate_date(row: &RowRecord) -> Vec<Issue> {
    let mut issues = vec![];
    if let Some(date) = row.fields.inv_date {
        let today = Utc::now().date_naive();
        if date > today {
            issues.push(Issue {
                code: IssueCode::DateFuture,
                severity: Severity::Warning,
                field: Some("inv_date".to_string()),
                message: "發票日期為未來日期".to_string(),
                suggestion: None,
            });
        }
    }
    issues
}

fn suggest_ocr_fix(ubn: &str) -> String {
    ubn.replace('O', "0")
        .replace('o', "0")
        .replace('I', "1")
        .replace('l', "1")
        .replace('S', "5")
        .replace('B', "8")
}
