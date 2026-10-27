import { createApp, h, ref, watch } from 'vue'
import DossierViewer from '../../src/components/research/DossierViewer.vue'
import ForecastReport from '../../src/components/research/ForecastReport.vue'
import { getDossier } from '../../src/api/research.js'
import { locale } from '../../src/i18n.js'
import '../../src/styles/tokens.css'

const fixtures = ['pipe_pdf_en', 'pipe_pdf_zh', 'report_pdf_en', 'report_pdf_zh']
const requested = new URLSearchParams(location.search).get('fixture')

// Only mounting controls live here. Report bodies come from the fixture server,
// and all export controls, API calls, polling and downloading are production code.
createApp({
  setup() {
    const fixture = ref(fixtures.includes(requested) ? requested : fixtures[0])
    const dossier = ref(null)
    const visible = ref(true)
    const loading = ref(false)
    const error = ref('')
    let readVersion = 0
    watch(fixture, async id => {
      const version = ++readVersion
      visible.value = true
      dossier.value = null
      error.value = ''
      loading.value = id.startsWith('pipe_')
      locale.value = id.endsWith('_zh') ? 'zh' : 'en'
      if (!loading.value) return
      try {
        const response = await getDossier(id)
        if (version === readVersion) dossier.value = response.data
      } catch (failure) {
        if (version === readVersion) error.value = failure.message
      } finally {
        if (version === readVersion) loading.value = false
      }
    }, { immediate: true, flush: 'sync' })
    return () => h('main', [
      h('nav', { class: 'harness-controls', 'aria-label': 'Fixture controls' }, [
        h('label', [ 'Fixture ', h('select', {
          'data-testid': 'fixture', value: fixture.value,
          onChange: event => { fixture.value = event.target.value },
        }, fixtures.map(id => h('option', { value: id }, id))) ]),
        h('button', { 'data-testid': 'toggle-mount', onClick: () => { visible.value = !visible.value } }, visible.value ? 'Unmount report' : 'Mount report'),
        h('span', { 'data-testid': 'selected-resource' }, fixture.value),
      ]),
      error.value ? h('p', { class: 'harness-error', role: 'alert' }, error.value) : null,
      h('section', { id: 'subject', 'data-testid': 'subject' }, visible.value
        ? (fixture.value.startsWith('pipe_')
          ? h(DossierViewer, { pipelineId: fixture.value, dossier: dossier.value, editable: false, artifactNames: [] })
          : h(ForecastReport, { reportId: fixture.value })) : null),
      loading.value ? h('span', { 'data-testid': 'loading' }, 'Loading fixture…') : null,
    ])
  },
}).mount('#app')
