import unittest,sys,copy
from pathlib import Path
from decimal import Decimal as D
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'python'))
from meter_allocations import ratio_children,verify_allocations,prior_deduction
TEXT='''计量点编号：100000001(电能表编号：123456)，主计量点
正向有功（总） 100 110 100 1000 0 0 -50 950
└计量点编号：100000002(定比：0.05)，上级计量点编号:100000001
定比：0.05 0 0 0 50
'''
class Allocation(unittest.TestCase):
 def parent(self):return {'meter':'100000001','read':D(1000),'change':D(-50),'billed':D(950)}
 def test_explicit_reallocation(self):
  m=[self.parent()];cs=ratio_children(TEXT);issues=[];verify_allocations(m,cs,ratio_children(TEXT),issues)
  self.assertFalse(issues);self.assertEqual(sum(x['billed'] for x in m),D(1000));self.assertFalse(prior_deduction(m[0]));self.assertEqual(m[0]['change'],D(-50))
 def test_meter_serial_link(self):
  text=TEXT.replace('上级计量点编号:100000001','上级电能表\n编号:123456');self.assertEqual(ratio_children(text)[0]['parent_meter'],'100000001')
 def test_adjacent_analysis_number_does_not_join_identifier(self):
  text=TEXT.replace('上级计量点编号:100000001','上级计量点编号:100000001 6.峰谷分析')
  self.assertEqual(ratio_children(text)[0]['parent_meter'],'100000001')
 def test_allocation_with_child_losses(self):
  text=TEXT.replace('上级计量点编号:100000001','上级电能表编\n号:123456').replace('0 0 0 50','3 1 0 54')
  m=[self.parent()];issues=[];verify_allocations(m,ratio_children(text),ratio_children(text),issues)
  self.assertFalse(issues);self.assertFalse(prior_deduction(m[0]));self.assertEqual(m[1]['read'],D(50));self.assertEqual(m[1]['billed'],D(54))
 def test_unmatched_negative_remains_prior(self):
  m=[self.parent()];issues=[];verify_allocations(m,[],[],issues);self.assertTrue(prior_deduction(m[0]))
 def test_mismatch_and_second_channel_do_not_unlock(self):
  for mode in ('amount','channel','ratio'):
   m=[self.parent()];cs=ratio_children(TEXT);ind=copy.deepcopy(cs)
   if mode=='amount':cs[0]['billed']=D(49)
   if mode=='ratio':cs[0]['ratio']=D('.06');ind=copy.deepcopy(cs)
   if mode=='channel':ind=[]
   issues=[];verify_allocations(m,cs,ind,issues);self.assertTrue(issues);self.assertTrue(prior_deduction(m[0]))
 def test_month_aggregation_keeps_real_prior_deductions(self):
  from bills import aggregate
  def row(identity,q,meter,end):
   return {'id':identity,'hash':identity,'name':'虚构企业','account':'DEMO','month':'2026-01','start':'2026-01-01','end':end,'q':str(q),'agency':'1','bill':'2','buckets':{'尖峰':'0','峰':'0','平':str(q),'谷':'0','深谷':'0'},'meters':[meter],'issues':[]}
  tail=row('tail',950,self.parent(),'2026-02-01')
  self.assertTrue(aggregate([tail])[0]['issues'])
  head=row('head',50,{'meter':'100000001','read':'50','change':'0','billed':'50'},'2026-01-16')
  merged=aggregate([head,tail])[0];self.assertFalse(merged['issues']);self.assertEqual(merged['q'],'1000')
  meters=[self.parent()];issues=[];verify_allocations(meters,ratio_children(TEXT),ratio_children(TEXT),issues)
  complete=row('complete',1000,meters[0],'2026-02-01');complete['meters']=meters
  self.assertFalse(aggregate([complete])[0]['issues'])
if __name__=='__main__':unittest.main()
