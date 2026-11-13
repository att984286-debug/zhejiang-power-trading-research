"""Confirmed platform format: MWh, slots 1..48 = 00:00..24:00."""
import calendar,hashlib,json,sys
from collections import defaultdict
from datetime import date,datetime
from decimal import Decimal as D
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent/'vendor'))

def number(v):
 if isinstance(v,bool) or v is None or str(v).strip()=='':raise ValueError('电量缺失，未当零处理')
 try:n=D(str(v).replace(',','').strip())
 except Exception:raise ValueError('无效电量')
 if not n.is_finite():raise ValueError('电量不是有限数')
 return n

def identifier(v):
 if isinstance(v,float):
  if not v.is_integer() or abs(v)>=10**15:raise ValueError('户号或计量点以数字存储且可能失真')
  return str(int(v))
 s=str(v or '').strip()
 if not s:raise ValueError('户号或计量点缺失')
 return s

def extract_curve(path,filename):
 path=Path(path);sha=hashlib.sha256(path.read_bytes()).hexdigest()
 if path.suffix=='.xls':
  import xlrd
  w=xlrd.open_workbook(path);sheets={s.name:[[xlrd.xldate_as_datetime(c.value,w.datemode) if c.ctype==xlrd.XL_CELL_DATE else c.value for c in s.row(i)] for i in range(s.nrows)] for s in w.sheets()}
 else:
  import openpyxl
  w=openpyxl.load_workbook(path,read_only=True,data_only=True)
  sheets={s.title:list(s.iter_rows(values_only=True)) for s in w};w.close()
 candidates=[]
 required=['电力用户名称','用户号','计量点ID','读数日期','日电量合计']+['时段'+str(i)+'电量' for i in range(1,49)]
 for sn,rows in sheets.items():
  for i,row in enumerate(rows[:20]):
   h={str(v).strip():j for j,v in enumerate(row) if v is not None}
   if all(k in h for k in required):candidates.append((sn,rows,i,h))
 if len(candidates)!=1:raise ValueError('未找到唯一的已确认平台48点曲线表；不要靠文件名猜测单位')
 sn,rows,head,h=candidates[0];records=[];footers=[];file_issues=[]
 for i,row in enumerate(rows[head+1:],head+2):
  name=str(row[h['电力用户名称']] or '').strip()
  if not name:continue
  if name=='合计':footers.append(row);continue
  try:
   uid=identifier(row[h['用户号']]);meter=identifier(row[h['计量点ID']]);dt=row[h['读数日期']]
   ds=dt.date().isoformat() if isinstance(dt,datetime) else dt.isoformat() if isinstance(dt,date) else str(dt).strip()
   d=date.fromisoformat(ds);values=[number(row[h['时段'+str(k)+'电量']]) for k in range(1,49)];total=number(row[h['日电量合计']])
  except Exception as e:raise ValueError(f'{sn}第{i}行：{e}')
  issues=[]
  if any(v<0 for v in values):issues.append('存在负电量，需确认更正口径')
  if sum(values)!=total:issues.append('48点之和与日电量合计不一致')
  sig=json.dumps([uid,meter,ds,name,[str(v) for v in values],str(total)],ensure_ascii=False)
  records.append({'id':hashlib.sha256(sig.encode()).hexdigest()[:24],'hash':sha,'filename':filename,'sheet':sn,'row':i,'name':name,'account':uid,'meter':meter,'meter_name':str(row[h.get('计量点名称',h['计量点ID'])]),'date':ds,'month':ds[:7],'slots_mwh':[str(v) for v in values],'daily_mwh':str(total),'issues':issues,'unit':'MWh','grain_minutes':30,'first_slot':'00:00-00:30','format_basis':'用户于2026-11-13确认该平台导出单位MWh，时段1为00:00—00:30'})
 if not records:raise ValueError('曲线没有有效日期记录')
 if len(footers)>1:raise ValueError('出现多个合计行，需确认分组边界')
 if footers:
  footer=footers[0]
  if number(footer[h['日电量合计']])!=sum(number(r['daily_mwh']) for r in records):file_issues.append('文件月合计与明细不一致')
  for k in range(48):
   if number(footer[h['时段'+str(k+1)+'电量']])!=sum(number(r['slots_mwh'][k]) for r in records):file_issues.append('时段'+str(k+1)+'合计与明细不一致')
 for r in records:r['issues']+=file_issues
 return records

def curve_months(records,bills):
 groups=defaultdict(list);seen=set();lookup={(r['account'],r['month']):r for r in bills}
 for r in records:
  if r['id'] not in seen:groups[r['account'],r['month']].append(r);seen.add(r['id'])
 result=[]
 for (account,month),rs in sorted(groups.items()):
  issues=[x for r in rs for x in r['issues']];keys=defaultdict(list);meters=defaultdict(set)
  for r in rs:keys[r['meter'],r['date']].append(r);meters[r['meter']].add(r['date'])
  if any(len(v)>1 for v in keys.values()):issues.append('同一计量点同一天存在不同版本，未重复计入或自动覆盖')
  if len({r['name'] for r in rs})>1:issues.append('同一户号出现不同户名')
  y,m=map(int,month.split('-'));expected={f'{month}-{d:02}' for d in range(1,calendar.monthrange(y,m)[1]+1)}
  for meter,days in meters.items():
   if days!=expected:issues.append(f'计量点{meter}缺少{len(expected-days)}天，需补齐或确认入退市边界')
  slots=[sum((D(r['slots_mwh'][i])*1000 for r in rs),D(0)) for i in range(48)]
  q=sum(slots);ref=lookup.get((account,month));known=bool(ref and not ref['issues'] and not ref['partial'])
  delta=D(ref['q'])-q if known else None
  note='已与账单总量核对一致' if delta==0 else f'账单比曲线相差{delta}度；调平或修正尚未计入' if delta is not None else '未提供可用月结电量，未核算调平费'
  result.append({'account':account,'name':rs[0]['name'],'month':month,'q':str(q),'slots_kwh':[str(v) for v in slots],'source_type':'curve','count':len(rs),'meters':sorted(meters),'days':len({r['date'] for r in rs}),'curve_records':[r['id'] for r in rs],'bills':ref['bills'] if ref else [],'issues':sorted(set(issues)),'partial':False,'agency':ref['agency'] if ref else None,'bill':ref['bill'] if ref else None,'buckets':{},'shares':{},'status':'待核对' if issues else '已核对','merge_reason':'实际曲线优先；按计量点和日期汇总','reconciliation':{'bill_q':ref['q'] if known else None,'delta_kwh':str(delta) if delta is not None else None,'note':note},'curve_sources':[{'file':r['filename'],'hash':r['hash'],'sheet':r['sheet'],'row':r['row'],'date':r['date'],'meter':r['meter'],'columns':'H:BC','unit':'MWh'} for r in rs]})
 return result
