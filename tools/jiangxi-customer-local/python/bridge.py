"""All business data stays in the browser's virtual filesystem."""
import base64,json
from pathlib import Path
from bills import Store,monthly_csv
from pricing import scenario_csv
STORE=Store('/data')
def restore(saved):
 if not saved:return
 for item in saved.get('originals',[]):
  sha=item['hash'];suffix=item['suffix']
  if len(sha)!=64 or any(c not in '0123456789abcdef' for c in sha) or suffix not in ('.pdf','.xls','.xlsx'):raise ValueError('无效备份原件标识')
  raw=base64.b64decode(item['content'],validate=True)
  import hashlib
  if hashlib.sha256(raw).hexdigest()!=sha:raise ValueError('备份原件指纹不一致')
  (STORE.originals/(sha+suffix)).write_bytes(raw)
 if saved.get('archive'):
  old=STORE.load();new=saved['archive']
  for key,identity in [('records','id'),('curve_records','id'),('files','hash')]:
   values={v[identity]:v for v in old.get(key,[])}
   for v in new.get(key,[]):
    if v[identity] not in values:values[v[identity]]=v
   old[key]=list(values.values())
  STORE.save(old)
 return STORE.load()
def report(args):
 return STORE.report(linkage=args.get('linkage','10'),service_fee=args.get('service_fee','0'),package=args.get('package','linkage'))
def upload(name,content):
 raw=base64.b64decode(content,validate=True)
 result=STORE.upload(name,raw)
 return {'result':result,'archive':STORE.load()}
def export(args):
 r=report(args)
 if args.get('kind')=='csv':data=scenario_csv(r,args.get('account'));kind='text/csv;charset=utf-8';name='客户联动测算.csv'
 elif args.get('kind')=='monthly':data=monthly_csv(r);kind='text/csv;charset=utf-8';name='月度账单.csv'
 else:data=json.dumps(r,ensure_ascii=False,indent=2).encode();kind='application/json';name='完整核对记录.json'
 return {'content':base64.b64encode(data).decode(),'type':kind,'name':name}
