import base64,json,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parent
def encode(p):return base64.b64encode(p.read_bytes()).decode()
runtime=['pyodide.js','pyodide.asm.js','pyodide.asm.wasm','python_stdlib.zip','pyodide-lock.json']
assets={'runtime':{n:encode(ROOT/'runtime'/n) for n in runtime},
 'wheels':{p.name:encode(p) for p in (ROOT/'dist/vendor/wheels').glob('*.whl')},
 'python':{p.name:encode(p) for p in (ROOT/'dist/python').glob('*.py')}}
doc=(ROOT/'index.template.html.in').read_text().replace('__ASSETS__',json.dumps(assets,separators=(',',':'))).replace('__WORKER__',json.dumps((ROOT/'worker.js').read_text()))
(ROOT/'dist/index.html').write_text(doc)
manifest={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'dist/python').glob('*.py')}
(ROOT/'dist/engine-manifest.json').write_text(json.dumps(manifest,indent=2))
print('已构建自包含HTML：',len(doc.encode()),'bytes')
