"""Read explicitly labelled active-energy totals with consecutive numeric subrows."""
import re,unicodedata
from decimal import Decimal as D

NUM=r'-?\d[\d,]*(?:\.\d+)?'
COLUMNS=('previous_reading','current_reading','multiplier','read','transformer_loss','line_loss','change','billed')

def total_row_groups(text):
    lines=unicodedata.normalize('NFKC',text).replace('−','-').splitlines()
    groups=[];meter=None
    for i,line in enumerate(lines):
        m=re.search(r'计量点编号[:：]\s*(\d+)',line)
        if m:meter=m[1]
        if not meter or '正向有功(总)' not in line:continue
        first=line.split('正向有功(总)',1)[1].strip()
        if not re.fullmatch(r'\s+'.join([NUM]*8),first):continue
        rows=[[D(v.replace(',','')) for v in re.findall(NUM,first)]]
        for continuation in lines[i+1:]:
            continuation=continuation.strip()
            if not continuation:continue
            # A new reading label, meter, header or partial row ends this group.
            if not re.fullmatch(r'\s+'.join([NUM]*8),continuation):break
            rows.append([D(v.replace(',','')) for v in re.findall(NUM,continuation)])
        groups.append({'meter':meter,'line':i,'rows':rows})
    return groups

def merge_total_group(group,independent,page,issues):
    matches=[g for g in independent if g['meter']==group['meter'] and g['rows']==group['rows']]
    verified=len(matches)==1
    if not verified:issues.append('多行计量点总电量未通过两个读取通道核对')
    rows=[dict(zip(COLUMNS,row)) for row in group['rows']]
    for r in rows:
        if r['read']+r['transformer_loss']+r['line_loss']+r['change']!=r['billed']:
            issues.append('计量点抄见、加减与计费电量不平')
    if any(r['change']!=0 for r in rows):
        issues.append('多行计量点含加减电量，需核对结算关系')
    return {'meter':group['meter'],**{k:sum((r[k] for r in rows),D(0)) for k in COLUMNS[3:]},
            'rows':rows,'source_page':page,'independent_rows_verified':verified,
            'method':'同一正向有功总项的连续多行电量逐行核对后合计；零电量行保留'}
