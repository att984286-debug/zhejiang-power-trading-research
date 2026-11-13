"""All business data stays in the browser's virtual filesystem."""
import base64,json
from pathlib import Path
from bills import Store,monthly_csv
from pricing import scenario_csv,PACK,calculate
from price_config import apply_prices, import_prices
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
 state=args.get('price_state') or {}
 if isinstance(state,str):state=json.loads(state)
 pack=apply_prices(state)
 r=STORE.report(linkage=args.get('linkage','10'),service_fee=args.get('service_fee','0'),package=args.get('package','rule-full'),pack=pack)
 r['price_state']=state
 if state.get('months'):
  r['scenario']['notes']=[('采购采用本次自定义方案的各月比例、滚撮价及日前／实时选择，详见月度明细；未认证为实际买入成交。' if n.startswith('采购成本沿用原表') else n) for n in r['scenario']['notes']]
 if state.get('months'):
  r['baseline']=calculate(r['months'],args.get('linkage','10'),args.get('service_fee','0'),package=args.get('package','rule-full'))['customers']
 return r
def price_import(name,content):
 return import_prices(name,base64.b64decode(content,validate=True))
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
