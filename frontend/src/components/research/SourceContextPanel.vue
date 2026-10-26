<template>
  <details v-if="view.visible" class="source-context-panel">
    <summary>
      {{ L('新闻与市场背景', 'News & market context') }}
      <span class="context-count">{{ view.totalItems }} {{ L('条', 'items') }}</span>
      <span class="context-tag">{{ L('仅供背景参考', 'Context only') }}</span>
    </summary>
    <div class="context-body">
      <p class="context-note">{{ L(
        '这些来源仅供背景参考，不用于概率锚定或结果判定。社交观点与社区预测不等同于成交报价；报价保留来源口径和单位，不推算概率或套利信号。',
        'These sources provide context only and are ineligible for probability anchoring or resolution. Social opinions and community forecasts differ from traded quotes. Quotes retain source basis and units; no probability or arbitrage signal is inferred.'
      ) }}</p>
      <ul v-if="view.providers.length" class="context-providers" :aria-label="L('数据提供方状态', 'Provider statuses')">
        <li v-for="provider in view.providers" :key="provider.provider" class="context-provider" :data-state="provider.state">
          <strong>{{ provider.provider || L('未知提供方', 'Unknown provider') }}</strong>
          <span>{{ stateLabel(provider.state) }}</span>
          <span class="context-muted">{{ provider.attempted === true ? L('已尝试', 'Attempted')
            : provider.attempted === false ? L('未尝试', 'Not attempted') : L('尝试状态未知', 'Attempt status unknown') }}</span>
        </li>
      </ul>
      <p v-if="view.hiddenProviders" class="context-note">{{ L(`另有 ${view.hiddenProviders} 个提供方未展示。`, `${view.hiddenProviders} additional providers are not shown.`) }}</p>
      <p v-if="!view.items.length" class="context-note">{{ L('没有可展示的背景条目，请查看各提供方状态。', 'No context items to display. Check each provider’s status.') }}</p>
      <p v-else class="context-note">{{ L(`展示 ${view.items.length} / ${view.totalItems} 条背景资料`, `Showing ${view.items.length} of ${view.totalItems} context items`) }}</p>
      <ol v-if="view.items.length" class="context-items">
        <li v-for="item in view.items" :key="item.key" class="context-item">
          <div class="context-meta">
            <span class="context-tag">{{ kindLabel(item.kind) }}</span>
            <span>{{ item.provider || L('未知提供方', 'Unknown provider') }}</span>
            <span v-if="item.publisher">{{ L('发布方', 'Publisher') }}: {{ item.publisher }}</span>
            <span v-if="item.sourceRef">{{ L('原始研究来源台账编号', 'Original research ledger reference') }}: {{ item.sourceRef }}</span>
            <span v-if="item.language">{{ L('语言', 'Language') }}: {{ item.language }}</span>
          </div>
          <a v-if="item.url" class="context-title" :href="item.url" target="_blank" rel="noopener noreferrer">{{ item.title || L('查看来源', 'View source') }} ↗</a>
          <span v-else class="context-title">{{ item.title || L('未命名来源', 'Untitled source') }}</span>
          <p v-if="item.snippet" class="context-snippet">{{ item.snippet }}</p>
          <div class="context-times">
            <span>{{ L('发布时间', 'Published') }}: <time v-if="item.publishedAt" :datetime="item.publishedAt">{{ item.publishedAt }}</time><span v-else>{{ L('未知', 'Unknown') }}</span></span>
            <span>{{ L('采集时间', 'Retrieved') }}: <time v-if="item.retrievedAt" :datetime="item.retrievedAt">{{ item.retrievedAt }}</time><span v-else>{{ L('未知', 'Unknown') }}</span></span>
            <span v-if="item.kind === 'market_quote'">{{ L('报价时间', 'Quote time') }}: <time v-if="item.quoteAt" :datetime="item.quoteAt">{{ item.quoteAt }}</time><span v-else>{{ L('未知', 'Unknown') }}</span></span>
            <span v-if="item.endAt">{{ L('截止时间', 'Ends') }}: <time :datetime="item.endAt">{{ item.endAt }}</time></span>
          </div>
          <dl v-if="item.basis || item.units || item.bid || item.ask || item.last || item.forecasters || item.outcome" class="context-quote">
            <div v-if="item.basis"><dt>{{ L('报价／预测口径', 'Quote / forecast basis') }}</dt><dd>{{ item.basis }}</dd></div>
            <div v-if="item.probabilityBasis"><dt>{{ L('来源价格口径', 'Source price basis') }}</dt><dd>{{ item.probabilityBasis }}</dd></div>
            <div v-if="item.units"><dt>{{ L('单位', 'Units') }}</dt><dd>{{ item.units }}</dd></div>
            <div v-if="item.bid"><dt>{{ L('买价', 'Bid') }}</dt><dd>{{ item.bid }}</dd></div>
            <div v-if="item.ask"><dt>{{ L('卖价', 'Ask') }}</dt><dd>{{ item.ask }}</dd></div>
            <div v-if="item.last"><dt>{{ L('最近报价', 'Last quote') }}</dt><dd>{{ item.last }}</dd></div>
            <div v-if="item.outcome"><dt>{{ L('结果选项', 'Outcome') }}</dt><dd>{{ item.outcome }}</dd></div>
            <div v-if="item.forecasters"><dt>{{ L('预测人数', 'Forecasters') }}</dt><dd>{{ item.forecasters }}</dd></div>
          </dl>
          <details v-if="item.rulesPrimary || item.rulesSecondary || item.strikeType || item.floorStrike || item.capStrike" class="context-rules">
            <summary>{{ L('结算规则与阈值', 'Settlement rules and thresholds') }}</summary>
            <p v-if="item.strikeType">{{ L('比较方式', 'Strike type') }}: {{ item.strikeType }}</p>
            <p v-if="item.floorStrike">{{ L('下限', 'Lower threshold') }}: {{ item.floorStrike }}</p>
            <p v-if="item.capStrike">{{ L('上限', 'Upper threshold') }}: {{ item.capStrike }}</p>
            <p v-if="item.rulesPrimary"><strong>{{ L('主要规则', 'Primary rule') }}:</strong> {{ item.rulesPrimary }}</p>
            <p v-if="item.rulesSecondary"><strong>{{ L('补充规则', 'Secondary rule') }}:</strong> {{ item.rulesSecondary }}</p>
          </details>
        </li>
      </ol>
    </div>
  </details>
</template>

<script setup>
import { computed } from 'vue'
import { L as appL } from '../../i18n'
import { sourceContextView } from '../../utils/sourceContext'

const props = defineProps({ context: { type: Object, default: null }, lang: { type: String, default: '' } })
function L(zh, en) { return props.lang === 'zh' ? zh : props.lang === 'en' ? (en ?? zh) : appL(zh, en) }
const view = computed(() => sourceContextView(props.context))
const states = {
  ok: ['可用', 'Available'], verified_empty: ['已核实无结果', 'Verified empty'],
  disabled: ['已禁用', 'Disabled'], unavailable: ['不可用', 'Unavailable'],
  forbidden: ['访问被拒绝', 'Access denied'], rate_limited: ['请求受限', 'Rate limited'],
  timeout: ['超时', 'Timed out'], budget_exhausted: ['预算已耗尽', 'Budget exhausted'],
  partial: ['部分结果', 'Partial results'], unsupported: ['不支持', 'Unsupported'],
}
const kinds = {
  news_snippet: ['新闻摘要', 'News snippet'], social_post: ['社交观点', 'Social opinion'],
  market_quote: ['交易市场报价', 'Traded market quote'], community_forecast: ['社区预测', 'Community forecast'],
}
const stateLabel = state => L(...states[state])
const kindLabel = kind => L(...kinds[kind])
</script>

<style scoped>
.source-context-panel {
  margin: 16px 0;
  border: 1px solid var(--border, #e5e5e5);
  border-radius: var(--radius, 2px);
  background: var(--paper, #fff);
  color: var(--ink, #000);
  font-size: 13px;
  line-height: 1.6;
  overflow-wrap: anywhere;
}
summary { padding: 12px 16px; cursor: pointer; font-weight: 600; }
summary::marker { color: var(--orange, #ff4500); }
summary:focus-visible, .context-title:focus-visible { outline: 2px solid var(--orange, #ff4500); outline-offset: 3px; }
.context-count { margin: 0 10px; color: var(--muted, #666); font-family: var(--mono, monospace); font-size: 11px; }
.context-body { padding: 0 16px 16px; }
.context-note { margin: 0 0 12px; color: var(--muted, #666); font-size: 12px; }
.context-providers, .context-items { list-style: none; margin: 0 0 12px; padding: 0; }
.context-provider, .context-meta, .context-times { display: flex; flex-wrap: wrap; gap: 4px 12px; }
.context-provider { padding: 5px 0; }
.context-muted, .context-times { color: var(--muted, #666); font-size: 11px; }
.context-item { padding: 14px 0; border-top: 1px solid var(--border, #e5e5e5); min-width: 0; }
.context-meta { margin-bottom: 6px; font-size: 11px; color: var(--muted, #666); }
.context-tag { display: inline-block; padding: 0 6px; border: 1px solid var(--border, #e5e5e5); font-family: var(--mono, monospace); font-size: 10px; font-weight: 400; }
.context-title { font-weight: 600; color: var(--ink, #000); text-decoration: none; }
a.context-title:hover { color: var(--orange, #ff4500); text-decoration: underline; }
.context-snippet { margin: 8px 0; white-space: pre-wrap; }
.context-quote { display: flex; flex-wrap: wrap; gap: 6px 20px; margin: 8px 0 0; font-size: 12px; }
.context-quote div { min-width: 0; }
.context-quote dt { color: var(--muted, #666); }
.context-quote dd { margin: 0; font-family: var(--mono, monospace); overflow-wrap: anywhere; }
.context-rules { margin-top: 10px; font-size: 12px; }
.context-rules summary { padding: 6px 0; }
.context-rules p { white-space: pre-wrap; overflow-wrap: anywhere; }
@media (max-width: 600px) {
  summary { padding: 10px 12px; }
  .context-body { padding: 0 12px 12px; }
  .context-times { flex-direction: column; }
}
</style>
