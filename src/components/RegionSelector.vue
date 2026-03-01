<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import type { InvoiceTemplate, RegionRect } from "../types";

const props = defineProps<{
  imageSrc: string;
  invoiceType: string;
  existingTemplate: InvoiceTemplate | null;
}>();

const emit = defineEmits<{
  (e: "save", field: string, region: RegionRect): void;
  (e: "delete", field: string): void;
  (e: "close"): void;
}>();

const INVOICE_TYPES = ["三聯式", "二聯式", "電子發票", "收銀機", "特種", "手開"];
const FIELDS = [
  { key: "inv_no", label: "發票號碼" },
  { key: "inv_date", label: "日期" },
  { key: "seller_ubn", label: "賣方統編" },
  { key: "seller_name", label: "賣方名稱" },
  { key: "buyer_ubn", label: "買方統編" },
  { key: "buyer_name", label: "買方名稱" },
  { key: "net_amount", label: "銷售額" },
  { key: "tax", label: "稅額" },
  { key: "total", label: "總計" },
];

// Colours per field index for overlay rectangles
const FIELD_COLORS = [
  "#3b82f6", "#10b981", "#f59e0b", "#ef4444",
  "#8b5cf6", "#ec4899", "#14b8a6", "#f97316", "#6366f1",
];

const canvasRef = ref<HTMLCanvasElement | null>(null);
const imgRef = ref<HTMLImageElement | null>(null);
const selectedField = ref(FIELDS[0].key);

// Drag state (in canvas pixels)
const dragging = ref(false);
const dragStart = ref({ x: 0, y: 0 });
const dragEnd = ref({ x: 0, y: 0 });

// Current draft rect (relative %, updated after drag ends)
const draftRect = ref<RegionRect | null>(null);

const currentInvoiceType = ref(props.invoiceType || INVOICE_TYPES[0]);

// Existing regions for this invoice type
const existingRegions = computed(() => props.existingTemplate?.regions ?? {});

function getFieldColor(fieldKey: string): string {
  const idx = FIELDS.findIndex((f) => f.key === fieldKey);
  return FIELD_COLORS[idx % FIELD_COLORS.length];
}

// Draw everything on canvas
function redraw() {
  const canvas = canvasRef.value;
  const img = imgRef.value;
  if (!canvas || !img || img.naturalWidth === 0) return;

  const ctx = canvas.getContext("2d")!;
  canvas.width = img.clientWidth;
  canvas.height = img.clientHeight;
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  const cw = canvas.width;
  const ch = canvas.height;

  // Draw existing saved regions
  for (const [fieldKey, rect] of Object.entries(existingRegions.value)) {
    const color = getFieldColor(fieldKey);
    const px = rect.x * cw;
    const py = rect.y * ch;
    const pw = rect.w * cw;
    const ph = rect.h * ch;
    ctx.save();
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.fillStyle = color + "33"; // 20% opacity fill
    ctx.fillRect(px, py, pw, ph);
    ctx.strokeRect(px, py, pw, ph);
    // Label
    const label = FIELDS.find((f) => f.key === fieldKey)?.label ?? fieldKey;
    ctx.fillStyle = color;
    ctx.font = "bold 12px sans-serif";
    ctx.fillText(label, px + 3, py + 14);
    ctx.restore();
  }

  // Draw current drag selection
  if (dragging.value || draftRect.value) {
    let px: number, py: number, pw: number, ph: number;
    if (dragging.value) {
      px = Math.min(dragStart.value.x, dragEnd.value.x);
      py = Math.min(dragStart.value.y, dragEnd.value.y);
      pw = Math.abs(dragEnd.value.x - dragStart.value.x);
      ph = Math.abs(dragEnd.value.y - dragStart.value.y);
    } else {
      const r = draftRect.value!;
      px = r.x * cw; py = r.y * ch; pw = r.w * cw; ph = r.h * ch;
    }
    ctx.save();
    ctx.strokeStyle = "#1d4ed8";
    ctx.lineWidth = 2;
    ctx.setLineDash([6, 3]);
    ctx.fillStyle = "#3b82f622";
    ctx.fillRect(px, py, pw, ph);
    ctx.strokeRect(px, py, pw, ph);
    ctx.restore();
  }
}

function canvasCoords(e: MouseEvent): { x: number; y: number } {
  const canvas = canvasRef.value!;
  const rect = canvas.getBoundingClientRect();
  return { x: e.clientX - rect.left, y: e.clientY - rect.top };
}

function onMouseDown(e: MouseEvent) {
  const pos = canvasCoords(e);
  dragging.value = true;
  dragStart.value = pos;
  dragEnd.value = pos;
  draftRect.value = null;
  redraw();
}

function onMouseMove(e: MouseEvent) {
  if (!dragging.value) return;
  dragEnd.value = canvasCoords(e);
  redraw();
}

function onMouseUp(e: MouseEvent) {
  if (!dragging.value) return;
  dragging.value = false;
  dragEnd.value = canvasCoords(e);

  const canvas = canvasRef.value!;
  const cw = canvas.width;
  const ch = canvas.height;

  const x = Math.min(dragStart.value.x, dragEnd.value.x) / cw;
  const y = Math.min(dragStart.value.y, dragEnd.value.y) / ch;
  const w = Math.abs(dragEnd.value.x - dragStart.value.x) / cw;
  const h = Math.abs(dragEnd.value.y - dragStart.value.y) / ch;

  if (w < 0.01 || h < 0.01) {
    // Too small, ignore
    draftRect.value = null;
    redraw();
    return;
  }

  draftRect.value = { x, y, w, h };
  redraw();
}

function saveRegion() {
  if (!draftRect.value) return;
  emit("save", selectedField.value, draftRect.value);
  draftRect.value = null;
  redraw();
}

function deleteRegion(fieldKey: string) {
  emit("delete", fieldKey);
}

watch(() => props.existingTemplate, redraw);
watch(selectedField, redraw);

onMounted(() => {
  const img = imgRef.value;
  if (img) {
    if (img.complete) redraw();
    else img.addEventListener("load", redraw);
  }
  window.addEventListener("resize", redraw);
});

onUnmounted(() => {
  window.removeEventListener("resize", redraw);
});
</script>

<template>
  <div class="rs-overlay" @click.self="emit('close')">
    <div class="rs-dialog">
      <div class="rs-header">
        <span class="rs-title">標記範本區域</span>
        <button class="rs-close" @click="emit('close')">✕</button>
      </div>

      <div class="rs-body">
        <!-- Left: controls -->
        <div class="rs-controls">
          <label class="rs-label">發票類型</label>
          <select v-model="currentInvoiceType" class="rs-select">
            <option v-for="t in INVOICE_TYPES" :key="t" :value="t">{{ t }}</option>
          </select>

          <label class="rs-label">框選欄位</label>
          <select v-model="selectedField" class="rs-select">
            <option v-for="f in FIELDS" :key="f.key" :value="f.key">{{ f.label }}</option>
          </select>

          <button
            class="rs-btn rs-btn-primary"
            :disabled="!draftRect"
            @click="saveRegion"
          >
            儲存此區域
          </button>

          <div class="rs-legend">
            <div class="rs-legend-title">已學習區域</div>
            <div
              v-for="(rect, fieldKey) in existingRegions"
              :key="fieldKey"
              class="rs-legend-item"
            >
              <span
                class="rs-legend-dot"
                :style="{ background: getFieldColor(fieldKey) }"
              ></span>
              <span class="rs-legend-name">{{ FIELDS.find((f) => f.key === fieldKey)?.label ?? fieldKey }}</span>
              <button class="rs-delete" @click="deleteRegion(fieldKey)">✕</button>
            </div>
            <div v-if="Object.keys(existingRegions).length === 0" class="rs-legend-empty">
              尚未學習任何區域
            </div>
          </div>

          <div class="rs-hint">
            在圖片上拖曳以框選欄位位置，<br />選好後按「儲存此區域」。
          </div>
        </div>

        <!-- Right: image + canvas overlay -->
        <div class="rs-canvas-wrap">
          <img
            ref="imgRef"
            :src="imageSrc"
            class="rs-img"
            draggable="false"
            @load="redraw"
          />
          <canvas
            ref="canvasRef"
            class="rs-canvas"
            @mousedown="onMouseDown"
            @mousemove="onMouseMove"
            @mouseup="onMouseUp"
          ></canvas>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.rs-overlay {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.55);
  display: grid;
  place-items: center;
  z-index: 100;
}

.rs-dialog {
  width: 900px;
  max-width: 96vw;
  height: 620px;
  max-height: 92vh;
  background: #fff;
  border-radius: 12px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.rs-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid #e2e8f0;
  background: #f8fafc;
}

.rs-title { font-weight: 700; font-size: 15px; }

.rs-close {
  border: none;
  background: none;
  font-size: 18px;
  cursor: pointer;
  color: #6b7280;
  padding: 0 4px;
}

.rs-body {
  flex: 1;
  display: flex;
  min-height: 0;
}

/* Controls panel */
.rs-controls {
  width: 190px;
  min-width: 190px;
  padding: 14px 12px;
  border-right: 1px solid #e2e8f0;
  display: flex;
  flex-direction: column;
  gap: 8px;
  overflow-y: auto;
}

.rs-label {
  font-size: 12px;
  font-weight: 600;
  color: #64748b;
  margin-top: 4px;
}

.rs-select {
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  padding: 5px 8px;
  font-size: 13px;
  width: 100%;
}

.rs-btn {
  border-radius: 6px;
  padding: 7px 10px;
  font-size: 13px;
  cursor: pointer;
  border: 1px solid #cbd5e1;
  background: #fff;
  margin-top: 4px;
}

.rs-btn-primary {
  border-color: #3b82f6;
  background: #eff6ff;
  color: #1d4ed8;
}

.rs-btn-primary:disabled {
  opacity: 0.4;
  cursor: default;
}

.rs-legend {
  margin-top: 8px;
  border-top: 1px solid #e2e8f0;
  padding-top: 8px;
}

.rs-legend-title {
  font-size: 12px;
  font-weight: 600;
  color: #64748b;
  margin-bottom: 6px;
}

.rs-legend-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  margin-bottom: 5px;
}

.rs-legend-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
}

.rs-legend-name { flex: 1; }

.rs-delete {
  border: none;
  background: none;
  color: #9ca3af;
  cursor: pointer;
  font-size: 11px;
  padding: 0 2px;
}

.rs-delete:hover { color: #ef4444; }

.rs-legend-empty {
  font-size: 12px;
  color: #9ca3af;
}

.rs-hint {
  margin-top: auto;
  font-size: 11px;
  color: #94a3b8;
  line-height: 1.5;
  border-top: 1px solid #f1f5f9;
  padding-top: 8px;
}

/* Image + canvas */
.rs-canvas-wrap {
  flex: 1;
  position: relative;
  overflow: auto;
  background: #f1f5f9;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding: 8px;
}

.rs-img {
  display: block;
  max-width: 100%;
  max-height: 560px;
  object-fit: contain;
  user-select: none;
}

.rs-canvas {
  position: absolute;
  top: 8px;
  left: 50%;
  transform: translateX(-50%);
  cursor: crosshair;
  pointer-events: all;
}
</style>
