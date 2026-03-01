import { invoke } from "@tauri-apps/api/core";
import type { ImportResult, RowRecordSummary } from "../types";

export async function importFiles(paths: string[]): Promise<ImportResult> {
  return invoke<ImportResult>("import_files", { paths });
}

export async function getAllRows(): Promise<RowRecordSummary[]> {
  return invoke<RowRecordSummary[]>("get_all_rows");
}

export async function updateField(
  rowId: string,
  field: string,
  value: string,
  autoLearn = false,
): Promise<unknown> {
  return invoke("update_field", { rowId, field, value, autoLearn });
}

export async function setRowStatus(rowId: string, status: string): Promise<unknown> {
  return invoke("set_row_status", { rowId, status });
}

export async function runOcrForRow(rowId: string): Promise<unknown> {
  return invoke("run_ocr_for_row", { rowId });
}

export async function exportExcel(outputPath: string, includeStatuses: string[]): Promise<unknown> {
  return invoke("export_excel_command", {
    options: {
      output_path: outputPath,
      include_statuses: includeStatuses,
      include_thumbnail: false,
      thumbnail_width: 0,
      column_order: null,
    },
  });
}

export async function saveMemoryEntry(ubn: string, name: string): Promise<void> {
  return invoke("save_memory_entry", { ubn, name });
}
