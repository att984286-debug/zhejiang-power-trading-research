"""Multirow, explicitly linked internal allocations; no customer data."""
import copy,sys,unittest
from decimal import Decimal as D
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'python'))
from meter_allocations import ratio_children,verify_allocations,prior_deduction
from meter_rows import total_row_groups,merge_total_group

HEAD='''计量点编号：100000001(电能表编号：123456)
正向有功（总） 0 2 100 200 0 0 -10 190
2 10 100 800 0 0 -40 760
└计量点编号：100000002(定比：0.05)，上级电能表编号:123456
电量明细
定比：0.05 '''
TAIL='\n电费明细\n上网环节线损费用 总 53 0.01 0.53\n'

class MultirowAllocations(unittest.TestCase):
 def verify(self,text,other=None):
  issues=[];groups=total_row_groups(text)
  root=merge_total_group(groups[0],groups,1,issues);meters=[root]
  cs=ratio_children(text);verify_allocations(meters,cs,ratio_children(other or text),issues)
  return meters,issues
 def test_flat_and_split_billed_cell_rows(self):
  flat=HEAD+'1 0 0 11.00\n2 0 0 42.00'+TAIL
  split=HEAD+'1 0 0 11.00\n42.00\n2 0 0'+TAIL
  reverse_split=HEAD+'1 0 0 11.00\n2 0 0\n42.00'+TAIL
  for text in [flat,split,reverse_split]:
   meters,issues=self.verify(text,split if text==flat else flat)
   self.assertFalse(issues);self.assertTrue(meters[0]['internal_allocation_verified'])
   self.assertFalse(prior_deduction(meters[0]));self.assertEqual(meters[0]['change'],D(-50))
   self.assertEqual(meters[1]['read'],D(50));self.assertEqual(meters[1]['transformer_loss'],D(3))
   self.assertEqual(meters[1]['billed'],D(53));self.assertEqual(len(meters[1]['rows']),2)
   self.assertEqual(sum(m['billed'] for m in meters),D(1003))
 def test_child_display_order_can_differ(self):
  text=HEAD+'2 0 0 42.00\n11.00\n1 0 0'+TAIL
  meters,issues=self.verify(text);self.assertFalse(issues)
  self.assertTrue(meters[0]['internal_allocation_verified'])
 def test_old_layout_ends_table_at_receiving_point(self):
  text=HEAD+'0 0 0 50\n受电点：虚构公司\n基本电费计算方式：不计算 合同容量：100\n本期电费明细\n费用组成 计收数量 电费'
  meters,issues=self.verify(text);self.assertFalse(issues)
  self.assertEqual(meters[1]['read'],D(50));self.assertTrue(meters[0]['internal_allocation_verified'])
 def test_round_each_explicit_parent_subrow(self):
  text=(HEAD.replace('0 2 100 200 0 0 -10 190','0 1 100 100 0 0 -1 99')
        .replace('2 10 100 800 0 0 -40 760','1 2 100 100 0 0 -1 99')
        .replace('0.05','0.005'))+'0 0 0 1.00\n0 0 0 1.00'+TAIL
  meters,issues=self.verify(text);self.assertFalse(issues)
  self.assertEqual(meters[1]['read'],D(2));self.assertTrue(meters[0]['internal_allocation_verified'])
 def test_same_total_but_different_child_subrows_block(self):
  text=HEAD+'1 0 0 11.00\n2 0 0 42.00'+TAIL
  other=text.replace('11.00','12.00').replace('42.00','41.00')
  meters,issues=self.verify(text,other)
  self.assertIn('定比分摊未通过两个读取通道核对',issues)
  self.assertTrue(prior_deduction(meters[0]))
 def test_partial_child_row_keeps_block(self):
  text=HEAD+'1 0 0 11.00\n42.00\n2 0'+TAIL
  meters,issues=self.verify(text);self.assertTrue(issues)
  self.assertTrue(prior_deduction(meters[0]))
 def test_offsetting_positive_and_negative_adjustments_block(self):
  text=(HEAD.replace('200 0 0 -10 190','200 0 0 10 210')
        .replace('800 0 0 -40 760','800 0 0 -60 740'))+'1 0 0 11.00\n2 0 0 42.00'+TAIL
  meters,issues=self.verify(text);self.assertTrue(issues)
  self.assertTrue(prior_deduction(meters[0]))
 def test_one_unresolved_parent_does_not_clear_global_blocker(self):
  text=HEAD+'1 0 0 11.00\n2 0 0 42.00'+TAIL
  issues=[];g=total_row_groups(text)[0];root=merge_total_group(g,[g],1,issues)
  other=copy.deepcopy(root);other['meter']='UNLINKED';meters=[root,other];cs=ratio_children(text)
  verify_allocations(meters,cs,ratio_children(text),issues)
  self.assertTrue(root['internal_allocation_verified']);self.assertTrue(prior_deduction(other))
  self.assertIn('多行计量点含加减电量，需核对结算关系',issues)

if __name__=='__main__':unittest.main()
