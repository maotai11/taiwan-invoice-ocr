import { invoke } from "@tauri-apps/api/core";
import type { FuzzyResult, ImportResult, MemoryEntry, RegionRect, RowRecordSummary, TemplateMap } from "../types";

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

export async function saveMemoryEntry(ubn: string, name: string, invoiceType?: string): Promise<void> {
  return invoke("save_memory_entry", { ubn, name, invoiceType: invoiceType ?? null });
}

export async function lookupMemoryEntry(ubn: string): Promise<MemoryEntry | null> {
  return invoke<MemoryEntry | null>("lookup_memory_entry", { ubn });
}

export async function fuzzySearchMemory(query: string): Promise<FuzzyResult[]> {
  return invoke<FuzzyResult[]>("fuzzy_search_memory", { query });
}

export async function saveTemplateRegion(
  invoiceType: string,
  field: string,
  region: RegionRect,
): Promise<void> {
  return invoke("save_template_region", { invoiceType, field, region });
}

export async function getTemplates(): Promise<TemplateMap> {
  return invoke<TemplateMap>("get_templates");
}

export async function deleteTemplateRegion(invoiceType: string, field: string): Promise<void> {
  return invoke("delete_template_region", { invoiceType, field });
}
