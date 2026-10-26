import { build } from 'vite'
import vue from '@vitejs/plugin-vue'
import { createHash } from 'node:crypto'
import { mkdir, readdir, readFile, writeFile, realpath } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const root = path.dirname(fileURLToPath(import.meta.url))
const frontend = path.resolve(root, '../..')
const repository = path.dirname(frontend)
const arg = name => { const i = process.argv.indexOf(name); return i < 0 ? undefined : process.argv[i + 1] }
const requested = arg('--out-dir') || process.env.DRF_BROWSER_WWW
if (!requested) throw new Error('Usage: node frontend/tests/browser/build.mjs --out-dir /private/tmp/<disposable>/www')
const outDir = path.resolve(requested)
await mkdir(outDir, { recursive: true })
const resolved = await realpath(outDir)
if (resolved === repository || resolved.startsWith(repository + path.sep)) throw new Error('Build output must be outside the repository')
if ((await readdir(outDir)).length) throw new Error('Build output must be an empty disposable directory; nothing will be deleted')
const sha256 = bytes => createHash('sha256').update(bytes).digest('hex')
async function inventory(directory, base = repository) {
  const rows = []
  for (const entry of (await readdir(directory, { withFileTypes: true })).sort((a, b) => a.name.localeCompare(b.name))) {
    const filename = path.join(directory, entry.name)
    if (entry.isDirectory()) rows.push(...await inventory(filename, base))
    else if (entry.isFile()) rows.push({ path: path.relative(base, filename), sha256: sha256(await readFile(filename)) })
  }
  return rows
}
const sourcesBefore = [...await inventory(path.join(frontend, 'src')), ...await inventory(root)]
await build({ root, configFile: false, envDir: false, plugins: [vue()], base: '/',
  define: { 'import.meta.env.VITE_API_BASE_URL': JSON.stringify('') },
  build: { outDir, emptyOutDir: false, sourcemap: true, target: 'chrome120', manifest: true },
})
const sourcesAfter = [...await inventory(path.join(frontend, 'src')), ...await inventory(root)]
if (JSON.stringify(sourcesBefore) !== JSON.stringify(sourcesAfter)) throw new Error('Source files changed during build; rebuild before using this artifact')
const receipt = { schema: 'translation-browser-build/v1', built_at: new Date().toISOString(), out_dir: resolved,
  api_origin: 'same-origin', fixture_origin: 'http://127.0.0.1:18761', sources: sourcesAfter,
  outputs: await inventory(outDir, outDir), semantic_limit: 'Controlled CJK stand-in, not provider or translation-quality acceptance' }
await writeFile(path.join(outDir, 'build-receipt.json'), JSON.stringify(receipt, null, 2) + '\n', { flag: 'wx' })
process.stdout.write(JSON.stringify({ outDir: resolved, sourceFiles: receipt.sources.length, outputs: receipt.outputs.length }) + '\n')
