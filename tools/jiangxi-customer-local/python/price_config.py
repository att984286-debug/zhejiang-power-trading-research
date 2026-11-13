"""Validated, traceable scenario overrides; original public/template inputs stay intact."""
import copy,hashlib,json,io,re
from decimal import Decimal as D
from pricing import PACK
FIELDS=('reference','rolling','da','rt')
def value(v):
 try:n=D(str(v))
 except Exception:raise ValueError('价格必须是有效数字，缺失不按零处理')
 if not n.is_finite() or abs(n)>D('10000000'):raise ValueError('价格不是有限数或超出可处理范围')
 return str(n)
def apply_prices(state):
 p=copy.deepcopy(PACK)
 if not state or not state.get('months'):return p
 if state.get('year')!=PACK['year']:raise ValueError('价格方案年度不匹配，不能跨年套价')
 for month,m in state['months'].items():
  if month not in p['months']:raise ValueError('无效月份')
  base=p['months'][month]
  if len(m['slots'])!=48:raise ValueError('每月必须有48个半小时价格')
  for i,s in enumerate(m['slots']):
   for key in FIELDS:base['slots'][i][key]=value(s[key])
  rw=D(value(m.get('rolling_weight',base['rolling_weight'])))
  sw=D(value(m.get('spot_weight',base['spot_weight'])))
  if not 0<=rw<=1 or not 0<=sw<=1 or rw+sw!=1:raise ValueError('采购比例须在0至100%之间，且合计100%')
  spot=m.get('cost_spot',base['cost_spot'])
  if spot not in ('da','rt'):raise ValueError('现货采购价格须选择日前或实时')
  base.update(rolling_weight=str(rw),spot_weight=str(sw),cost_spot=spot)
 digest=hashlib.sha256(json.dumps(state,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
 p['id']='custom-'+digest[:16];p['scenario_name']=str(state.get('name','自定义价格方案'));p['scenario_sha256']=digest
 return p

def import_prices(name,raw):
 """Explicit tidy-price XLS/XLSX and the exact supplied template; no inference of trade fills."""
 sha=hashlib.sha256(raw).hexdigest()
 if name.lower().endswith('.xlsx'):
  import openpyxl
  w=openpyxl.load_workbook(io.BytesIO(raw),read_only=True,data_only=True)
  if '联动类' in w.sheetnames:
   s=w['联动类'];months={}
   for k,m in PACK['months'].items():
    slots=[{f:value(s[slot['cells'][f]].value) for f in FIELDS} for slot in m['slots']]
    months[k]={**{f:m[f] for f in ('rolling_weight','spot_weight','cost_spot')},'slots':slots}
   w.close();state={'year':2026,'months':months,'name':name,'source':{'filename':name,'sha256':sha,'kind':'导入模板／采购假设，未认证成交'}};apply_prices(state);return state
  sheets=[list(s.iter_rows(values_only=True)) for s in w];w.close()
 elif name.lower().endswith('.xls'):
  import xlrd
  w=xlrd.open_workbook(file_contents=raw);sheets=[[[c.value for c in s.row(i)] for i in range(s.nrows)] for s in w.sheets()]
 else:raise ValueError('价格文件须为XLS或XLSX')
 required=['月份','时段','参考价','滚撮价','日前价','实时价'];months={};seen=set()
 for rows in sheets:
  for i,row in enumerate(rows[:20]):
   h={str(v).strip():j for j,v in enumerate(row) if v is not None}
   if all(k in h for k in required):break
  else:continue
  for row in rows[i+1:]:
   if row[h['月份']] in (None,''):continue
   month=str(row[h['月份']]).strip();match=re.fullmatch(r'2026-(0[1-9]|1[012])',month)
   if not match:raise ValueError('价格月份请使用2026-MM格式；不推断年度')
   key=str(int(match[1]));slot=D(str(row[h['时段']]))
   if slot!=int(slot) or not 1<=slot<=48:raise ValueError('价格时段须为1至48的整数（1=00:00—00:30）')
   idx=int(slot)-1
   if (key,idx) in seen:raise ValueError('同月份时段出现重复价格，未自动覆盖')
   seen.add((key,idx));months.setdefault(key,{**{f:PACK['months'][key][f] for f in ('rolling_weight','spot_weight','cost_spot')},'slots':[None]*48})['slots'][idx]={f:value(row[h[c]]) for f,c in zip(FIELDS,required[2:])}
 if not months or any(any(s is None for s in m['slots']) for m in months.values()):raise ValueError('每个导入月份需完整48行；表头为月份、时段、参考价、滚撮价、日前价、实时价')
 state={'year':2026,'months':months,'name':name,'source':{'filename':name,'sha256':sha,'kind':'导入测算价格，未认证买入成交'}};apply_prices(state);return state
