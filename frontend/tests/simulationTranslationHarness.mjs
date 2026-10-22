// Load the actual module with only transport injected. Vue reactivity is real;
// no live API client, backend or provider is imported.
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { babelParse } from '@vue/compiler-sfc'
import * as vue from 'vue'

export function loadOverlay(api = {}) {
  let code = readFileSync(new URL('../src/utils/overlayTranslation.js', import.meta.url), 'utf8')
  const ast = babelParse(code, { sourceType: 'module' }).program.body
  const exports = ast.filter(node => node.type === 'ExportNamedDeclaration').map(node => node.declaration.id?.name || node.declaration.declarations[0].id.name)
  for (const node of ast.filter(node => node.type === 'ImportDeclaration').reverse()) {
    const bindings = node.specifiers.map(spec => {
      assert.equal(spec.type, 'ImportSpecifier')
      return `const ${spec.local.name} = imports[${JSON.stringify(node.source.value)}][${JSON.stringify(spec.imported.name)}];`
    }).join('\n')
    code = code.slice(0, node.start) + bindings + code.slice(node.end)
  }
  code = code.replace(/^export /gm, '')
  const missing = () => { throw new Error('No translation transport supplied by this test') }
  return new Function('imports', `${code}\nreturn {${exports.join(',')}}`)( {
    vue,
    '../api/translations': { getGraphTranslation: missing, startGraphTranslation: missing,
      getSimulationTranslation: missing, startSimulationTranslation: missing, ...api },
  })
}
export const overlay = loadOverlay()
