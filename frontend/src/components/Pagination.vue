<script setup lang="ts">
defineProps<{ page: number; pages: number; busy?: boolean; label?: string }>()
defineEmits<{ change: [page: number] }>()
</script>
<template><div class="pager" :aria-label="label || '分页'"><button type="button" :disabled="busy || page <= 1" @click="$emit('change', page - 1)">上一页</button><span>{{ page }} / {{ Math.max(1, pages) }}</span><button type="button" :disabled="busy || page >= pages" @click="$emit('change', page + 1)">下一页</button></div></template>
