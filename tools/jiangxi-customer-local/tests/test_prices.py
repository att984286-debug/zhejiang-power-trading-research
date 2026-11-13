import unittest,sys,copy,io,tempfile
from pathlib import Path
from decimal import Decimal as D
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'python'))
from pricing import PACK,calculate
from price_config import apply_prices,import_prices
class Prices(unittest.TestCase):
 def state(self):
  m=PACK['months']['7'];return {'year':2026,'name':'虚构试算','months':{'7':{'slots':[{k:s[k] for k in ('reference','rolling','da','rt')} for s in m['slots']],**{k:m[k] for k in ('rolling_weight','spot_weight','cost_spot')}}}}
 def test_validation_and_isolation(self):
  state=self.state();state['months']['7']['slots'][0]['rolling']='-5.123456';p=apply_prices(state)
  self.assertEqual(p['months']['8'],PACK['months']['8']);self.assertNotEqual(p['months']['7'],PACK['months']['7']);self.assertNotEqual(p['id'],PACK['id'])
  for v in ('','NaN','Infinity',None):
   s=self.state();s['months']['7']['slots'][0]['rolling']=v
   with self.assertRaises(ValueError):apply_prices(s)
  state['year']=2027
  with self.assertRaises(ValueError):apply_prices(state)
 def test_break_even_uses_custom_prices(self):
  state=self.state()
  for s in state['months']['7']['slots']:s['rolling']='1000'
  p=apply_prices(state);row={'account':'DEMO','name':'虚构企业','month':'2026-07','q':'1000','slots_kwh':['1000']+['0']*47,'buckets':{},'bills':[],'issues':[],'partial':False,'source_type':'curve','reconciliation':{'note':'虚构'}}
  result=calculate([row],pack=p,package='rule-full');fee=result['customers'][0]['break_even_fee']['low']
  if D(fee)<=100:
   self.assertGreaterEqual(D(calculate([row],service_fee=fee,pack=p,package='rule-full')['customers'][0]['profit']['low']),0)
  # Independently confirm unbounded break-even matches direct fee contribution before slot rounding.
  need=(D(result['months'][0]['cost']['low'])-D(result['months'][0]['revenue']['low']))
  self.assertLess(abs(D(fee)-max(D(0),need)),D('.02'))
 def test_tidy_import(self):
  from openpyxl import Workbook
  w=Workbook();s=w.active;s.append(['月份','时段','参考价','滚撮价','日前价','实时价'])
  for i in range(48):s.append(['2026-07',i+1,300,-1 if i==0 else 400,200,100])
  b=io.BytesIO();w.save(b);p=apply_prices(import_prices('示例.xlsx',b.getvalue()));self.assertEqual(p['months']['7']['slots'][0]['rolling'],'-1')
 def test_group_footers(self):
  from openpyxl import Workbook
  from curves import extract_curve
  w=Workbook();s=w.active
  s.append(['电力用户名称','用户号','计量点ID','读数日期','日电量合计']+['时段'+str(i)+'电量' for i in range(1,49)])
  for day in (1,2):
   s.append(['虚构','DEMO','METER',f'2026-07-{day:02}',48]+[1]*48)
   s.append(['合计',None,None,None,48]+[1]*48)
  with tempfile.TemporaryDirectory() as td:
   p=Path(td)/'demo.xlsx';w.save(p);rs=extract_curve(p,p.name);self.assertEqual(len(rs),2);self.assertTrue(all(not r['issues'] for r in rs))
   s['E5']=49;w.save(p);self.assertTrue(all(r['issues'] for r in extract_curve(p,p.name)))
if __name__=='__main__':unittest.main()
