let py,assets;
const decode=s=>Uint8Array.from(atob(s),c=>c.charCodeAt(0));
const text=s=>new TextDecoder().decode(decode(s));
self.onmessage=async({data:m})=>{try{
 if(m.action==='init'){
  assets=m.assets;postMessage({progress:'正在启动文件内置计算组件…'});
  self.fetch=async url=>{const name=String(url).split('/').pop().split('?')[0];if(!assets.runtime[name])throw Error('禁止网络请求：'+name);return new Response(decode(assets.runtime[name]),{headers:{'Content-Type':name.endsWith('.wasm')?'application/wasm':'application/octet-stream'}})};
  self.importScripts=(...urls)=>{for(const u of urls){const name=u.split('/').pop();if(!assets.runtime[name])throw Error('未知运行组件');(0,eval)(text(assets.runtime[name]))}};
  (0,eval)(text(assets.runtime['pyodide.js']));py=await loadPyodide({indexURL:'https://offline.invalid/',stdout:()=>{},stderr:()=>{}});
  postMessage({progress:'正在准备PDF双通道读取与精确小数计算…'});await py.loadPackage(['cryptography']);
  py.FS.mkdirTree('/code/prices');py.FS.mkdirTree('/packages');
  for(const [name,s] of Object.entries(assets.code))py.FS.writeFile('/code/'+name,decode(s));
  for(const [name,s] of Object.entries(assets.wheels))py.FS.writeFile('/'+name,decode(s));
  await py.runPythonAsync(`import sys,zipfile,glob,json\nsys.path[:0]=['/code','/packages']\nfor p in glob.glob('/*.whl'):\n with zipfile.ZipFile(p) as z:z.extractall('/packages')\nimport bridge`);
  self.fetch=async()=>{throw Error('计算阶段禁止网络访问')};postMessage({id:m.id,ok:true,result:{ready:true}});return;
 }
 py.globals.set('request_json',JSON.stringify(m.args||{}));
 const calls={restore:'bridge.restore(json.loads(request_json))',report:'bridge.report(json.loads(request_json))',upload:'bridge.upload(**json.loads(request_json))',export:'bridge.export(json.loads(request_json))',price_import:'bridge.price_import(**json.loads(request_json))'};
 if(!calls[m.action])throw Error('未知操作');
 const result=await py.runPythonAsync('json.dumps('+calls[m.action]+',ensure_ascii=False)');postMessage({id:m.id,ok:true,result:JSON.parse(result)});
}catch(e){postMessage({id:m.id,ok:false,error:String(e)})}};
