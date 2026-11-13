// Offline RPC. No HTTP APIs or remote uploads.
const offlineAssets=JSON.parse(document.getElementById('offline-assets').textContent);
const localWorker=new Worker(URL.createObjectURL(new Blob([OFFLINE_WORKER],{type:'text/javascript'})));
let seq=0;const pending=new Map();let database,originalFiles=new Map(),localArchive=null,storageOK=true;
function rpc(action,args={},extra={}){return new Promise((resolve,reject)=>{const id=++seq;pending.set(id,{resolve,reject});localWorker.postMessage({id,action,args,...extra})})}
localWorker.onmessage=({data})=>{if(data.progress){document.getElementById('progress').textContent=data.progress;return}const p=pending.get(data.id);if(!p)return;pending.delete(data.id);data.ok?p.resolve(data.result):p.reject(Error(data.error))};
localWorker.onerror=e=>{for(const p of pending.values())p.reject(Error('本地计算线程中断：'+e.message));pending.clear()};
const idbRequest=r=>new Promise((res,rej)=>{r.onsuccess=()=>res(r.result);r.onerror=()=>rej(r.error)});
async function loadLocal(){try{const req=indexedDB.open('jx-customer-offline-v1',1);req.onupgradeneeded=()=>req.result.createObjectStore('state');database=await idbRequest(req);const saved=await idbRequest(database.transaction('state').objectStore('state').get('archive'));if(saved){localArchive=saved.archive;originalFiles=new Map(saved.originals.map(({url,...f})=>[f.hash,f]));return saved}}catch(e){storageOK=false}return null}
async function persist(){if(!database||!storageOK)return;try{await new Promise((res,rej)=>{const tx=database.transaction('state','readwrite');tx.objectStore('state').put({archive:localArchive,originals:[...originalFiles.values()].map(({url,...f})=>f)},'archive');tx.oncomplete=res;tx.onerror=()=>rej(tx.error)})}catch(e){storageOK=false;document.getElementById('progress').textContent+='\n浏览器未能保存资料，请下载本地备份，关闭前保留原文件。'}}
const localReady=(async()=>{const saved=await loadLocal();await rpc('init',{}, {assets:offlineAssets});if(saved)await rpc('restore',saved);document.getElementById('progress').textContent=storageOK?'本地计算器已就绪。文件仅在本机处理，已支持自动保留资料。':'本地计算器已就绪。当前浏览器不支持持久保存，请下载备份。';document.getElementById('files').disabled=false;return true})();
function binary(s){return Uint8Array.from(atob(s),c=>c.charCodeAt(0))}
function localOriginalUrl(hash,page){const f=originalFiles.get(hash);if(!f)return '';if(!f.url)f.url=URL.createObjectURL(new Blob([binary(f.content)],{type:f.suffix==='.pdf'?'application/pdf':'application/octet-stream'}));return f.url+(page?'#page='+page:'')}
window.fetch=async function(url,options={}){
 await localReady;const u=new URL(url,'https://offline.invalid/'),args=Object.fromEntries(u.searchParams);
 try{
  args.price_state=window.priceState||{};
  if(u.pathname==='/api/upload'){
   const body=JSON.parse(options.body);const result=await rpc('upload',body);localArchive=result.archive;
   const bytes=binary(body.content),hash=[...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(c=>c.toString(16).padStart(2,'0')).join('');
   originalFiles.set(hash,{hash,name:body.name,suffix:'.'+body.name.split('.').pop().toLowerCase(),content:body.content});await persist();return new Response(JSON.stringify(result.result),{headers:{'Content-Type':'application/json'}});
  }
  if(u.pathname==='/api/report')return new Response(JSON.stringify(await rpc('report',args)),{headers:{'Content-Type':'application/json'}});
  if(['/api/scenario.csv','/api/monthly.csv','/api/audit.json'].includes(u.pathname)){
   args.kind=u.pathname.endsWith('scenario.csv')?'csv':u.pathname.endsWith('monthly.csv')?'monthly':'json';const r=await rpc('export',args);return new Response(binary(r.content),{headers:{'Content-Type':r.type,'X-Local-Filename':encodeURIComponent(r.name)}})
  }
  throw Error('不支持的本地操作');
 }catch(e){return new Response(JSON.stringify({error:String(e.message||e)}),{status:400,headers:{'Content-Type':'application/json'}})}
};
function saveBlob(blob,name){const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=name;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),60000)}
document.addEventListener('click',async e=>{const a=e.target.closest('a');if(!a)return;const href=a.getAttribute('href')||'';if(!href.startsWith('/api/'))return;e.preventDefault();try{if(href.startsWith('/api/original')){const u=new URL(href,'https://offline.invalid'),f=originalFiles.get(u.searchParams.get('hash'));if(!f)throw Error('原件未找到');if(f.suffix==='.pdf')window.open(localOriginalUrl(f.hash)+(u.hash||''),'_blank');else saveBlob(new Blob([binary(f.content)]),f.name);return}const r=await fetch(href);if(!r.ok)throw Error((await r.json()).error);saveBlob(await r.blob(),decodeURIComponent(r.headers.get('X-Local-Filename')))}catch(err){document.getElementById('error').textContent=err.message}});
document.getElementById('backup').onclick=async()=>{await localReady;saveBlob(new Blob([JSON.stringify({format:'jx-customer-local-v1',archive:localArchive,priceLibrary:window.priceLibrary,activePrice:window.activePrice,settings:saved,selected_account:selected,originals:[...originalFiles.values()].map(({url,...f})=>f)})],{type:'application/json'}),'客户资料本地备份.json')};
document.getElementById('restore-local').onchange=async e=>{const file=e.target.files[0];if(!file)return;try{await localReady;const v=JSON.parse(await file.text());if(v.format!=='jx-customer-local-v1')throw Error('不是本工具的备份');localArchive=await rpc('restore',v);if(v.priceLibrary)restorePriceLibrary(v);if(v.settings){saved=v.settings;selected=v.selected_account||selected;paramsForAccount()}for(const {url,...f} of v.originals)originalFiles.set(f.hash,f);await persist();await refresh();document.getElementById('progress').textContent='本地备份已恢复'}catch(err){document.getElementById('error').textContent=err.message}finally{e.target.value=''}};
localReady.catch(e=>{document.getElementById('error').textContent='本地运行组件初始化失败：'+e.message+'。请用最新版Chrome或Edge打开成品HTML。'});
