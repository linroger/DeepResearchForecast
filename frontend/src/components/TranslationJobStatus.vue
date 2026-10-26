<template>
  <div v-if="observer.status.value !== 'source' || observer.loading.value" class="translation-job-status" role="status" aria-live="polite">
    <slot>
    <template v-if="showSummary">
    <span v-if="observer.status.value === 'reconnecting'">{{ L('连接中断，正在重新查询已保存的翻译。', 'Reconnecting to the saved translation.') }}</span>
    <span v-else-if="observer.busy.value">{{ L('翻译处理中，未完成的内容保留原文。', 'Translation is in progress; pending content shows the source.') }}</span>
    <span v-else-if="observer.coverage.value.pending || observer.snapshot.value?.partial">{{ L('部分内容尚未翻译。', 'Some content remains untranslated.') }}</span>
    </template>
    </slot>
    <span v-if="showSummary && observer.coverage.value.total"> {{ observer.coverage.value.accepted }} / {{ observer.coverage.value.total }} · {{ observer.coverage.value.pending }} {{ L('待完成', 'pending') }}</span>
    <span v-if="showSummary && observer.snapshot.value?.refreshPending"> {{ observer.snapshot.value.refreshPending }} {{ L('待更新', 'pending refresh') }}</span>
    <span v-if="showIssues && observer.error.value"> {{ observer.error.value }}</span>
    <button v-if="showActions && (observer.actions.value.retry || observer.actions.value.start)" type="button" :disabled="observer.busy.value" @click="observer.retry()">{{ L('重试翻译', 'Retry translation') }}</button>
    <details v-if="showIssues && observer.issues.value.length"><summary>{{ L('翻译详情', 'Translation details') }}</summary><ul><li v-for="issue in observer.issues.value" :key="issue">{{ issue }}</li></ul></details>
  </div>
</template>
<script setup>
defineProps({ observer: { type: Object, required: true }, L: { type: Function, default: (_zh, en) => en },
  showSummary: { type: Boolean, default: true }, showActions: { type: Boolean, default: true },
  showIssues: { type: Boolean, default: true } })
</script>
<style scoped>
.translation-job-status { padding: 8px 12px; background: #fff7ed; color: #7c2d12; font-size: 12px; }
button { margin-inline-start: 10px; }
</style>
