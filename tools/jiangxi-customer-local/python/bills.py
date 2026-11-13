"""Evidence-preserving Jiangxi bill extraction. No tariff/profit assumptions."""
import csv, hashlib, io, json, re, unicodedata
from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
import pdfplumber
from pypdf import PdfReader

VERSION = '3.0.0'
PARSER_REVISION = 'fixed-ratio-20261113'
from meter_allocations import ratio_children,verify_allocations,prior_deduction
KINDS = ['尖峰','峰','平','谷','深谷']
NUM = r'-?\d[\d,]*(?:\.\d+)?'
D = Decimal

def compact(s):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', s)).replace('−','-')

def amount(s):
    return D(s.replace(',',''))

def match_value(pattern, text):
    m = re.search(pattern, text)
    return amount(m[1]) if m else None

def purchase_fee(text):
    found=[]
    for label in ['代理购电电费','市场化购电电费','零售交易电费']:
        v=match_value(r'(?:\(\d+\)\s*)?'+label+r'\s*('+NUM+r')(?=\s|$)',unicodedata.normalize('NFKC',text))
        if v is not None:found.append((label,v))
    return found[0] if len(found)==1 else ('购电费用项目缺失或存在多种口径，待核对',None)

def fields(text):
    s=compact(text)
    return {'q': match_value(r'本期电量('+NUM+r')千瓦时',s),
            'bill': match_value(r'本期电费('+NUM+r')元',s),
            'agency': purchase_fee(text)[1]}

def buckets(text):
    s=compact(text)
    m=re.search(r'本期您用电的峰谷电量为[:：](.*?)(?:本期您用电的峰谷分时比例|上期峰谷)',s)
    if not m:return {}
    out={}
    for k in KINDS:
        pattern=(r'(?<!尖)' if k=='峰' else r'(?<!深)' if k=='谷' else '')+k+'('+NUM+r')千瓦时'
        v=match_value(pattern,m[1])
        if v is not None:out[k]=v
    return out

def dump(v):
    return json.dumps(v,ensure_ascii=False,indent=2,default=str)

def extract_pdf(path, filename=None):
    path=Path(path); raw=path.read_bytes(); sha=hashlib.sha256(raw).hexdigest()
    reader=PdfReader(io.BytesIO(raw))
    if reader.is_encrypted:raise ValueError('PDF已加密，请提供可读取的账单。')
    if len(reader.pages)>250:raise ValueError('单个PDF超过250页，请分批上传。')
    texts=[p.extract_text() or '' for p in reader.pages]
    if not any('国网江西省电力' in compact(t) for t in texts[:2]):
        raise ValueError('未确认是国网江西账单，此版暂不自动采用其他地区账单。')
    starts=[i for i,t in enumerate(texts) if re.search(r'户\s*号\s*\d{8,}',t) and '本期电量' in t]
    if not starts:raise ValueError('未识别出带文字层的账单；扫描件或不支持的版式待人工核对，不进行OCR猜数。')
    records=[]
    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        for j,start in enumerate(starts):
            end=starts[j+1] if j+1<len(starts) else len(texts)
            text='\n'.join(texts[start:end]); head=texts[start]; s=compact(head)
            issues=[]; warnings=[]
            account=re.search(r'户号(\d{8,})',s)[1]
            nm=re.search(r'户名\s*([^\n]+)',head)
            name=re.split(r'电压等级|供电服务单位',nm[1])[0].strip() if nm else ''
            dates=re.findall(r'20\d{2}-\d{2}-\d{2}',head.split('费用类型')[0])[:2]
            try:
                first,last=map(date.fromisoformat,dates)
                if last<=first:raise ValueError()
                following=date(first.year+first.month//12,first.month%12+1,1)
                if last>following:issues.append('跨月周期，需确认各月归属')
            except (ValueError,TypeError):
                first=last=None;issues.append('用电周期无法可靠识别')
            vals=fields(text); qs=buckets(head)
            secondary=[];meters=[]; all_filtered=[]; rotated=0
            for pg in range(start,end):
                page=pdf.pages[pg]
                rotated+=sum(abs(c.get('matrix',(1,0,0,1,0,0))[1])>.01 for c in page.chars)
                clean=page.filter(lambda o:o.get('object_type')!='char' or abs(o.get('matrix',(1,0,0,1,0,0))[1])<.01)
                ct=clean.extract_text(x_tolerance=3) or ''; all_filtered.append(ct)
                secondary.append(fields(ct))
                # Table body is the left 68% for the verified bill layouts.
                boundaries=[w['x0'] for w in clean.extract_words() if w['text']=='用能分析']
                edge=min(boundaries) if boundaries else page.width if '示数类型' in ct and '计费电量' in ct else page.width*.66
                table=clean.crop((0,0,edge,page.height)).extract_text(x_tolerance=3) or ''
                meter=None
                for line in table.splitlines():
                    mi=re.search(r'计量点编号[:：](\d+)',compact(line))
                    if mi:meter=mi[1]
                    if '正向有功（总）' in line:
                        nums=re.findall(NUM,line.split('正向有功（总）',1)[1])
                        if len(nums)>=8 and meter:
                            v=list(map(amount,nums[:8]))
                            if v[3]+v[4]+v[5]+v[6]!=v[7]:issues.append('计量点抄见、加减与计费电量不平')
                            meters.append({'meter':meter,'read':v[3],'change':v[6],'billed':v[7]})
                        elif len(nums)==1 and meter:
                            # Replacement-meter rows: billed total is a vertically
                            # merged cell; independently sum the reading column.
                            words=clean.extract_words(x_tolerance=3)
                            labels=[w for w in words if w['text']=='正向有功（总）']
                            for label in labels:
                                same=[w for w in words if 350<w['x0']<390 and abs(w['top']-label['top'])<2 and re.fullmatch(NUM,w['text'])]
                                if not same or amount(same[0]['text'])!=amount(nums[0]):continue
                                band=[w for w in words if abs(w['top']-label['top'])<24 and re.fullmatch(NUM,w['text'])]
                                reads=[amount(w['text']) for w in band if 225<w['x0']<270]
                                adjustments=[amount(w['text']) for w in band if 275<w['x0']<350]
                                billed=amount(nums[0])
                                if reads and sum(reads)==billed and adjustments and all(x==0 for x in adjustments):
                                    meters.append({'meter':meter,'read':billed,'change':D(0),'billed':billed,'method':'换表多行读数合计与合并计费单元格核对'})
                                    break
            verify_allocations(meters,ratio_children('\n'.join(all_filtered)),ratio_children(text),issues)
            evidence={}
            for key,label in [('q','本期电量'),('bill','本期电费'),('agency',purchase_fee(text)[0])]:
                value=vals[key]; others=[v[key] for v in secondary if v[key] is not None]
                if value is None:issues.append(label+'缺失或无法识别')
                elif not others:issues.append(label+'未通过第二读取通道核对')
                elif others[0]!=value:issues.append(label+'两种读取方式不一致，需核对小数点及数字')
                evidence[key]={'value':value,'pages':[start+i+1 for i,v in enumerate(secondary) if v[key] is not None], 'label':label}
            if not name:issues.append('户名缺失')
            if len(qs)!=5:issues.append('五类本期分时电量不完整')
            elif vals['q'] is not None and sum(qs.values())!=vals['q']:issues.append('五类分时电量之和不等于本期电量')
            # Independent geometry-based reading of right-hand current-period panel.
            right=pdf.pages[start].filter(lambda o:o.get('object_type')!='char' or abs(o.get('matrix',(1,0,0,1,0,0))[1])<.01)
            rt=right.crop((right.width*.66,0,right.width,right.height)).extract_text(x_tolerance=1) or ''
            qs2=buckets(rt)
            if qs2!=qs:issues.append('分时电量未通过右侧原文交叉核对')
            if meters and vals['q'] is not None and sum(m['billed'] for m in meters)!=vals['q']:
                issues.append('计量点计费电量合计不等于本期电量')
            pn=re.search(r'当前期数[ \t]*([^\r\n]*)',head)
            # Content identity ignores filenames, watermark timestamps and page ordering.
            signature=dump([name,account,dates,vals,qs,meters])
            if purchase_fee(text)[0]!='代理购电电费':signature+=purchase_fee(text)[0]
            records.append({'id':hashlib.sha256(signature.encode()).hexdigest()[:24], 'hash':sha,
                'filename':filename or path.name,'pages':list(range(start+1,end+1)), 'name':name,'account':account,
                'start':str(first) if first else None,'end':str(last) if last else None,
                'month':first.strftime('%Y-%m') if first else '待核对','period_no':pn[1].strip() if pn else '',
                **vals,'purchase_fee_kind':purchase_fee(text)[0],'buckets':qs,'meters':meters,'evidence':evidence,'issues':sorted(set(issues)),
                'warnings':warnings,'parser_revision':PARSER_REVISION,'removed_rotated_chars':rotated,
                'raw_text':text,'filtered_text':'\n'.join(all_filtered)})
    return json.loads(dump(records))

def dec(v):return D(v) if v is not None else None

def aggregate(records):
    groups=defaultdict(list);seen=set()
    for r in records:
        if r['id'] in seen:continue
        seen.add(r['id']);groups[(r['account'],r['month'])].append(r)
    result=[]
    for (account,month),rs in sorted(groups.items()):
        issues=[x for r in rs for x in r['issues']]
        if len({r['name'] for r in rs})>1:issues.append('同一户号出现不同户名，待核对')
        if len({r.get('purchase_fee_kind','代理购电电费') for r in rs})>1:issues.append('同月账单购电费用口径不同，未自动混合采用')
        reason='单张账单'
        if len(rs)==1 and any(prior_deduction(m) for m in rs[0]['meters']):
            issues.append('含前期电量扣减，但未找到对应前期账单，月资料可能不全')
        if len(rs)>1:
            # Merge only when a month-end residual explicitly deducts the earlier
            # billed quantities at each matching meter; dates alone never prove it.
            residual=[r for r in rs if any(prior_deduction(m) for m in r['meters'])]
            proven=False
            if len(residual)==1:
                tail=residual[0];early=[r for r in rs if r is not tail]
                changes=defaultdict(D); prior=defaultdict(D)
                for m in tail['meters']:
                    if prior_deduction(m):changes[m['meter']]+=-dec(m['change'])
                for r in early:
                    for m in r['meters']:prior[m['meter']]+=dec(m['billed'])
                proven=(bool(prior) and all(changes[k]==prior[k] for k in set(changes)|set(prior))
                        and all(r['start']==tail['start'] and r['end']<tail['end'] for r in early)
                        and tail['end'] and tail['end'][8:]=='01')
            if proven:reason='分次结算已合并：逐计量点扣减与前期计费电量一致'
            else:issues.append('同月多张账单的增量、累计或更正关系未证实，暂不合并');reason='同月多单待核对'
        qs={k:sum((dec(r['buckets'][k]) for r in rs),D(0)) if all(k in r['buckets'] for r in rs) else None for k in KINDS}
        totals={key:sum((dec(r[key]) for r in rs),D(0)) if all(r[key] is not None for r in rs) else None for key in ['q','agency','bill']}
        valid=not issues
        # Ambiguous multi-bill groups must not expose an asserted monthly sum.
        if len(rs)>1 and '待核对' in reason:totals={k:None for k in totals};qs={k:None for k in qs}
        shares={k:(v/totals['q']*100).quantize(D('.0001'),rounding=ROUND_HALF_UP) if v is not None and totals['q'] else None for k,v in qs.items()}
        partial=not any(r['start'] and r['start'][8:]=='01' and r['end'] and r['end'][8:]=='01' for r in rs)
        result.append({'account':account,'name':rs[0]['name'],'month':month,'bills':[r['id'] for r in rs],
            'count':len(rs),**totals,'buckets':qs,'shares':shares,'issues':sorted(set(issues)),
            'status':'已核对' if valid else '待核对','merge_reason':reason,'partial':partial,
            'baseline_price':(totals['agency']/totals['q']).quantize(D('.000001')) if totals['agency'] is not None and totals['q'] else None})
    return json.loads(dump(result))

class Store:
    def __init__(self,root):
        self.root=Path(root);self.originals=self.root/'originals';self.originals.mkdir(parents=True,exist_ok=True)
        self.db=self.root/'archive.json'
    def load(self):
        return json.loads(self.db.read_text()) if self.db.exists() else {'version':VERSION,'files':[],'records':[]}
    def save(self,data):
        tmp=self.db.with_suffix('.tmp');tmp.write_text(dump(data));tmp.replace(self.db)
    def reprocess_pending(self):
        data=self.load()
        affected={r['hash'] for r in data.get('records',[]) if r.get('parser_revision')!=PARSER_REVISION and
            (any(dec(m['change'])<0 for m in r.get('meters',[])) or any('计量点' in i or '扣减' in i for i in r.get('issues',[])))}
        changed=False
        for sha in sorted(affected):
            path=self.originals/(sha+'.pdf')
            if not path.exists():continue
            previous=[r for r in data['records'] if r['hash']==sha]
            try:new=extract_pdf(path,previous[0]['filename'])
            except Exception:continue  # Retain old evidence and blocking flags on failure.
            data.setdefault('parser_migrations',[]).append({'hash':sha,'revision':PARSER_REVISION,
                'old_issues':[r['issues'] for r in previous],'old_ids':[r['id'] for r in previous],'new_ids':[r['id'] for r in new]})
            data['records']=[r for r in data['records'] if r['hash']!=sha]+new;changed=True
        if changed:
            self.save(data)
        return data
    def upload(self,name,raw):
        suffix=Path(name).suffix.lower()
        if suffix not in ('.pdf','.xls','.xlsx'):raise ValueError('请选择PDF账单或XLS/XLSX曲线表。')
        if suffix=='.pdf' and not raw.startswith(b'%PDF-'):raise ValueError('PDF文件内容无效')
        if len(raw)>30*1024*1024:raise ValueError('单文件限30MB。')
        data=self.load();sha=hashlib.sha256(raw).hexdigest()
        previous=next((f for f in data['files'] if f['hash']==sha),None)
        if previous:
            self.reprocess_pending()
            return {'duplicate':True,'name':name,'accounts':previous.get('accounts',sorted({r['account'] for r in data.get('records',[])+data.get('curve_records',[]) if r['hash']==sha}))}
        target=self.originals/(sha+suffix);target.write_bytes(raw)
        try:
            if suffix=='.pdf':rs=extract_pdf(target,Path(name).name)
            else:
                from curves import extract_curve
                rs=extract_curve(target,Path(name).name)
            error=None
        except Exception as e:
            rs=[];error=f'未自动采用：{e}'
        key='records' if suffix=='.pdf' else 'curve_records'
        existing={r['id'] for r in data.get(key,[])};fresh=[r for r in rs if r['id'] not in existing]
        data.setdefault(key,[]).extend(fresh)
        f={'name':Path(name).name,'hash':sha,'bills':len(rs),'added':len(fresh),'error':error,'suffix':suffix,'kind':'bill' if suffix=='.pdf' else 'curve','accounts':sorted({r['account'] for r in rs})}
        data['files'].append(f);self.save(data);return f
    def report(self,package='rule-full',linkage='10',service_fee='0',pack=None):
        data=self.load(); bill_rows=aggregate(data['records'])
        from curves import curve_months
        curves=curve_months(data.get('curve_records',[]),bill_rows)
        curve_keys={(r['account'],r['month']) for r in curves}
        rows=sorted([dict(r,source_type='bill') for r in bill_rows if (r['account'],r['month']) not in curve_keys]+curves,key=lambda r:(r['account'],r['month']))
        customers=[]
        for account in sorted({r['account'] for r in rows}):
            good=[r for r in rows if r['account']==account and not r['issues']]
            customers.append({'account':account,'verified_months':len(good),'q':str(sum((D(r['q']) for r in good),D(0))),'agency':str(sum((D(r['agency']) for r in good if r['agency'] is not None),D(0)))})
        from pricing import calculate,PACK
        return {**data,'version':VERSION,'archive_version':data.get('version'),'scenario':calculate(rows,linkage,service_fee,package=package,pack=pack or PACK),'customers':customers,'months':rows,'package':package,'pricing_status':'按所提供模板测算',
            'pending':['7、8月按原表日前采购口径，其余月按实时，等待后续业务统一确认','服务费按当前选定套餐计取；佣金与返还尚未纳入'],
            'summary':{'accounts':len({r['account'] for r in rows}),'months':len(rows),'bills':len(data['records']),
                       'review':sum(bool(r['issues']) for r in rows),'merged':sum(r['count']>1 and not r['issues'] for r in bill_rows)}}

def monthly_csv(report):
    buf=io.StringIO(newline='');w=csv.writer(buf)
    w.writerow(['企业','户号','月份','账单数','本期电量(千瓦时)','代理购电电费(元)','本期总电费(元)',*['本期'+k+'电量(千瓦时)' for k in KINDS],*['本期'+k+'占比(%)' for k in KINDS],'核对状态','归集依据','疑点'])
    for r in report['months']:
        vals=[r['name'],r['account'],r['month'],r['count'],r['q'],r['agency'],r['bill'],*[r['buckets'].get(k) for k in KINDS],*[r['shares'].get(k) for k in KINDS],r['status'],r['merge_reason'],'；'.join(r['issues'])]
        w.writerow([("'"+v if isinstance(v,str) and v.startswith(('=','+','-','@')) else v) for v in vals])
    return ('\ufeff'+buf.getvalue()).encode('utf-8')
