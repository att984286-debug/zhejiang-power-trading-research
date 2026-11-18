"""Curve-derived time-of-use shares; display data must not alter pricing inputs."""
import copy,sys,unittest
from decimal import Decimal as D
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'python'))
from pricing import PACK,calculate
from curve_structure import summarize_curve

class CurveStructure(unittest.TestCase):
 def row(self,month='2026-07',values=None):
  values=values or ['1']*48
  return {'account':'DEMO','name':'虚构企业','month':month,'q':str(sum(map(D,values))),'slots_kwh':values,'buckets':{},'shares':{},'bills':[],'issues':[],'partial':False,'source_type':'curve','curve_records':['demo-row'],'reconciliation':{'note':'虚构'}}
 def test_uniform_curve_counts_and_zero_are_retained(self):
  row=self.row();s=summarize_curve(row,PACK)
  self.assertEqual(s['status'],'已核对')
  self.assertEqual({k:D(v) for k,v in s['buckets'].items()},{'尖峰':D(4),'峰':D(8),'平':D(22),'谷':D(10),'深谷':D(4)})
  self.assertEqual(D(s['shares']['深谷']),D('8.3333'))
  values=['0']*48;values[24]='1.125';s=summarize_curve(self.row(values=values),PACK)
  self.assertEqual(s['buckets']['深谷'],'1.125');self.assertEqual(s['shares']['深谷'],'100.0000');self.assertEqual(s['shares']['峰'],'0.0000')
 def test_september_correction_and_month_isolation(self):
  values=['0']*48;values[24]='12';s=summarize_curve(self.row('2026-09',values),PACK)
  self.assertEqual(s['buckets']['深谷'],'12');self.assertEqual(s['buckets']['谷'],'0')
 def test_missing_or_invalid_data_not_zero(self):
  for change in [{'issues':['缺一天']},{'slots_kwh':['1']*47},{'q':'49'},{'slots_kwh':['-1']+['1']*47,'q':'46'},{'month':'2027-07'}]:
   r=self.row();r.update(change);s=summarize_curve(r,PACK)
   self.assertEqual(s['status'],'待确认');self.assertTrue(all(v is None for v in s['shares'].values()))
  s=summarize_curve(self.row(values=['0']*48),PACK);self.assertEqual(s['status'],'待确认')
 def test_unconfigured_date_dependent_holiday_not_guessed(self):
  s=summarize_curve(self.row('2026-02'),PACK)
  self.assertEqual(s['status'],'待确认');self.assertTrue(any('日期' in x for x in s['issues']))
 def test_inputs_and_profit_unchanged(self):
  r=self.row();before=copy.deepcopy(r);old=calculate([r],'0','2',package='rule-full')
  r['curve_structure']=summarize_curve(r,PACK)
  self.assertEqual({k:v for k,v in r.items() if k!='curve_structure'},before)
  self.assertEqual(calculate([r],'0','2',package='rule-full'),old)

if __name__=='__main__':unittest.main()
