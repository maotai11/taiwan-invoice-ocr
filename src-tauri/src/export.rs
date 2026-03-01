use std::collections::HashMap;
use std::path::Path;

use rust_decimal::prelude::ToPrimitive;
use rust_xlsxwriter::{Format, FormatBorder, Workbook};

use crate::error::AppError;
use crate::models::{ExportOptions, ExportResult, RowRecord, RowStatus};

pub fn export_excel(rows: Vec<RowRecord>, options: &ExportOptions) -> Result<ExportResult, AppError> {
    let mut workbook = Workbook::new();
    let worksheet = workbook.add_worksheet();
    let headers = [
        "發票號碼",
        "發票日期",
        "賣方統編",
        "賣方名稱",
        "買方統編",
        "買方名稱",
        "銷售額",
        "稅額",
        "總計",
        "狀態",
        "問題數",
        "縮圖路徑",
    ];
    let header_fmt = Format::new().set_bold().set_border(FormatBorder::Thin);
    for (idx, title) in headers.iter().enumerate() {
        worksheet
            .write_string_with_format(0, idx as u16, *title, &header_fmt)
            .map_err(|e| AppError::ExportFailed {
                reason: e.to_string(),
                code: 5002,
            })?;
    }

    let mut line = 1u32;
    let mut exported_rows = 0u32;
    let mut skipped_rows = 0u32;
    let mut skipped_reasons: HashMap<RowStatus, u32> = HashMap::new();

    for row in rows {
        if !options.include_statuses.contains(&row.status) {
            skipped_rows += 1;
            *skipped_reasons.entry(row.status).or_insert(0) += 1;
            continue;
        }

        worksheet.write_string(line, 0, row.fields.inv_no.unwrap_or_default()).ok();
        worksheet.write_string(line, 1, row.fields.inv_date.map(|d| d.to_string()).unwrap_or_default()).ok();
        worksheet.write_string(line, 2, row.fields.seller_ubn.unwrap_or_default()).ok();
        worksheet.write_string(line, 3, row.fields.seller_name.unwrap_or_default()).ok();
        worksheet.write_string(line, 4, row.fields.buyer_ubn.unwrap_or_default()).ok();
        worksheet.write_string(line, 5, row.fields.buyer_name.unwrap_or_default()).ok();
        worksheet.write_number(line, 6, row.fields.net_amount.map(|v| v.to_f64().unwrap_or(0.0)).unwrap_or(0.0)).ok();
        worksheet.write_number(line, 7, row.fields.tax.map(|v| v.to_f64().unwrap_or(0.0)).unwrap_or(0.0)).ok();
        worksheet.write_number(line, 8, row.fields.total.map(|v| v.to_f64().unwrap_or(0.0)).unwrap_or(0.0)).ok();
        worksheet.write_string(line, 9, format!("{:?}", row.status)).ok();
        worksheet.write_number(line, 10, row.issues.len() as f64).ok();
        if options.include_thumbnail {
            worksheet.write_string(line, 11, row.thumb_path.to_string_lossy().to_string()).ok();
        }
        line += 1;
        exported_rows += 1;
    }

    workbook
        .save(Path::new(&options.output_path))
        .map_err(|e| AppError::ExportFailed {
            reason: e.to_string(),
            code: 5002,
        })?;

    Ok(ExportResult {
        output_path: options.output_path.clone(),
        total_rows: line.saturating_sub(1),
        exported_rows,
        skipped_rows,
        skipped_reasons,
    })
}
