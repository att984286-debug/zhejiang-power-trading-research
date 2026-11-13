"""Generate a fictional, full-July platform-shaped workbook for offline QA."""
import sys
from datetime import date
from decimal import Decimal
from openpyxl import Workbook

w = Workbook()
s = w.active
s.title = '匿名回归'
s.append(['电力用户名称', '用户号', '计量点ID', '读数日期', '日电量合计'] + ['时段'+str(i)+'电量' for i in range(1,49)])
for d in range(1,32):
    s.append(['演示企业（虚构数据）', '0000000000001', 'DEMO-METER-001', date(2026,7,d), Decimal('0.048')] + [Decimal('0.001')]*48)
w.save(sys.argv[1])
print('Created fictional fixture:', sys.argv[1])
