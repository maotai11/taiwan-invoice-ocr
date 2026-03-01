<script setup lang="ts">
import type { TemplateMap } from "../types";

const FIELD_LABELS: Record<string, string> = {
  inv_no: "發票號碼",
  inv_date: "日期",
  seller_ubn: "賣方統編",
  seller_name: "賣方名稱",
  buyer_ubn: "買方統編",
  buyer_name: "買方名稱",
  net_amount: "銷售額",
  tax: "稅額",
  total: "總計",
};

const FIELD_COLORS = [
  "#3b82f6", "#10b981", "#f59e0b", "#ef4444",
  "#8b5cf6", "#ec4899", "#14b8a6", "#f97316", "#6366f1",
];
const FIELD_KEYS = Object.keys(FIELD_LABELS);

function fieldColor(key: string): string {
  const idx = FIELD_KEYS.indexOf(key);
  return idx >= 0 ? FIELD_COLORS[idx] : "#888";
}

function pct(v: number): string {
  return Math.round(v * 100) + "%";
}

defineProps<{ templates: TemplateMap }>();
const emit = defineEmits<{
  (e: "delete", invoiceType: string, field: string): void;
  (e: "close"): void;
}>();
</script>

<template>
  <div class="tm-overlay" @click.self="emit('close')">
    <div class="tm-dialog">
      <div class="tm-header">
        <span class="tm-title">範本管理</span>
        <button class="tm-close" @click="emit('close')">✕</button>
      </div>

      <div class="tm-body">
        <div v-if="Object.keys(templates).length === 0" class="tm-empty">
          尚未學習任何範本。<br />
          選取一列發票後按「標記範本」開始學習。
        </div>

        <div v-for="(template, invType) in templates" :key="invType" class="tm-group">
          <div class="tm-group-header">
            <span class="tm-type-label">{{ invType }}</span>
            <span class="tm-count">{{ Object.keys(template.regions).length }} 個區域</span>
          </div>

          <table class="tm-table">
            <thead>
              <tr>
                <th>欄位</th>
                <th>X</th>
                <th>Y</th>
                <th>寬</th>
                <th>高</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(rect, fieldKey) in template.regions" :key="fieldKey">
                <td>
                  <span class="tm-field-dot" :style="{ background: fieldColor(fieldKey) }"></span>
                  {{ FIELD_LABELS[fieldKey] ?? fieldKey }}
                </td>
                <td class="tm-num">{{ pct(rect.x) }}</td>
                <td class="tm-num">{{ pct(rect.y) }}</td>
                <td class="tm-num">{{ pct(rect.w) }}</td>
                <td class="tm-num">{{ pct(rect.h) }}</td>
                <td>
                  <button
                    class="tm-del"
                    title="刪除此區域"
                    @click="emit('delete', invType, fieldKey)"
                  >✕</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.tm-overlay {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  display: grid;
  place-items: center;
  z-index: 100;
}

.tm-dialog {
  width: 560px;
  max-width: 94vw;
  max-height: 80vh;
  background: #fff;
  border-radius: 12px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.tm-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid #e2e8f0;
  background: #f8fafc;
}

.tm-title { font-weight: 700; font-size: 15px; }

.tm-close {
  border: none;
  background: none;
  font-size: 18px;
  cursor: pointer;
  color: #6b7280;
  padding: 0 4px;
}

.tm-body {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.tm-empty {
  color: #94a3b8;
  font-size: 14px;
  text-align: center;
  padding: 32px 0;
  line-height: 1.8;
}

.tm-group {}

.tm-group-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.tm-type-label {
  font-weight: 700;
  font-size: 14px;
  color: #1e293b;
}

.tm-count {
  font-size: 12px;
  color: #64748b;
  background: #f1f5f9;
  border-radius: 999px;
  padding: 2px 8px;
}

.tm-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.tm-table th {
  text-align: left;
  padding: 5px 8px;
  background: #f8fafc;
  color: #64748b;
  font-size: 11px;
  font-weight: 600;
  border-bottom: 1px solid #e2e8f0;
}

.tm-table td {
  padding: 6px 8px;
  border-bottom: 1px solid #f1f5f9;
  vertical-align: middle;
}

.tm-field-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-right: 5px;
  vertical-align: middle;
}

.tm-num {
  color: #475569;
  font-variant-numeric: tabular-nums;
  font-size: 12px;
}

.tm-del {
  border: none;
  background: none;
  color: #9ca3af;
  cursor: pointer;
  font-size: 12px;
  padding: 2px 4px;
  border-radius: 4px;
}

.tm-del:hover {
  color: #ef4444;
  background: #fef2f2;
}
</style>
