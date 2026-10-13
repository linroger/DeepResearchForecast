// Compile a real .vue SFC for node tests: the script setup and template are compiled
// with @vue/compiler-sfc exactly as the Vite plugin does, and every import is replaced
// by a module the test injects (API clients, utils, child components). No browser,
// backend or network is involved; components render through Vue's server renderer.
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { babelParse, compileScript, compileTemplate, parse } from '@vue/compiler-sfc'

function injectImports(code) {
  const imports = babelParse(code, { sourceType: 'module' }).program.body
    .filter(node => node.type === 'ImportDeclaration')
  let out = code
  for (const node of imports.reverse()) {
    const source = JSON.stringify(node.source.value)
    const bindings = node.specifiers.map(specifier => {
      if (specifier.type === 'ImportDefaultSpecifier') {
        return `const ${specifier.local.name} = imports[${source}].default;`
      }
      assert.equal(specifier.type, 'ImportSpecifier')
      return `const ${specifier.local.name} = imports[${source}][${JSON.stringify(specifier.imported.name)}];`
    }).join('\n')
    out = out.slice(0, node.start) + bindings + out.slice(node.end)
  }
  return out
}

/**
 * Returns `build(imports)` → the component options object (setup + render).
 * `imports` maps each import specifier used by the SFC to its module object.
 */
export function compileSfc(url) {
  const filename = url.pathname
  const { descriptor } = parse(readFileSync(url, 'utf8'), { filename })
  const id = 'test-' + filename.split('/').pop().replace(/\W/g, '-')
  const script = compileScript(descriptor, { id, genDefaultAs: '__component' })
  const template = compileTemplate({
    source: descriptor.template.content,
    filename,
    id,
    compilerOptions: { bindingMetadata: script.bindings },
  })
  assert.deepEqual(template.errors, [])
  const scriptFactory = new Function('imports', `${injectImports(script.content)}\nreturn __component;`)
  const renderFactory = new Function('imports',
    `${injectImports(template.code).replace(/^export function render/m, 'function render')}\nreturn render;`)
  return imports => {
    const component = scriptFactory(imports)
    component.render = renderFactory(imports)
    return component
  }
}
