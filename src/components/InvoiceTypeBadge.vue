<script setup lang="ts">
defineProps<{
  invoiceType: string;
}>();

const TYPE_STYLES: Record<string, { bg: string; color: string; border: string }> = {
  三聯式: { bg: "#dbeafe", color: "#1d4ed8", border: "#93c5fd" },
  二聯式: { bg: "#e0e7ff", color: "#4338ca", border: "#a5b4fc" },
  電子發票: { bg: "#dcfce7", color: "#15803d", border: "#86efac" },
  收銀機:   { bg: "#ffedd5", color: "#c2410c", border: "#fdba74" },
  特種:     { bg: "#fef9c3", color: "#854d0e", border: "#fde047" },
  手開:     { bg: "#f3e8ff", color: "#7e22ce", border: "#d8b4fe" },
};

function style(t: string) {
  return TYPE_STYLES[t] ?? { bg: "#f1f5f9", color: "#475569", border: "#cbd5e1" };
}
</script>

<template>
  <span
    class="badge"
    :style="{
      background: style(invoiceType).bg,
      color: style(invoiceType).color,
      borderColor: style(invoiceType).border,
    }"
  >{{ invoiceType || "未知" }}</span>
</template>

<style scoped>
.badge {
  display: inline-block;
  font-size: 11px;
  font-weight: 600;
  padding: 2px 7px;
  border-radius: 999px;
  border: 1px solid;
  white-space: nowrap;
  line-height: 1.5;
}
</style>
