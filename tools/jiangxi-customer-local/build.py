import base64,hashlib,json,shutil
from pathlib import Path
R=Path(__file__).resolve().parent;src=R/'source'
enc=lambda p:base64.b64encode(p.read_bytes()).decode()
shutil.copy2(R/'bridge.py',R/'python/bridge.py')
expected=json.loads((R/'dependencies.lock.json').read_text())
for relative,info in expected.items():
 p=R/relative
 if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=info['sha256']:
  raise SystemExit('Dependency missing or changed: '+relative+'; run python fetch_assets.py')
assets={'runtime':{p.name:enc(p) for p in (R/'runtime').iterdir() if p.is_file()},'wheels':{p.name:enc(p) for p in (R/'wheels').glob('*.whl')},'code':{p.name:enc(p) for p in (R/'python').glob('*.py')}}
assets['code']['prices/template_2026.json']=enc(R/'python/prices/template_2026.json')
html=(src/'web/index.html').read_text()
html=html.replace('<link rel="stylesheet" href="/style.css">','<style>'+(src/'web/style.css').read_text()+'</style>')
html=html.replace('<title>','<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; script-src \'unsafe-inline\' \'unsafe-eval\' blob:; worker-src blob:; connect-src \'none\'; style-src \'unsafe-inline\'; frame-src blob:; img-src data: blob:; base-uri \'none\'; form-action \'none\'"><link rel="icon" href="data:,"><title>')
html=html.replace('本机计算','浏览器离线版').replace('class="brand" href="/"','class="brand" href="#"')
html=html.replace('id="files" type="file"','id="files" disabled type="file"')
html=html.replace('<header>','<header>')
html=html.replace('<div class="actions">','<div class="actions"><button id="backup">备份本机资料</button><label class="restorelabel">恢复备份<input id="restore-local" type="file" accept=".json"></label>')
html=html.replace('原件保存在本机<br>重复账单自动跳过','资料仅保存在此浏览器<br>可备份后带到另一台电脑')
html=html.replace('<p id="progress" role="status" aria-live="polite"></p>','<p id="progress" role="status" aria-live="polite">正在启动内置计算器，首次打开需稍候…</p>')
app=(src/'web/app.js').read_text().replace('src="/api/original?hash=${rs[0].hash}#page=${rs[0].pages[0]}"','src="${localOriginalUrl(rs[0].hash,rs[0].pages[0])}"')
app=app.replace("fetch('/api/report?'+query(),{signal:controller.signal})","fetch('/api/report?'+query(),{signal:controller.signal})")
html=html.replace('<script src="/app.js"></script>', '<script id="offline-assets" type="application/json">'+json.dumps(assets,separators=(',',':'))+'</script><script>const OFFLINE_WORKER='+json.dumps((R/'worker.js').read_text())+';\n'+(R/'adapter.js').read_text()+'</script><script>'+app+'</script>')
html=html.replace('</style>','.restorelabel{cursor:pointer;border:1px solid #cbd8d0;border-radius:6px;padding:8px 12px;background:white;color:#286b53;font-size:12px}@media print{#backup,.restorelabel{display:none}}</style>')
(R/'dist').mkdir(exist_ok=True)
(R/'dist/index.html').write_text(html,encoding='utf-8')
manifest={str(p.relative_to(R)):hashlib.sha256(p.read_bytes()).hexdigest() for folder in ['python','runtime','wheels','source'] for p in (R/folder).rglob('*') if p.is_file() and '__pycache__' not in str(p)}
for name in ['bridge.py','adapter.js','worker.js','build.py','dependencies.lock.json']:
 manifest[name]=hashlib.sha256((R/name).read_bytes()).hexdigest()
manifest['dist/index.html']=hashlib.sha256((R/'dist/index.html').read_bytes()).hexdigest()
(R/'dist/manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
print('Built offline HTML',len(html.encode()),'bytes')
