import { createApp } from 'vue'
import '@fontsource/inter/400.css'
import '@fontsource/noto-sans-sc/400.css'
import '@fontsource/jetbrains-mono/400.css'
import '../../src/styles/tokens.css'
import { locale } from '../../src/i18n.js'
import BrowserHarness from './BrowserHarness.vue'

// A new browser profile starts in the source-language UI. This is the real app
// locale; the harness never replaces a component, composable, or API module.
locale.value = 'en'
createApp(BrowserHarness).mount('#app')
