import json,hashlib,copy
from pathlib import Path
from readers import InputError,read_prices,read_curves,read_meters,file_info
from file_classifier import identify,ROLES
from import_contracts import current_contracts,whitelist_rows
from readers import identifier
from engine import build_report
from report_template import apply_template
from export_xlsx import export_report

FILES={};SELECTED={};DECISIONS={};LAST=None
def inspect_files(paths):
    global LAST
    notices=[]
    for path,name in paths:
        try:
            f=identify(path);f['name']=name
            if FILES and f['month']!=next(iter(FILES.values()))['month']:raise InputError('不同月份请先新建批次')
            sha=f['sha256']
            if sha in FILES:continue
            FILES[sha]=f
            for role in f['roles']:
                candidates=[k for k,v in FILES.items() if role in v['roles']]
                SELECTED[role]=sha if len(candidates)==1 else None
            LAST=None
        except Exception as e:notices.append(name+'：'+str(e))
    return state(notices)
def state(notices=[]):
    return dict(files=list(FILES.values()),selected=SELECTED,notices=notices,roles=ROLES,
        month=next(iter(FILES.values()))['month'] if FILES else '',
        decisions=[{'name':k,'basis':v['basis'],'active':v['inputs']==SELECTED} for k,v in DECISIONS.items()])
def choose(choices):
    global LAST
    for role,sha in choices.items():
        if sha not in FILES or role not in FILES[sha]['roles']:raise InputError('无效的文件选择')
        SELECTED[role]=sha
    LAST=None
    return state()
def calculate():
    global LAST
    missing=[v for k,v in ROLES.items() if not SELECTED.get(k)]
    if missing:raise InputError('待补充或选择：'+'、'.join(missing))
    paths={k:Path(FILES[v]['path']) for k,v in SELECTED.items()}
    p=read_prices(paths['prices']);m=p['month']
    c=current_contracts(paths['report_template'],m)
    fits={k:{'method':d['method'],'basis':d['basis']} for k,d in DECISIONS.items() if d['inputs']==SELECTED and d['method']!='overdue_balance'}
    balances={k:d['basis'] for k,d in DECISIONS.items() if d['inputs']==SELECTED and d['method']=='overdue_balance'}
    template_inputs=whitelist_rows(paths['report_template'])
    names={r[0] for r in template_inputs if r[0]}
    keys={(identifier(r[1]),identifier(r[2])) for r in template_inputs if r[0]}
    # A rejected-only template can contain only some meters of a customer.
    # Price must still use ALL that customer's meters, never just rejected ones.
    all_meters=read_meters(paths['meters'],m)
    all_names={r['name'] for r in all_meters}
    meters=[r for r in all_meters if r['name'] in names]
    report=build_report(meters,read_curves(paths['curves'],m),c,p,
        confirmed_curve_fittings=fits,confirmed_balance_bases=balances)
    report['rows']=[r for r in report['rows'] if (r[3],r[4]) in keys]
    report=apply_template(report,paths['report_template'])
    report['unmatched_curves']=[r for r in report['unmatched_curves'] if r['name'] not in all_names]
    report['summary']['unmatched_curves']=len(report['unmatched_curves'])
    report['summary']['meters']=len(report['rows'])
    from decimal import Decimal
    report['summary']['official_q']=str(sum(Decimal(str(r[13])) for r in report['rows']))
    report['batch']={'id':m+'_浏览器本地计算','revision':1,'version':'4.0.0',
        'selected':SELECTED.copy(),'inputs':FILES,'answer_policy':'N/O隔离，本地计算；均价按客户全部计量点计算，仅回填申报名单'}
    export_report(report,'/result.xlsx')
    # Independently reread saved XLSX and verify every output/template cell.
    from openpyxl import load_workbook
    w=load_workbook('/result.xlsx',read_only=True,data_only=True)
    rows=list(w[report['sheet_name']].values);w.close()
    expected=[report['headers'],*report['rows']]
    assert len(rows)==len(expected),'导出行数不一致'
    for a,b in zip(rows,expected):
        assert all(x==y or x in (None,'') and y in (None,'') for x,y in zip(a,b)),'导出字段不一致'
    LAST=report
    return dict(summary=report['summary'],month=m,
        customers=[{'name':x['name'],'status':x['status'],'price':x['calc']['price'] if x['calc'] else None,'large':x.get('quantity_review',{}).get('large_difference',False)} for x in report['customers']],
        unmatched=report['unmatched_curves'])
def decide(name,method,basis):
    if not basis.strip():raise InputError('需要本月本户已确认的修正依据')
    if method not in ('annex5_positive_monthly_full_precision','overdue_balance'):raise InputError('未知修正方式')
    if not LAST or not any(x['name']==name and x.get('quantity_review',{}).get('large_difference') for x in LAST['customers']):raise InputError('仅能处理本次已识别的大差错客户')
    DECISIONS[name]={'method':method,'basis':basis.strip(),'inputs':SELECTED.copy()}
    return state()
def reset():
    global LAST
    FILES.clear();SELECTED.clear();DECISIONS.clear();LAST=None
    return state()
