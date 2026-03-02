<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { convertFileSrc } from "@tauri-apps/api/core";
import { open, save } from "@tauri-apps/plugin-dialog";
import {
  deleteTemplateRegion,
  exportExcel,
  fuzzySearchMemory,
  getAllRows,
  getTemplates,
  importFiles,
  runOcrForRow,
  saveMemoryEntry,
  saveTemplateRegion,
  setRowStatus,
  updateField,
} from "./utils/tauri";
import ConfidenceBar from "./components/ConfidenceBar.vue";
import InvoiceTypeBadge from "./components/InvoiceTypeBadge.vue";
import RegionSelector from "./components/RegionSelector.vue";
import TemplateManager from "./components/TemplateManager.vue";
import type { FuzzyResult, RegionRect, RowRecordSummary, TemplateMap } from "./types";

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
const rows = ref<RowRecordSummary[]>([]);
const selectedRowId = ref<string>("");
const editing = ref<{ rowId: string; field: string; value: string; ubn?: string } | null>(null);
const autoLearn = ref(false);
const exportMsg = ref("");
const statusFilter = ref<string>("all");
const lightboxSrc = ref<string>("");

// Template state
const showRegionSelector = ref(false);
const showTemplateManager = ref(false);
const templates = ref<TemplateMap>({});
const selectedInvoiceType = ref("三聯式");

// Fuzzy search suggestions (shown inside edit dialog for name fields)
const fuzzySuggestions = ref<FuzzyResult[]>([]);
let fuzzyTimer: ReturnType<typeof setTimeout> | null = null;

// ---------------------------------------------------------------------------
// Computed
// ---------------------------------------------------------------------------
const selectedRow = computed(() => rows.value.find((r) => r.id === selectedRowId.value) ?? null);
const isNameField = computed(() =>
  editing.value?.field === "seller_name" || editing.value?.field === "buyer_name",
);
const currentTemplate = computed(() => templates.value[selectedInvoiceType.value] ?? null);

const stats = computed(() => ({
  all:      rows.value.length,
  OK:       rows.value.filter((r) => r.status === "OK").length,
  Review:   rows.value.filter((r) => r.status === "Review").length,
  Error:    rows.value.filter((r) => r.status === "Error").length,
  Excluded: rows.value.filter((r) => r.status === "Excluded").length,
}));

const filteredRows = computed(() => {
  if (statusFilter.value === "all") return rows.value;
  return rows.value.filter((r) => r.status === statusFilter.value);
});

function toAssetUrl(path: string): string {
  if (!path) return "";
  if (/^(https?:|asset:|tauri:|blob:|data:)/i.test(path)) return path;
  return convertFileSrc(path);
}

const selectedRowAssetUrl = computed(() =>
  selectedRow.value?.thumb_url ? toAssetUrl(selectedRow.value.thumb_url) : "",
);

// Field colors (same order as RegionSelector FIELDS)
const FIELD_KEYS = ["inv_no", "inv_date", "seller_ubn", "seller_name", "buyer_ubn", "buyer_name", "net_amount", "tax", "total"];
const FIELD_COLORS = ["#3b82f6", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#ec4899", "#14b8a6", "#f97316", "#6366f1"];
function fieldColor(key: string): string {
  const idx = FIELD_KEYS.indexOf(key);
  return idx >= 0 ? FIELD_COLORS[idx] : "#888";
}

// ---------------------------------------------------------------------------
// Data fetch
// ---------------------------------------------------------------------------
async function refreshRows() {
  rows.value = await getAllRows();
  if (!selectedRowId.value && rows.value.length > 0) {
    selectedRowId.value = rows.value[0].id;
  }
}

async function refreshTemplates() {
  templates.value = await getTemplates();
}

// ---------------------------------------------------------------------------
// Import / OCR
// ---------------------------------------------------------------------------
async function pickAndImportFiles() {
  const selected = await open({
    multiple: true,
    directory: false,
    filters: [{ name: "Invoice Files", extensions: ["pdf", "jpg", "jpeg", "png", "webp", "tif", "tiff", "heic"] }],
  });
  if (!selected) return;
  const paths = Array.isArray(selected) ? selected : [selected];
  if (!paths.length) return;
  await importFiles(paths);
  await refreshRows();
}

async function markExcluded() {
  if (!selectedRowId.value) return;
  await setRowStatus(selectedRowId.value, "Excluded");
  await refreshRows();
}

async function rerunOcr() {
  if (!selectedRowId.value) return;
  await runOcrForRow(selectedRowId.value);
  await refreshRows();
}

async function doExport() {
  const outputPath = await save({
    filters: [{ name: "Excel", extensions: ["xlsx"] }],
    defaultPath: "invoices.xlsx",
  });
  if (!outputPath) return;
  await exportExcel(outputPath as string, ["OK", "Review", "Error"]);
  exportMsg.value = "已匯出 ✓";
  setTimeout(() => (exportMsg.value = ""), 3000);
}

// ---------------------------------------------------------------------------
// Keyboard navigation
// ---------------------------------------------------------------------------
function handleKeydown(e: KeyboardEvent) {
  if (editing.value || lightboxSrc.value) return;
  const list = filteredRows.value;
  const idx = list.findIndex((r) => r.id === selectedRowId.value);
  if (e.key === "ArrowDown" || e.key === "j") {
    e.preventDefault();
    if (idx < list.length - 1) selectedRowId.value = list[idx + 1].id;
  } else if (e.key === "ArrowUp" || e.key === "k") {
    e.preventDefault();
    if (idx > 0) selectedRowId.value = list[idx - 1].id;
  }
}

onMounted(async () => {
  await refreshRows();
  await refreshTemplates();
  window.addEventListener("keydown", handleKeydown);
});

onUnmounted(() => {
  window.removeEventListener("keydown", handleKeydown);
});

// ---------------------------------------------------------------------------
// Edit dialog
// ---------------------------------------------------------------------------
function startEdit(row: RowRecordSummary, field: string) {
  const currentValue = ((row.fields as Record<string, string | undefined>)[field] ?? "").toString();
  const ubn = field === "seller_name" ? row.fields.seller_ubn
             : field === "buyer_name"  ? row.fields.buyer_ubn
             : undefined;
  editing.value = { rowId: row.id, field, value: currentValue, ubn };
  autoLearn.value = false;
  fuzzySuggestions.value = [];
}

// Auto-sync invoice type picker with selected row's classified type
watch(selectedRow, (row) => {
  if (row?.fields.invoice_type) {
    selectedInvoiceType.value = row.fields.invoice_type;
  }
});

// Debounced fuzzy search while user types in name field
watch(
  () => editing.value?.value,
  (val) => {
    if (!isNameField.value || !val || val.length < 2) {
      fuzzySuggestions.value = [];
      return;
    }
    if (fuzzyTimer) clearTimeout(fuzzyTimer);
    fuzzyTimer = setTimeout(async () => {
      fuzzySuggestions.value = await fuzzySearchMemory(val);
    }, 300);
  },
);

function applySuggestion(name: string) {
  if (!editing.value) return;
  editing.value.value = name;
  fuzzySuggestions.value = [];
}

async function saveEdit() {
  if (!editing.value) return;
  await updateField(editing.value.rowId, editing.value.field, editing.value.value, autoLearn.value);
  if (autoLearn.value && isNameField.value && editing.value.ubn && editing.value.value) {
    await saveMemoryEntry(editing.value.ubn, editing.value.value, selectedInvoiceType.value);
  }
  editing.value = null;
  autoLearn.value = false;
  fuzzySuggestions.value = [];
  await refreshRows();
}

// ---------------------------------------------------------------------------
// Template region
// ---------------------------------------------------------------------------
function openRegionSelector() {
  showRegionSelector.value = true;
}

async function onRegionSave(field: string, region: RegionRect) {
  await saveTemplateRegion(selectedInvoiceType.value, field, region);
  await refreshTemplates();
}

async function onRegionDelete(field: string) {
  await deleteTemplateRegion(selectedInvoiceType.value, field);
  await refreshTemplates();
}

async function onManagerDelete(invType: string, field: string) {
  await deleteTemplateRegion(invType, field);
  await refreshTemplates();
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function statusClass(status: string): string {
  return (
    { OK: "status-ok", Review: "status-review", Error: "status-error", Excluded: "status-excluded" }[status] ?? ""
  );
}
</script>

<template>
  <div class="app">
    <!-- ------------------------------------------------------------------ Toolbar -->
    <header class="toolbar">
      <button class="btn" @click="pickAndImportFiles">匯入檔案</button>
      <button class="btn danger" :disabled="!selectedRowId" @click="markExcluded">排除列</button>
      <button class="btn" :disabled="!selectedRowId" @click="rerunOcr">重跑 OCR</button>
      <button class="btn" @click="refreshRows">重新整理</button>
      <button class="btn template-btn" :disabled="!selectedRowId" @click="openRegionSelector">標記範本</button>
      <button class="btn manage-btn" @click="showTemplateManager = true">範本管理</button>
      <div class="spacer"></div>
      <span v-if="exportMsg" class="export-msg">{{ exportMsg }}</span>
      <button class="btn export-btn" @click="doExport">匯出 Excel</button>
    </header>

    <!-- ------------------------------------------------------------------ Stats bar -->
    <div class="stats-bar">
      <button
        v-for="[key, label] in [['all','全部'],['OK','OK'],['Review','待確認'],['Error','錯誤'],['Excluded','已排除']] as [string,string][]"
        :key="key"
        class="stat-chip"
        :class="[`chip-${key}`, { active: statusFilter === key }]"
        @click="statusFilter = key"
      >
        {{ label }}
        <span class="stat-num">{{ key === 'all' ? stats.all : stats[key as keyof typeof stats] }}</span>
      </button>
    </div>

    <!-- ------------------------------------------------------------------ Content -->
    <main class="content">
      <!-- Table pane -->
      <section class="table-pane">
        <table>
          <thead>
            <tr>
              <th>狀態</th>
              <th>來源</th>
              <th>信心</th>
              <th>問題</th>
              <th>類型</th>
              <th>發票號碼</th>
              <th>日期</th>
              <th>賣方統編</th>
              <th>賣方名稱</th>
              <th>買方統編</th>
              <th>買方名稱</th>
              <th>總計</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="row in filteredRows"
              :key="row.id"
              :class="{ selected: row.id === selectedRowId, review: row.status === 'Review' }"
              @click="selectedRowId = row.id"
            >
              <td><span class="status" :class="statusClass(row.status)">{{ row.status }}</span></td>
              <td>{{ row.source_label }}</td>
              <td class="td-confidence">
                <ConfidenceBar :score="row.score ?? 0" :show-pct="false" />
              </td>
              <td>
                {{ row.issue_count }}
                <span v-if="row.cross_validations?.length" class="cv-badge" title="數值差異">⚠️{{ row.cross_validations.length }}</span>
              </td>
              <td>
                <span v-if="row.fields.invoice_type" class="type-chip">{{ row.fields.invoice_type }}</span>
              </td>
              <td @dblclick.stop="startEdit(row, 'inv_no')">{{ row.fields.inv_no ?? "" }}</td>
              <td @dblclick.stop="startEdit(row, 'inv_date')">{{ row.fields.inv_date ?? "" }}</td>
              <td @dblclick.stop="startEdit(row, 'seller_ubn')">{{ row.fields.seller_ubn ?? "" }}</td>
              <td @dblclick.stop="startEdit(row, 'seller_name')">
                <span class="name-cell">{{ row.fields.seller_name ?? "" }}</span>
              </td>
              <td @dblclick.stop="startEdit(row, 'buyer_ubn')">{{ row.fields.buyer_ubn ?? "" }}</td>
              <td @dblclick.stop="startEdit(row, 'buyer_name')">
                <span class="name-cell">{{ row.fields.buyer_name ?? "" }}</span>
              </td>
              <td @dblclick.stop="startEdit(row, 'total')">{{ row.fields.total ?? "" }}</td>
            </tr>
          </tbody>
        </table>
      </section>

      <!-- Viewer pane -->
      <section class="viewer-pane">
        <div class="viewer-header">
          <span class="viewer-title">影像預覽</span>

          <!-- Invoice type picker -->
          <select v-model="selectedInvoiceType" class="type-select" title="發票類型">
            <option v-for="t in ['三聯式','二聯式','電子發票','收銀機','特種','手開']" :key="t" :value="t">{{ t }}</option>
          </select>

          <InvoiceTypeBadge :invoice-type="selectedInvoiceType" />

          <!-- Template regions indicator -->
          <span
            v-if="currentTemplate && Object.keys(currentTemplate.regions).length"
            class="template-badge"
          >
            範本 {{ Object.keys(currentTemplate.regions).length }} 區域
          </span>

          <!-- Keyboard hint -->
          <span class="kbd-hint">↑↓ 換列</span>
        </div>

        <!-- Confidence detail for selected row -->
        <div v-if="selectedRow" class="score-row">
          <ConfidenceBar :score="selectedRow.score ?? 0" label="整體信心" />
        </div>

        <!-- Cross-validation mismatches -->
        <div v-if="selectedRow?.cross_validations?.length" class="mismatch-panel">
          <div class="mismatch-title">⚠️ 數值差異（需人工確認）</div>
          <table class="mismatch-table">
            <thead>
              <tr><th>欄位</th><th>PaddleOCR</th><th>Qwen-VL</th></tr>
            </thead>
            <tbody>
              <tr v-for="cv in selectedRow.cross_validations" :key="cv.field">
                <td class="cv-field">{{ cv.field }}</td>
                <td class="cv-paddle">{{ cv.paddle_val }}</td>
                <td class="cv-qwen">{{ cv.qwen_val }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- Image with overlay — click to open lightbox -->
        <div v-if="selectedRow" class="image-wrap" @click="lightboxSrc = selectedRowAssetUrl">
          <img :src="selectedRowAssetUrl" alt="thumb" class="preview-image" />
          <div
            v-for="(rect, fieldKey) in currentTemplate?.regions ?? {}"
            :key="fieldKey"
            class="region-overlay"
            :style="{
              left: (rect.x * 100) + '%',
              top: (rect.y * 100) + '%',
              width: (rect.w * 100) + '%',
              height: (rect.h * 100) + '%',
              borderColor: fieldColor(fieldKey),
              background: fieldColor(fieldKey) + '22',
            }"
          >
            <span class="region-label" :style="{ color: fieldColor(fieldKey) }">{{ fieldKey }}</span>
          </div>
          <div class="zoom-hint">點擊放大</div>
        </div>
        <div v-else class="empty">尚未選取列</div>
      </section>
    </main>

    <!-- ------------------------------------------------------------------ Edit dialog -->
    <div v-if="editing" class="editor">
      <div class="editor-card">
        <h3>編輯 {{ editing.field }}</h3>
        <input v-model="editing.value" @keyup.enter="saveEdit" @keyup.esc="editing = null" />

        <!-- Fuzzy suggestions for name fields -->
        <div v-if="isNameField && fuzzySuggestions.length" class="suggestions">
          <div class="suggestions-title">記憶中的近似結果：</div>
          <button
            v-for="r in fuzzySuggestions"
            :key="r.ubn"
            class="suggestion-item"
            @click="applySuggestion(r.entry.name)"
          >
            <span class="sug-name">{{ r.entry.name }}</span>
            <span class="sug-meta">統編 {{ r.ubn }} · {{ Math.round(r.score * 100) }}%</span>
          </button>
        </div>

        <!-- Auto-learn for name fields with known UBN -->
        <label v-if="isNameField && editing.ubn" class="learn-label">
          <input type="checkbox" v-model="autoLearn" />
          記住此名稱（統編 {{ editing.ubn }}）
        </label>

        <div class="editor-actions">
          <button class="btn" @click="saveEdit">儲存</button>
          <button class="btn" @click="editing = null">取消</button>
        </div>
      </div>
    </div>

    <!-- ------------------------------------------------------------------ Lightbox -->
    <div v-if="lightboxSrc" class="lightbox" @click="lightboxSrc = ''">
      <img :src="lightboxSrc" class="lightbox-img" @click.stop />
      <button class="lightbox-close" @click="lightboxSrc = ''">✕</button>
    </div>

    <!-- ------------------------------------------------------------------ Region Selector -->
    <RegionSelector
      v-if="showRegionSelector && selectedRow"
      :image-src="selectedRowAssetUrl"
      :invoice-type="selectedInvoiceType"
      :existing-template="currentTemplate"
      @save="onRegionSave"
      @delete="onRegionDelete"
      @close="showRegionSelector = false"
    />

    <!-- ------------------------------------------------------------------ Template Manager -->
    <TemplateManager
      v-if="showTemplateManager"
      :templates="templates"
      @delete="onManagerDelete"
      @close="showTemplateManager = false"
    />
  </div>
</template>

<style scoped>
.app {
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: linear-gradient(180deg, #f6f7f9 0%, #eef2f7 100%);
  color: #213547;
  font-family: "Noto Sans TC", "Microsoft JhengHei", sans-serif;
}

/* Toolbar */
.toolbar {
  height: 56px;
  display: flex;
  align-items: center;
  padding: 0 12px;
  border-bottom: 1px solid #d5dce5;
  background: #fff;
}

.btn {
  border: 1px solid #bcc7d6;
  border-radius: 8px;
  padding: 8px 12px;
  background: #fff;
  cursor: pointer;
  margin-right: 8px;
  font-size: 13px;
}
.btn:disabled { opacity: 0.4; cursor: default; }
.btn.danger      { border-color: #d97070; color: #8f1d1d; }
.btn.export-btn  { border-color: #3a7bd5; color: #1a4fa0; background: #eef4ff; }
.btn.template-btn { border-color: #7c3aed; color: #4c1d95; background: #f5f3ff; }
.btn.manage-btn  { border-color: #0891b2; color: #0e4f62; background: #ecfeff; }

.export-msg { font-size: 13px; color: #1f7a2e; margin-right: 8px; }
.spacer { flex: 1; }

/* Stats bar */
.stats-bar {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  background: #f8fafc;
  border-bottom: 1px solid #e4e8ef;
}

.stat-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 3px 10px;
  border-radius: 999px;
  border: 1px solid #d1d9e4;
  background: #fff;
  font-size: 12px;
  cursor: pointer;
  color: #374151;
  transition: all 0.15s;
}
.stat-chip:hover { border-color: #94a3b8; }
.stat-chip.active { font-weight: 700; }

.stat-num {
  font-size: 11px;
  font-weight: 700;
  background: #e9ecf0;
  border-radius: 999px;
  padding: 0 5px;
  line-height: 1.6;
}

.chip-all.active    { background: #f0f4fa; border-color: #7090b8; color: #1e3a5f; }
.chip-OK.active     { background: #d9f3dc; border-color: #5aab68; color: #1f5a28; }
.chip-Review.active { background: #fff2c6; border-color: #e0b820; color: #7b5a00; }
.chip-Error.active  { background: #ffd7d7; border-color: #d05050; color: #a52020; }
.chip-Excluded.active { background: #ebedf1; border-color: #9099aa; color: #3d4452; }

.chip-OK .stat-num     { background: #b4e8bc; }
.chip-Review .stat-num { background: #fde68a; }
.chip-Error .stat-num  { background: #fca5a5; }

/* Layout */
.content {
  flex: 1;
  display: grid;
  grid-template-columns: 58% 42%;
  min-height: 0;
}

/* Table */
.table-pane { overflow: auto; border-right: 1px solid #d5dce5; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { border-bottom: 1px solid #e4e8ef; padding: 7px 8px; white-space: nowrap; }
thead th { position: sticky; top: 0; background: #f0f4fa; z-index: 1; }
tr.selected { background: #eaf2ff; }
tr.review td { background: #fffbe6; }
tr.review.selected td { background: #fff3cc; }

.name-cell { max-width: 140px; overflow: hidden; text-overflow: ellipsis; display: inline-block; }
.td-confidence { min-width: 70px; }

.status { display: inline-block; border-radius: 999px; padding: 2px 8px; font-size: 12px; }
.status-ok       { background: #d9f3dc; color: #1f7a2e; }
.status-review   { background: #fff2c6; color: #7b5a00; }
.status-error    { background: #ffd7d7; color: #a52020; }
.status-excluded { background: #ebedf1; color: #6d7480; }

.type-chip {
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 4px;
  background: #f0ebff;
  color: #5b21b6;
  border: 1px solid #ddd6fe;
  white-space: nowrap;
}

/* Viewer */
.viewer-pane { padding: 12px; display: flex; flex-direction: column; gap: 6px; }

.viewer-header {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.viewer-title { font-weight: 700; }

.type-select {
  font-size: 12px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  padding: 3px 6px;
  background: #fff;
  cursor: pointer;
}

.template-badge {
  font-size: 11px;
  background: #f0ebff;
  color: #6d28d9;
  border-radius: 999px;
  padding: 2px 8px;
  border: 1px solid #ddd6fe;
}

.kbd-hint {
  font-size: 11px;
  color: #94a3b8;
  margin-left: auto;
}

.score-row { flex-shrink: 0; }

.mismatch-panel {
  flex-shrink: 0;
  margin: 6px 8px;
  border: 1px solid #fde68a;
  border-radius: 6px;
  background: #fffbeb;
  overflow: hidden;
}
.mismatch-title {
  padding: 5px 10px;
  font-size: 11px;
  font-weight: 600;
  color: #92400e;
  background: #fef3c7;
  border-bottom: 1px solid #fde68a;
}
.mismatch-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 11px;
}
.mismatch-table th {
  padding: 3px 8px;
  text-align: left;
  color: #78350f;
  font-weight: 600;
  background: #fef9c3;
}
.mismatch-table td { padding: 3px 8px; border-top: 1px solid #fde68a; }
.cv-field { font-family: monospace; color: #374151; }
.cv-paddle { color: #1d4ed8; font-weight: 600; }
.cv-qwen   { color: #b45309; font-weight: 600; }

.cv-badge {
  margin-left: 4px;
  font-size: 10px;
  font-weight: 700;
  color: #92400e;
  background: #fef3c7;
  border: 1px solid #fde68a;
  border-radius: 4px;
  padding: 0 3px;
  vertical-align: middle;
}

.image-wrap {
  position: relative;
  flex: 1;
  min-height: 0;
  cursor: zoom-in;
}

.zoom-hint {
  position: absolute;
  bottom: 6px;
  right: 8px;
  font-size: 11px;
  color: #fff;
  background: rgba(0,0,0,0.45);
  border-radius: 4px;
  padding: 2px 6px;
  pointer-events: none;
  opacity: 0;
  transition: opacity 0.2s;
}
.image-wrap:hover .zoom-hint { opacity: 1; }

.preview-image {
  width: 100%;
  height: 100%;
  object-fit: contain;
  border: 1px solid #cbd4e2;
  background: #fff;
  display: block;
}

.region-overlay {
  position: absolute;
  border: 2px solid;
  pointer-events: none;
  box-sizing: border-box;
}

.region-label {
  font-size: 10px;
  font-weight: 700;
  position: absolute;
  top: 1px;
  left: 2px;
  line-height: 1;
}

.empty { color: #6b7280; }

/* Lightbox */
.lightbox {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.82);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
  cursor: zoom-out;
}

.lightbox-img {
  max-width: 90vw;
  max-height: 90vh;
  object-fit: contain;
  border-radius: 4px;
  box-shadow: 0 8px 40px rgba(0,0,0,0.6);
  cursor: default;
}

.lightbox-close {
  position: absolute;
  top: 16px;
  right: 20px;
  background: rgba(255,255,255,0.15);
  border: none;
  color: #fff;
  font-size: 20px;
  width: 36px;
  height: 36px;
  border-radius: 50%;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  line-height: 1;
}
.lightbox-close:hover { background: rgba(255,255,255,0.3); }

/* Edit dialog */
.editor {
  position: fixed; inset: 0;
  background: rgba(15, 23, 42, 0.35);
  display: grid; place-items: center;
  z-index: 50;
}
.editor-card {
  width: 400px;
  padding: 20px;
  border-radius: 12px;
  background: #fff;
}
.editor-card h3 { margin: 0 0 12px; font-size: 15px; }
.editor-card input[type="text"],
.editor-card input:not([type="checkbox"]) {
  width: 100%; box-sizing: border-box; margin: 0 0 10px;
  border: 1px solid #c2ccda; border-radius: 8px; padding: 8px; font-size: 14px;
}

/* Fuzzy suggestions */
.suggestions {
  margin-bottom: 10px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  overflow: hidden;
}
.suggestions-title {
  font-size: 11px;
  color: #64748b;
  padding: 5px 8px;
  background: #f8fafc;
  border-bottom: 1px solid #e2e8f0;
}
.suggestion-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  width: 100%;
  padding: 6px 10px;
  border: none;
  border-bottom: 1px solid #f1f5f9;
  background: #fff;
  cursor: pointer;
  text-align: left;
  font-size: 13px;
}
.suggestion-item:last-child { border-bottom: none; }
.suggestion-item:hover { background: #f0f9ff; }
.sug-name { font-weight: 500; color: #1e293b; }
.sug-meta { font-size: 11px; color: #94a3b8; }

.learn-label {
  display: flex; align-items: center; gap: 8px;
  font-size: 13px; color: #3a5fa0; margin-bottom: 14px; cursor: pointer;
}
.learn-label input[type="checkbox"] { width: 15px; height: 15px; cursor: pointer; }
.editor-actions { display: flex; justify-content: flex-end; gap: 8px; }

@media (max-width: 1024px) {
  .content { grid-template-columns: 1fr; grid-template-rows: 55% 45%; }
  .table-pane { border-right: 0; border-bottom: 1px solid #d5dce5; }
}
</style>
