<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { open, save } from "@tauri-apps/plugin-dialog";
import {
  deleteTemplateRegion,
  exportExcel,
  getAllRows,
  getTemplates,
  importFiles,
  runOcrForRow,
  saveMemoryEntry,
  saveTemplateRegion,
  setRowStatus,
  updateField,
} from "./utils/tauri";
import RegionSelector from "./components/RegionSelector.vue";
import type { RegionRect, RowRecordSummary, TemplateMap } from "./types";

const rows = ref<RowRecordSummary[]>([]);
const selectedRowId = ref<string>("");
const editing = ref<{ rowId: string; field: string; value: string; ubn?: string } | null>(null);
const autoLearn = ref(false);
const exportMsg = ref("");

// Template region state
const showRegionSelector = ref(false);
const templates = ref<TemplateMap>({});

// The invoice_type for the currently selected row (user-assigned via RegionSelector)
// Since the OCR pipeline doesn't yet output invoice_type, we default to "三聯式"
const selectedInvoiceType = ref("三聯式");

const selectedRow = computed(() => rows.value.find((r) => r.id === selectedRowId.value) ?? null);
const isNameField = computed(() =>
  editing.value?.field === "seller_name" || editing.value?.field === "buyer_name",
);

const currentTemplate = computed(() =>
  templates.value[selectedInvoiceType.value] ?? null,
);

// Field colors (same order as RegionSelector.vue FIELDS)
const FIELD_KEYS = ["inv_no", "inv_date", "seller_ubn", "seller_name", "buyer_ubn", "buyer_name", "net_amount", "tax", "total"];
const FIELD_COLORS = ["#3b82f6", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#ec4899", "#14b8a6", "#f97316", "#6366f1"];

function fieldColor(key: string): string {
  const idx = FIELD_KEYS.indexOf(key);
  return idx >= 0 ? FIELD_COLORS[idx] : "#888";
}

async function refreshRows() {
  rows.value = await getAllRows();
  if (!selectedRowId.value && rows.value.length > 0) {
    selectedRowId.value = rows.value[0].id;
  }
}

async function refreshTemplates() {
  templates.value = await getTemplates();
}

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

function startEdit(row: RowRecordSummary, field: string) {
  const currentValue = ((row.fields as Record<string, string | undefined>)[field] ?? "").toString();
  const ubn = field === "seller_name" ? row.fields.seller_ubn : field === "buyer_name" ? row.fields.buyer_ubn : undefined;
  editing.value = { rowId: row.id, field, value: currentValue, ubn };
  autoLearn.value = false;
}

async function saveEdit() {
  if (!editing.value) return;
  await updateField(editing.value.rowId, editing.value.field, editing.value.value, autoLearn.value);
  if (autoLearn.value && isNameField.value && editing.value.ubn && editing.value.value) {
    await saveMemoryEntry(editing.value.ubn, editing.value.value);
  }
  editing.value = null;
  autoLearn.value = false;
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
  const statuses = ["OK", "Review", "Error"];
  await exportExcel(outputPath as string, statuses);
  exportMsg.value = "已匯出 ✓";
  setTimeout(() => (exportMsg.value = ""), 3000);
}

function statusClass(status: string): string {
  return (
    { OK: "status-ok", Review: "status-review", Error: "status-error", Excluded: "status-excluded" }[status] ?? ""
  );
}

// Template region handling
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

onMounted(async () => {
  await refreshRows();
  await refreshTemplates();
});
</script>

<template>
  <div class="app">
    <header class="toolbar">
      <button class="btn" @click="pickAndImportFiles">匯入檔案</button>
      <button class="btn danger" :disabled="!selectedRowId" @click="markExcluded">排除列</button>
      <button class="btn" :disabled="!selectedRowId" @click="rerunOcr">重跑 OCR</button>
      <button class="btn" @click="refreshRows">重新整理</button>
      <button class="btn template-btn" :disabled="!selectedRowId" @click="openRegionSelector">標記範本</button>
      <div class="spacer"></div>
      <span v-if="exportMsg" class="export-msg">{{ exportMsg }}</span>
      <button class="btn export-btn" @click="doExport">匯出 Excel</button>
    </header>

    <main class="content">
      <section class="table-pane">
        <table>
          <thead>
            <tr>
              <th>狀態</th>
              <th>來源</th>
              <th>分數</th>
              <th>問題</th>
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
              v-for="row in rows"
              :key="row.id"
              :class="{ selected: row.id === selectedRowId }"
              @click="selectedRowId = row.id"
            >
              <td><span class="status" :class="statusClass(row.status)">{{ row.status }}</span></td>
              <td>{{ row.source_label }}</td>
              <td>{{ Math.round((row.score ?? 0) * 100) }}</td>
              <td>{{ row.issue_count }}</td>
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

      <section class="viewer-pane">
        <div class="viewer-header">
          <span class="viewer-title">影像預覽</span>
          <!-- Show template overlay legend when regions exist -->
          <div v-if="currentTemplate && Object.keys(currentTemplate.regions).length" class="template-badge">
            {{ selectedInvoiceType }} 範本 {{ Object.keys(currentTemplate.regions).length }} 區域
          </div>
        </div>

        <!-- Image with template region overlay -->
        <div v-if="selectedRow" class="image-wrap">
          <img :src="selectedRow.thumb_url" alt="thumb" class="preview-image" />
          <!-- Overlay divs for template regions -->
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
        </div>
        <div v-else class="empty">尚未選取列</div>
      </section>
    </main>

    <!-- Edit dialog -->
    <div v-if="editing" class="editor">
      <div class="editor-card">
        <h3>編輯 {{ editing.field }}</h3>
        <input v-model="editing.value" @keyup.enter="saveEdit" @keyup.esc="editing = null" />

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

    <!-- Region Selector dialog -->
    <RegionSelector
      v-if="showRegionSelector && selectedRow"
      :image-src="selectedRow.thumb_url"
      :invoice-type="selectedInvoiceType"
      :existing-template="currentTemplate"
      @save="onRegionSave"
      @delete="onRegionDelete"
      @close="showRegionSelector = false"
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
.btn.danger { border-color: #d97070; color: #8f1d1d; }
.btn.export-btn { border-color: #3a7bd5; color: #1a4fa0; background: #eef4ff; }
.btn.template-btn { border-color: #7c3aed; color: #4c1d95; background: #f5f3ff; }

.export-msg { font-size: 13px; color: #1f7a2e; margin-right: 8px; }

.spacer { flex: 1; }

.content {
  flex: 1;
  display: grid;
  grid-template-columns: 58% 42%;
  min-height: 0;
}

.table-pane { overflow: auto; border-right: 1px solid #d5dce5; }

table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { border-bottom: 1px solid #e4e8ef; padding: 7px 8px; white-space: nowrap; }
thead th { position: sticky; top: 0; background: #f0f4fa; z-index: 1; }
tr.selected { background: #eaf2ff; }

.name-cell { max-width: 140px; overflow: hidden; text-overflow: ellipsis; display: inline-block; }

.status { display: inline-block; border-radius: 999px; padding: 2px 8px; font-size: 12px; }
.status-ok       { background: #d9f3dc; color: #1f7a2e; }
.status-review   { background: #fff2c6; color: #7b5a00; }
.status-error    { background: #ffd7d7; color: #a52020; }
.status-excluded { background: #ebedf1; color: #6d7480; }

.viewer-pane { padding: 12px; display: flex; flex-direction: column; }

.viewer-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.viewer-title { font-weight: 700; }

.template-badge {
  font-size: 11px;
  background: #f0ebff;
  color: #6d28d9;
  border-radius: 999px;
  padding: 2px 8px;
  border: 1px solid #ddd6fe;
}

.image-wrap {
  position: relative;
  flex: 1;
  min-height: 0;
}

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

.editor {
  position: fixed; inset: 0;
  background: rgba(15, 23, 42, 0.35);
  display: grid; place-items: center;
  z-index: 50;
}
.editor-card { width: 380px; padding: 20px; border-radius: 12px; background: #fff; }
.editor-card h3 { margin: 0 0 12px; font-size: 15px; }
.editor-card input[type="text"], .editor-card input:not([type="checkbox"]) {
  width: 100%; box-sizing: border-box; margin: 0 0 12px;
  border: 1px solid #c2ccda; border-radius: 8px; padding: 8px; font-size: 14px;
}
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
