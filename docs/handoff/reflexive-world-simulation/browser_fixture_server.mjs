// Isolated browser acceptance: production components + frozen real API responses.
// No application backend, provider or saved user run is started by this server.
import fs from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'

const [fixturePath, dependencies] = process.argv.slice(2)
if (!fixturePath || !dependencies) throw new Error('Pass browser-api-fixture.json and existing frontend/node_modules')
const repository = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..')
const fixture = JSON.parse(await fs.readFile(fixturePath, 'utf8'))
const root = await fs.realpath(await fs.mkdtemp(path.join(os.tmpdir(), 'world-browser-')))
await fs.cp(path.join(repository, 'frontend/src'), path.join(root, 'src'), { recursive: true })
await fs.symlink(path.resolve(dependencies), path.join(root, 'node_modules'))
await fs.writeFile(path.join(root, 'package.json'), '{"type":"module"}')
await fs.writeFile(path.join(root, 'index.html'), '<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>World simulation acceptance</title></head><body style="margin:0;background:#f8f9fa"><div id="app"></div><script type="module" src="/test-main.js"></script></body></html>')
await fs.writeFile(path.join(root, 'test-main.js'), `import { createApp,ref,h } from 'vue';
import SimulationView from './src/components/research/SimulationView.vue';
import {locale,setLocale} from './src/i18n.js';
createApp({setup(){const legacy=ref(false);return()=>h('main',{style:'max-width:1200px;margin:auto;padding:20px'},[
h('h1','Synthetic world · browser acceptance'),h('p','Frozen responses from the real compiler, controller and Flask API. No live model calls.'),
h('button',{onClick:()=>setLocale(locale.value==='en'?'zh':'en')},'EN / 中文'),
h('button',{onClick:()=>legacy.value=!legacy.value},legacy.value?'Show world run':'Show legacy run'),
h(SimulationView,{simulationId:legacy.value?'sim_legacy':${JSON.stringify(fixture.simulationId)}})])}}).mount('#app');`)
const { createServer } = await import(pathToFileURL(path.join(dependencies, 'vite/dist/node/index.js')))
const { default: vue } = await import(pathToFileURL(path.join(dependencies, '@vitejs/plugin-vue/dist/index.mjs')))
const requests = []
const api = { name: 'frozen-world-api', configureServer(server) { server.middlewares.use((req, res, next) => {
  if (!req.url.startsWith('/api/')) return next()
  const url = new URL(req.url, 'http://127.0.0.1:4179')
  requests.push({method:req.method,url:url.pathname,query:Object.fromEntries(url.searchParams)})
  let payload
  if (url.pathname === '/api/simulation/' + fixture.simulationId) payload = fixture.state
  else if (url.pathname.endsWith('/world')) {
    const view = url.searchParams.get('view') || 'public', actor = view === 'actor' ? url.searchParams.get('actor_id') || '' : ''
    const round = url.searchParams.get('round') ?? '4'
    payload = fixture.responses[view + ':' + actor + ':' + round]
  } else if (url.pathname === '/api/simulation/sim_legacy') payload = {success:true,data:{simulation_id:'sim_legacy',status:'completed'}}
  else if (url.pathname.includes('/sim_legacy/')) payload = {success:true,data:{profiles:[],posts:[],comments:[],agents:[],current_round:4,total_rounds:4,runner_status:'completed'}}
  res.statusCode = payload ? 200 : 404
  res.setHeader('Content-Type','application/json')
  res.end(JSON.stringify(payload || {success:false,error:'Fixture response unavailable'}))
})} }
const server = await createServer({root,cacheDir:path.join(root,'.vite'),configFile:false,plugins:[vue(),api],
  server:{host:'127.0.0.1',port:4179,strictPort:true,fs:{allow:[root,path.resolve(dependencies)]}}})
await server.listen()
console.log(JSON.stringify({url:'http://127.0.0.1:4179/',root,simulationId:fixture.simulationId}))
process.on('SIGINT',async()=>{await fs.writeFile(path.join(root,'requests.json'),JSON.stringify(requests,null,2));await server.close();process.exit(0)})
