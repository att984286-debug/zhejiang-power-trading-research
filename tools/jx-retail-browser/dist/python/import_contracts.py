"""Explicitly authorized field whitelist for mixed input/result platform exports.

The user authorized B/D/E/H/L/M as contract inputs on 2026-11-10.
N/O and all cached calculated values are never accessed by this extractor.
"""
from pathlib import Path
import sys

from readers import InputError, file_info, identifier, month, text


ALLOWED_COLUMNS = (1, 3, 4, 7, 11, 12)
ALLOWED_HEADERS = ("零售用户名称", "用户号", "计量点ID", "月份", "比例系数K(%)", "代理销售价模式")


def whitelist_rows(path):
    path = Path(path)
    if path.suffix.lower() == ".xls":
        import xlrd
        w = xlrd.open_workbook(path)
        for s in w.sheets():
            for ri in range(min(s.nrows, 10)):
                selected = [text(s.cell_value(ri,c)) if c<s.ncols else "" for c in ALLOWED_COLUMNS]
                if tuple(selected) == ALLOWED_HEADERS:
                    return [[s.cell_value(i,c) for c in ALLOWED_COLUMNS] for i in range(ri+1,s.nrows)]
    elif path.suffix.lower() == ".xlsx":
        from openpyxl import load_workbook
        w = load_workbook(path, read_only=True, data_only=True)
        try:
            for s in w:
                found=False;rows=[]
                # Streaming XLSX exports may omit the optional dimension record.
                # Bound columns at M so neither N nor O is yielded to this reader.
                for ri,row in enumerate(s.iter_rows(max_col=13,values_only=True),1):
                    selected=[row[c] if c<len(row) else None for c in ALLOWED_COLUMNS]
                    if found:rows.append(selected)
                    elif tuple(text(v) for v in selected)==ALLOWED_HEADERS:found=True
                    elif ri>=10:break
                if found:return rows
        finally:
            w.close()
    raise InputError("未找到已授权的套餐字段B/D/E/H/L/M")


def extract(path, confirmed_through=None):
    grouped = {}
    months = set()
    for name,uid,meter,m,params,mode in whitelist_rows(path):
        name,params,mode=text(name),text(params),text(mode)
        if not name:
            continue
        m=month(m)
        months.add(m)
        identifier(uid);identifier(meter)
        if name in grouped and grouped[name] != (params,mode,m):
            raise InputError(name+"在同一客户下存在不同套餐，需要按合同组分别提供曲线")
        grouped[name]=(params,mode,m)
    if len(months)!=1:
        raise InputError("套餐导入文件需为单一月份")
    snap=next(iter(months))
    end=month(confirmed_through) if confirmed_through else snap
    if end<snap:
        raise InputError("确认适用月份早于套餐快照月份")
    period=("本月套餐快照"+snap if end==snap else "用户确认存量套餐延续至"+end)
    source="白名单套餐输入："+Path(path).name+"，仅B/D/E/H/L/M；N/O隔离；"+period
    rows=[]
    for name,(params,mode,m) in sorted(grouped.items()):
        # Preserve explicit exceptions; absence defaults to cap by user confirmation.
        pars=dict(x.replace("：",":").split(":",1) for x in params.replace("，",",").split(",") if ":" in x or "：" in x)
        rows.append([name,snap,end,mode,params,pars.get("执行价格封顶","是"),source])
    return {"kind":"contracts","rows":rows,"provenance":{
        **file_info(path),"allowed_columns":["B","D","E","H","L","M"],
        "blocked_columns":["N","O"],"confirmed_through":end,
        "authorization":"用户2026-11-10明确授权仅提取套餐输入，答案仅作计算后比对",
    }}


def current_contracts(path, requested_month):
    """Only this month's authorized inputs; differing contract groups stay pending."""
    contracts, errors = {}, {}
    for name,uid,meter,m,params,mode in whitelist_rows(path):
        name,params,mode=text(name),text(params),text(mode)
        if not name:
            continue
        if month(m)!=requested_month:
            raise InputError("申报表套餐月份不一致")
        identifier(uid); identifier(meter)
        if not params or not mode:
            errors[name]="本月申报表缺少套餐参数或套餐类型"
            continue
        c={"mode":mode,"params":params,"start":requested_month,"end":requested_month,
           "source":"白名单套餐输入："+Path(path).name+"；本月L/M；N/O未用于计算",
           "cap_override":"","continued":False}
        if name in contracts and contracts[name]["params"]!=params or name in contracts and contracts[name]["mode"]!=mode:
            errors[name]="同一客户有不同套餐合同组，当前客户汇总曲线无法分摊；需合同组曲线"
        contracts[name]=c
    for name in errors:
        contracts[name]={"error":errors[name],"source":str(path)}
    return contracts
