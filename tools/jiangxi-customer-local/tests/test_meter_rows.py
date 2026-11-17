"""Anonymous multirow meter totals; preserve zero rows, losses and blocking checks."""
import sys,unittest
from decimal import Decimal as D
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'python'))
from meter_rows import total_row_groups,merge_total_group

TEXT='''计量点编号：100000001,100000001(电能表编号：123456)
示数类型 上期示数 本期示数 倍率 抄见电量 变损 线损 加减 计费电量
正向有功（总） 10.00 10.00 1000 0 0 0 0 0
10.00 22.34 1000 12340 0 1 0 12341
正向有功（峰） / / 1000 0 0 0 0 0
/ / 1000 2340 0 0 0 2340
正向无功（总） 1.00 2.00 1000 1000 0 0 0 1000
'''

class MeterRows(unittest.TestCase):
 def test_zero_then_nonzero_with_loss(self):
  groups=total_row_groups(TEXT);self.assertEqual(len(groups),1)
  g=groups[0];self.assertEqual(len(g['rows']),2);issues=[]
  r=merge_total_group(g,total_row_groups(TEXT),2,issues)
  self.assertEqual((r['read'],r['billed'],r['line_loss']),(D(12340),D(12341),D(1)))
  self.assertFalse(issues);self.assertEqual(r['source_page'],2)
  self.assertEqual(r['rows'][0]['billed'],D(0));self.assertEqual(r['rows'][1]['billed'],D(12341))
 def test_both_rows_nonzero_and_decimals(self):
  text=TEXT.replace('10.00 10.00 1000 0 0 0 0 0','9 10 1000 1000.25 0.25 0 0 1000.50')
  issues=[];r=merge_total_group(total_row_groups(text)[0],total_row_groups(text),1,issues)
  self.assertEqual(r['billed'],D('13341.50'));self.assertEqual(r['read'],D('13340.25'));self.assertFalse(issues)
 def test_other_meter_not_absorbed(self):
  text=TEXT.split('正向有功（峰）')[0]+'计量点编号：200000002\n正向有功（总） 0 1 1000 1000 0 0 0 1000\n'
  groups=total_row_groups(text);self.assertEqual(len(groups),2)
  self.assertEqual(len(groups[0]['rows']),2);self.assertEqual(len(groups[1]['rows']),1)
 def test_bad_or_missing_independent_rows_block(self):
  g=total_row_groups(TEXT)[0]
  for other in [[],total_row_groups(TEXT.replace('12341','12342')),total_row_groups(TEXT)*2]:
   issues=[];merge_total_group(g,other,1,issues);self.assertIn('多行计量点总电量未通过两个读取通道核对',issues)
 def test_arithmetic_mismatch_keeps_block(self):
  text=TEXT.replace('12341','12342');issues=[]
  merge_total_group(total_row_groups(text)[0],total_row_groups(text),1,issues)
  self.assertIn('计量点抄见、加减与计费电量不平',issues)
 def test_adjustments_not_silently_netted(self):
  text=TEXT.replace('0 0 0 0 0\n10.00','10 0 0 -10 0\n10.00').replace('12340 0 1 0 12341','12340 0 1 10 12351')
  issues=[];merge_total_group(total_row_groups(text)[0],total_row_groups(text),1,issues)
  self.assertIn('多行计量点含加减电量，需核对结算关系',issues)
 def test_partial_or_unlabelled_lines_not_guessed(self):
  self.assertEqual(total_row_groups('0 0 1000 0 0 0 0 0\n'+TEXT.splitlines()[3]),[])
  g=total_row_groups(TEXT.replace('10.00 22.34 1000 12340 0 1 0 12341','10.00 22.34 1000 12340 1 0 12341'))[0]
  self.assertEqual(len(g['rows']),1)

if __name__=='__main__':unittest.main()
