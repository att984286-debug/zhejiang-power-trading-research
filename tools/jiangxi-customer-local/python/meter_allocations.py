"""Recognize explicitly linked same-period fixed-ratio meter reallocations."""
import re,unicodedata
from decimal import Decimal as D,ROUND_HALF_UP

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
  nums=re.findall(r'-?\d[\d,]*(?:\.\d+)?',ratio[2])
  if len(nums)!=4 or not parent_id:continue
  v=[D(n.replace(',','')) for n in nums]
  result.append({'meter':meter,'parent_meter':parent_id,'ratio':D(ratio[1]),'read':v[3]-v[0]-v[1]-v[2],'transformer_loss':v[0],'line_loss':v[1],'change':v[2],'billed':v[3],
                 'read_meaning':'按定比从上级分入的电量，非独立抄见量',
                 'method':'本期定比分摊子计量点（原账单明确上级关系）'})
 return result

def allocation_key(m):return tuple(str(m[k]) for k in ('meter','parent_meter','ratio','read','transformer_loss','line_loss','change','billed'))

def verify_allocations(meters,children,independent,issues):
 from collections import defaultdict
 seen={m['meter'] for m in meters};other={allocation_key(m) for m in independent};groups=defaultdict(list)
 for child in children:
  if child['meter'] in seen:
   issues.append('定比子计量点出现重复或口径冲突');continue
  seen.add(child['meter']);meters.append(child);groups[child['parent_meter']].append(child)
  if allocation_key(child) not in other:issues.append('定比分摊未通过两个读取通道核对')
 for parent,cs in groups.items():
  roots=[m for m in meters if m['meter']==parent and 'parent_meter' not in m]
  if len(roots)!=1:issues.append('未找到唯一的定比分摊上级计量点');continue
  root=roots[0]
  verified=(root['change']<0 and sum(c['read'] for c in cs)==-root['change'] and sum(c['ratio'] for c in cs)<=1
      and all(allocation_key(c) in other and 0<c['ratio']<=1 and c['read']>=0 and c['read']==(root['read']*c['ratio']).quantize(D('1'),rounding=ROUND_HALF_UP) for c in cs))
  if verified:
   root['internal_allocation_verified']=True
   root['allocation_to']=[c['meter'] for c in cs]
   root['change_meaning']='本期定比分摊转出，与子计量点转入核对一致；非前期结算扣减'
  else:issues.append('本期定比分摊关系或电量不平，未解除扣减核对')

def prior_deduction(m):return D(m['change'])<0 and not m.get('internal_allocation_verified',False)
