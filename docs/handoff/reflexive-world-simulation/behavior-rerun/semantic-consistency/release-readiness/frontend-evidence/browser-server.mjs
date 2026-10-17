import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
const root=path.dirname(new URL(import.meta.url).pathname);
const fixtures=JSON.parse(fs.readFileSync(path.join(root,'preflight-fixtures.json'))).responses;
const send=(res,status,body)=>{res.writeHead(status,{'Content-Type':'application/json'});res.end(JSON.stringify(body));};
const types={'.html':'text/html','.js':'text/javascript','.css':'text/css','.woff2':'font/woff2','.svg':'image/svg+xml','.png':'image/png'};
const server=http.createServer(async(req,res)=>{
 const url=new URL(req.url,'http://127.0.0.1');
 if(url.pathname.startsWith('/api/')){
  let raw='';for await(const chunk of req)raw+=chunk;
  fs.appendFileSync(path.join(root,'browser-requests.jsonl'),JSON.stringify({method:req.method,path:url.pathname,query:Object.fromEntries(url.searchParams),body:raw?JSON.parse(raw):null})+'\n');
  if(url.pathname==='/api/research/preflight'){
   const mode=JSON.parse(fs.readFileSync(path.join(root,'scenario.json'))).scenario;
   if(mode==='http_failure')return send(res,503,{success:false,error:'Fixture readiness temporarily unavailable'});
   const name=url.searchParams.get('simulation_engine')==='oasis-legacy'?'explicit_legacy':mode;
   return send(res,fixtures[name].status,fixtures[name].body);
  }
  if(url.pathname==='/api/research/run')return send(res,409,{success:false,error:'Browser acceptance captured request; no pipeline was started.'});
  return send(res,404,{success:false,error:'No live backend in isolated browser acceptance.'});
 }
 const file=path.resolve(root,'frontend/dist','.'+decodeURIComponent(url.pathname));
 if(!file.startsWith(path.join(root,'frontend/dist')+path.sep)&&file!==path.join(root,'frontend/dist'))return send(res,403,{});
 const actual=fs.existsSync(file)&&fs.statSync(file).isFile()?file:path.join(root,'frontend/dist/index.html');
 res.writeHead(200,{'Content-Type':types[path.extname(actual)]||'application/octet-stream'});fs.createReadStream(actual).pipe(res);
});
server.listen(0,'127.0.0.1',()=>{const port=server.address().port;fs.writeFileSync(path.join(root,'browser-server.json'),JSON.stringify({port,pid:process.pid}));console.log('Isolated browser acceptance http://127.0.0.1:'+port);});
