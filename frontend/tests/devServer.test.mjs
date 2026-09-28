import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

// The /api proxy reaches Flask over loopback, which the backend trusts without a
// token, so the dev server must not listen on every interface by default.

const pkg = JSON.parse(readFileSync(new URL('../package.json', import.meta.url), 'utf8'))

async function loadConfig(host) {
  const prev = process.env.FRONTEND_HOST
  if (host === undefined) delete process.env.FRONTEND_HOST
  else process.env.FRONTEND_HOST = host
  try {
    const mod = await import(`../vite.config.js?host=${encodeURIComponent(host ?? '')}`)
    return mod.default
  } finally {
    if (prev === undefined) delete process.env.FRONTEND_HOST
    else process.env.FRONTEND_HOST = prev
  }
}

test('npm scripts do not expose the dev server to the network', () => {
  for (const name of ['dev', 'preview']) {
    assert.doesNotMatch(pkg.scripts[name] || '', /--host\b/, `${name} script must not pass --host`)
  }
})

test('dev server binds to loopback unless FRONTEND_HOST opts in', async () => {
  assert.equal((await loadConfig(undefined)).server.host, 'localhost')
  assert.equal((await loadConfig('0.0.0.0')).server.host, '0.0.0.0')
})

test('api proxy forwards the client address to the backend auth gate', async () => {
  const proxy = (await loadConfig(undefined)).server.proxy['/api']
  assert.equal(proxy.xfwd, true)
})
