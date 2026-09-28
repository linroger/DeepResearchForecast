import assert from 'node:assert/strict'
import { mkdtempSync, readFileSync, rmSync } from 'node:fs'
import http from 'node:http'
import net from 'node:net'
import { networkInterfaces, tmpdir } from 'node:os'
import { join } from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { createServer as createViteServer } from 'vite'

// The /api proxy reaches Flask over loopback, which the backend trusts without a
// token, so the dev server must not listen on every interface by default. It must
// still answer on both loopback spellings people type: http://localhost:3000 and
// http://127.0.0.1:3000.

const pkg = JSON.parse(readFileSync(new URL('../package.json', import.meta.url), 'utf8'))
const frontendDir = fileURLToPath(new URL('..', import.meta.url))
const configFile = fileURLToPath(new URL('../vite.config.js', import.meta.url))

async function withFrontendHost(host, fn) {
  const prev = process.env.FRONTEND_HOST
  if (host === undefined) delete process.env.FRONTEND_HOST
  else process.env.FRONTEND_HOST = host
  try {
    return await fn()
  } finally {
    if (prev === undefined) delete process.env.FRONTEND_HOST
    else process.env.FRONTEND_HOST = prev
  }
}

function loadConfig(host) {
  return withFrontendHost(host, async () => {
    const mod = await import(`../vite.config.js?host=${encodeURIComponent(host ?? '')}`)
    return mod.default
  })
}

// GET through a fresh connection. autoSelectFamily tries every address a name
// resolves to, as browsers and curl do, so 'localhost' may land on ::1 or 127.0.0.1.
function httpGet(host, port, path) {
  return new Promise((resolve, reject) => {
    const req = http.get({ host, port, path, agent: false, autoSelectFamily: true, timeout: 5000 }, (res) => {
      res.resume()
      res.on('end', () => resolve(res.statusCode))
    })
    req.on('timeout', () => req.destroy(new Error(`timed out requesting http://${host}:${port}${path}`)))
    req.on('error', reject)
  })
}

function canConnect(host, port) {
  return new Promise((resolve) => {
    const socket = net.connect({ host, port, timeout: 2000 })
    socket.once('connect', () => {
      socket.destroy()
      resolve(true)
    })
    socket.once('timeout', () => {
      socket.destroy()
      resolve(false)
    })
    socket.once('error', () => resolve(false))
  })
}

// Vite treats port 0 as "use the default 5173", so reserve a concrete free port.
function freeLoopbackPort() {
  return new Promise((resolve, reject) => {
    const probe = net.createServer()
    probe.once('error', reject)
    probe.listen(0, '127.0.0.1', () => {
      const { port } = probe.address()
      probe.close(() => resolve(port))
    })
  })
}

function externalIPv4Addresses() {
  return Object.values(networkInterfaces())
    .flat()
    .filter((iface) => iface && iface.family === 'IPv4' && !iface.internal)
    .map((iface) => iface.address)
}

test('npm scripts do not expose the dev server to the network', () => {
  for (const name of ['dev', 'preview']) {
    assert.doesNotMatch(pkg.scripts[name] || '', /--host\b/, `${name} script must not pass --host`)
  }
})

test('dev server binds to IPv4 loopback unless FRONTEND_HOST opts in', async () => {
  // Not 'localhost': Node may resolve it to ::1 only, which refuses 127.0.0.1.
  assert.equal((await loadConfig(undefined)).server.host, '127.0.0.1')
  assert.equal((await loadConfig('0.0.0.0')).server.host, '0.0.0.0')
})

test('api proxy forwards the client address to the backend auth gate', async () => {
  const proxy = (await loadConfig(undefined)).server.proxy['/api']
  assert.equal(proxy.xfwd, true)
})

test('running dev server answers on localhost and 127.0.0.1 and on no other interface', async () => {
  // Stub backend on loopback that records what the /api proxy forwards.
  const forwardedFor = []
  const backend = http.createServer((req, res) => {
    forwardedFor.push(req.headers['x-forwarded-for'])
    res.end('ok')
  })
  await new Promise((resolve) => backend.listen(0, '127.0.0.1', resolve))
  const cacheDir = mkdtempSync(join(tmpdir(), 'drf-vite-cache-'))
  const devPort = await freeLoopbackPort()
  let server
  try {
    // Vite loads vite.config.js itself, as `npm run dev` does; only the port, the
    // browser auto-open, the dep cache and the proxy target are overridden.
    server = await withFrontendHost(undefined, () => createViteServer({
      configFile,
      root: frontendDir,
      cacheDir,
      logLevel: 'silent',
      optimizeDeps: { noDiscovery: true },
      server: {
        port: devPort,
        open: false,
        proxy: { '/api': { target: `http://127.0.0.1:${backend.address().port}` } }
      }
    }))
    await server.listen()
    const { address, port } = server.httpServer.address()
    assert.equal(port, devPort)

    assert.equal(await httpGet('127.0.0.1', port, '/'), 200)
    assert.equal(await httpGet('localhost', port, '/'), 200)
    assert.equal(address, '127.0.0.1', 'dev server must listen on IPv4 loopback only')

    // The proxy keeps xfwd, and a local browser reaches Flask as a loopback client.
    assert.equal(await httpGet('127.0.0.1', port, '/api/ping'), 200)
    assert.equal(await httpGet('localhost', port, '/api/ping'), 200)
    assert.deepEqual(forwardedFor, ['127.0.0.1', '127.0.0.1'])

    for (const lanAddress of externalIPv4Addresses()) {
      assert.equal(await canConnect(lanAddress, port), false, `dev server must not accept connections on ${lanAddress}`)
    }
  } finally {
    await server?.close()
    backend.closeAllConnections()
    await new Promise((resolve) => backend.close(resolve))
    rmSync(cacheDir, { recursive: true, force: true })
  }
})
