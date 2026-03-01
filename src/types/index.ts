export type RowStatus = "OK" | "Review" | "Error" | "Excluded";

export interface InvoiceFieldsSummary {
  inv_no?: string;
  inv_date?: string;
  seller_ubn?: string;
  seller_name?: string;
  buyer_ubn?: string;
  buyer_name?: string;
  net_amount?: string;
  tax?: string;
  total?: string;
  tax_type?: string;
  invoice_type?: string;
}

export interface RowRecordSummary {
  id: string;
  status: RowStatus;
  source_label: string;
  thumb_url: string;
  template_name?: string;
  score: number;
  issue_count: number;
  fields: InvoiceFieldsSummary;
}

export interface ImportResult {
  job_id: string;
  total_files: number;
  total_pages: number;
}

export interface RegionRect {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface InvoiceTemplate {
  version: number;
  regions: Record<string, RegionRect>;
}

export type TemplateMap = Record<string, InvoiceTemplate>;

export interface MemoryEntry {
  name: string;
  invoice_type?: string;
  use_count: number;
  last_seen: string;
  aliases: string[];
}

export interface FuzzyResult {
  ubn: string;
  entry: MemoryEntry;
  score: number;
}
