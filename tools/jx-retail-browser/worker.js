let py,assets;
const decode=s=>Uint8Array.from(atob(s),c=>c.charCodeAt(0));
const text=s=>new TextDecoder().decode(decode(s));
onmessage=async ({data:m})=>{
 try{
  if(m.action==='init'){
   postMessage({progress:'正在读取文件内置的运行组件…'});
   assets=m.assets;
   self.fetch=async url=>{const name=String(url).split('/').pop();if(!assets.runtime[name])throw Error('禁止网络请求：'+name);return new Response(decode(assets.runtime[name]),{headers:{'Content-Type':name.endsWith('.wasm')?'application/wasm':'application/octet-stream'}})};
   self.importScripts=(...urls)=>{for(const url of urls){const name=url.split('/').pop();if(!assets.runtime[name])throw Error('未知运行文件');(0,eval)(text(assets.runtime[name]))}};
   (0,eval)(text(assets.runtime['pyodide.js']));
   py=await loadPyodide({indexURL:'https://offline.invalid/',stdout:()=>{},stderr:()=>{}});
   postMessage({progress:'正在准备Excel解析与精确计算模块…'});
   py.FS.mkdirTree('/code');py.FS.mkdirTree('/packages');py.FS.mkdirTree('/inputs');
   for(const [name,s] of Object.entries(assets.python))py.FS.writeFile('/code/'+name,decode(s));
   for(const [name,s] of Object.entries(assets.wheels))py.FS.writeFile('/'+name,decode(s));
   await py.runPythonAsync(`import sys,zipfile,glob\nsys.path[:0]=['/code','/packages']\nfor p in glob.glob('/*.whl'):\n with zipfile.ZipFile(p) as z:z.extractall('/packages')\nimport browser_bridge,json`);
   self.fetch=async()=>{throw Error('计算阶段禁止网络访问')};
   postMessage({id:m.id,ok:true,result:{ready:true}});return;
  }
  py.globals.set('request_json',JSON.stringify(m.args||{}));
  let result;
  if(m.action==='files'){
   let paths=[];for(const f of m.files){const path='/inputs/'+crypto.randomUUID()+f.name.slice(f.name.lastIndexOf('.')).toLowerCase();py.FS.writeFile(path,new Uint8Array(f.bytes));paths.push([path,f.name])}
   py.globals.set('request_json',JSON.stringify(paths));
   result=await py.runPythonAsync('json.dumps(browser_bridge.inspect_files(json.loads(request_json)),ensure_ascii=False)');
  }else{
   const calls={choose:'browser_bridge.choose(**json.loads(request_json))',calculate:'browser_bridge.calculate()',decide:'browser_bridge.decide(**json.loads(request_json))',reset:'browser_bridge.reset()'};
   if(!calls[m.action])throw Error('未知操作');
   result=await py.runPythonAsync('json.dumps('+calls[m.action]+',ensure_ascii=False)');
  }
  const response={id:m.id,ok:true,result:JSON.parse(result)};
  if(m.action==='calculate'){response.bytes=py.FS.readFile('/result.xlsx').buffer;response.report=JSON.parse(py.runPython('json.dumps(browser_bridge.LAST,ensure_ascii=False)'))}
  postMessage(response);
 }catch(e){postMessage({id:m.id,ok:false,error:String(e)})}
};
