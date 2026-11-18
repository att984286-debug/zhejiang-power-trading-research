"""Recognize explicitly linked same-period fixed-ratio meter reallocations."""
import re,unicodedata
from collections import Counter
from decimal import Decimal as D,ROUND_HALF_UP

NUM=r'-?\d[\d,]*(?:\.\d+)?'
def ratio_rows(section):
 # A printed billed cell can precede the other three cells in PDF text order.
 # Accept only complete four-column rows or an explicit 1+3 / 3+1 split.
 lines=[s.strip() for s in section.splitlines() if s.strip() and not s.strip().startswith('emss-')]
 rows=[];i=0
 def numbers(s):
  return [D(n.replace(',','')) for n in re.findall(NUM,s)] if re.fullmatch(r'\s*'+NUM+r'(?:\s+'+NUM+r')*\s*',s) else []
 while i<len(lines):
  v=numbers(lines[i]);i+=1
  if len(v)==4:rows.append(v);continue
  other=numbers(lines[i]) if i<len(lines) else []
  if len(v)==1 and len(other)==3:rows.append(other+v);i+=1
  elif len(v)==3 and len(other)==1:rows.append(v+other);i+=1
  else:return rows,False
 return rows,bool(rows)

def ratio_children(text):
 t=unicodedata.normalize('NFKC',text);heads=list(re.finditer(r'(?:^|\n)\s*[└├]?\s*计量点编号[:：]\s*(\d+)',t));blocks=[];tables={}
 for i,h in enumerate(heads):
  block=t[h.start():heads[i+1].start() if i+1<len(heads) else len(t)];c=re.sub(r'\s+','',block)
  em=re.search(r'(?<!上级)电能表编号[:：](\d+)',c)
  if em:tables[em[1]]=h[1]
  blocks.append((h[1],block,c))
 result=[]
 for meter,block,c in blocks:
  ratio=re.search(r'^\s*定比[:：]([0-9.]+)\s+([^\n]+)',block,re.M)
  if not ratio:continue
  parent=re.search(r'上级\s*计量点\s*编号[:：]\s*(\d+)',block)
  parent_table=re.search(r'上\s*级\s*电\s*能\s*表\s*编\s*号[:：]\s*(\d+)',block)
  parent_id=parent[1] if parent else tables.get(parent_table[1]) if parent_table else None
  section=re.split(r'(?:本期)?电费明细|(?:^|\n)\s*\*?\s*受电点[:：]',ratio[2]+block[ratio.end():],maxsplit=1)[0]
  values,complete=ratio_rows(section)
  if not values or not parent_id:continue
  rows=[{'read':v[3]-v[0]-v[1]-v[2],'transformer_loss':v[0],'line_loss':v[1],'change':v[2],'billed':v[3]} for v in values]
  child={'meter':meter,'parent_meter':parent_id,'ratio':D(ratio[1]),**{k:sum((r[k] for r in rows),D(0)) for k in rows[0]},
                 'read_meaning':'按定比从上级分入的电量，非独立抄见量',
                 'method':'本期定比分摊子计量点（原账单明确上级关系）'}
  if len(rows)>1 or not complete:child.update(rows=rows,rows_complete=complete)
  result.append(child)
 return result

def allocation_key(m):
 base=tuple(str(m[k]) for k in ('meter','parent_meter','ratio','read','transformer_loss','line_loss','change','billed'))
 rows=tuple(sorted(tuple(r[k] for k in ('read','transformer_loss','line_loss','change','billed')) for r in m.get('rows',[])))
 return base+(m.get('rows_complete',True),rows)

def expected_read(read,ratio):return (read*ratio).quantize(D('1'),rounding=ROUND_HALF_UP)

def child_matches(root,child):
 if not child.get('rows_complete',True):return False
 if not root.get('rows'):return child['read']==expected_read(root['read'],child['ratio'])
 expected=[expected_read(r['read'],child['ratio']) for r in root['rows']]
 return (sum(expected,D(0))==child['read'] and (not child.get('rows') or
   (all(r['read']>=0 and r['change']==0 for r in child['rows']) and Counter(r['read'] for r in child['rows'])==Counter(expected))))

def verify_allocations(meters,children,independent,issues):
 from collections import defaultdict
 seen={m['meter'] for m in meters};other={allocation_key(m) for m in independent};groups=defaultdict(list)
 for child in children:
  if child['meter'] in seen:
   issues.append('定比子计量点出现重复或口径冲突');continue
  seen.add(child['meter']);meters.append(child);groups[child['parent_meter']].append(child)
  if allocation_key(child) not in other:issues.append('定比分摊未通过两个读取通道核对')
  if not child.get('rows_complete',True):issues.append('定比分摊多行明细不完整，待核对')
 for parent,cs in groups.items():
  roots=[m for m in meters if m['meter']==parent and 'parent_meter' not in m]
  if len(roots)!=1:issues.append('未找到唯一的定比分摊上级计量点');continue
  root=roots[0]
  row_match=(not root.get('rows') or (root.get('independent_rows_verified') and all(
      r['change']<=0 and -r['change']==sum((expected_read(r['read'],c['ratio']) for c in cs),D(0)) for r in root['rows'])))
  verified=(root['change']<0 and row_match and sum(c['read'] for c in cs)==-root['change'] and sum(c['ratio'] for c in cs)<=1
      and all(allocation_key(c) in other and 0<c['ratio']<=1 and c['read']>=0 and child_matches(root,c) for c in cs))
  if verified:
   root['internal_allocation_verified']=True
   root['allocation_to']=[c['meter'] for c in cs]
   root['change_meaning']='本期定比分摊转出，与子计量点转入核对一致；非前期结算扣减'
  else:issues.append('本期定比分摊关系或电量不平，未解除扣减核对')
 # Resolve the earlier provisional blocker only after every affected parent has
 # explicit, independently verified internal-transfer evidence.
 if not any(m.get('rows') and any(r['change']!=0 for r in m['rows']) and not m.get('internal_allocation_verified') for m in meters if 'parent_meter' not in m):
  issues[:]=[i for i in issues if i!='多行计量点含加减电量，需核对结算关系']

def prior_deduction(m):return D(m['change'])<0 and not m.get('internal_allocation_verified',False)
