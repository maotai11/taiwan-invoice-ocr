<script setup lang="ts">
defineProps<{
  score: number;       // 0.0 – 1.0
  label?: string;
  showPct?: boolean;
}>();

function barColor(s: number): string {
  if (s >= 0.8) return "#22c55e";
  if (s >= 0.5) return "#f59e0b";
  return "#ef4444";
}
</script>

<template>
  <div class="cb-wrap" :title="`信心值 ${Math.round(score * 100)}%`">
    <span v-if="label" class="cb-label">{{ label }}</span>
    <div class="cb-track">
      <div
        class="cb-fill"
        :style="{
          width: Math.round(score * 100) + '%',
          background: barColor(score),
        }"
      ></div>
    </div>
    <span v-if="showPct !== false" class="cb-pct">{{ Math.round(score * 100) }}%</span>
  </div>
</template>

<style scoped>
.cb-wrap {
  display: flex;
  align-items: center;
  gap: 5px;
  min-width: 80px;
}
.cb-label {
  font-size: 11px;
  color: #6b7280;
  white-space: nowrap;
  width: 52px;
  flex-shrink: 0;
}
.cb-track {
  flex: 1;
  height: 6px;
  background: #e5e7eb;
  border-radius: 3px;
  overflow: hidden;
  min-width: 40px;
}
.cb-fill {
  height: 100%;
  border-radius: 3px;
  transition: width 0.3s ease;
}
.cb-pct {
  font-size: 11px;
  color: #6b7280;
  width: 28px;
  text-align: right;
  flex-shrink: 0;
}
</style>
