"""Fill only N/O in the current blank platform export; preserve all other cells."""
from pathlib import Path
from readers import InputError,file_info,identifier,month,table_with_headers,text,workbook_rows

GENERATED_AUDIT_HEADERS=['客户名称','计量点数','计量点电量MWh','原曲线电量MWh','月结与原曲线差额MWh','分时电费元','调平电费元','封顶前均价元/MWh','封顶价元/MWh','申报均价元/MWh','处理情况','套餐来源']
LEGACY_GENERATED_AUDIT_HEADERS=GENERATED_AUDIT_HEADERS[:3]+['曲线电量MWh','调平电量MWh']+GENERATED_AUDIT_HEADERS[5:]

def apply_template(report,path):
    sheets=workbook_rows(path)
    sheet,start,h,rows=table_with_headers(sheets,[
        "零售用户名称","用户号","计量点ID","月份","计量点用电量","零售用户交易价格"])
    expected=[h["计量点用电量"],h["零售用户交易价格"]]
    if expected != [13,14]:
        raise InputError("本月申报模板的目标列不是N/O，需要核对表头")
    calculated={(r[3],r[4]):r for r in report["rows"]}
    used=set();out=[]
    width=max(len(r) for r in rows)
    for i,source in enumerate(rows[start+1:],start+2):
        if not text(source[h["零售用户名称"]]):
            continue
        if month(source[h["月份"]])!=report["month"]:
            raise InputError("申报模板月份与价格表不一致")
        key=(identifier(source[h["用户号"]]),identifier(source[h["计量点ID"]]))
        if key in used:
            raise InputError("申报模板存在重复计量点")
        used.add(key)
        if key not in calculated:
            raise InputError("申报模板计量点缺少本月电量："+str(i)+"行")
        result=calculated[key]
        if text(source[h["零售用户名称"]])!=result[1]:
            raise InputError("申报模板与电量表的计量点客户名称不一致")
        copied=list(source)+[None]*(width-len(source))
        copied[13],copied[14]=result[13],result[14]
        out.append(copied)
    if used!=set(calculated):
        raise InputError("本月电量表与申报模板的计量点名单不一致")
    report["headers"]=list(rows[start])+[""]*(width-len(rows[start]))
    report["rows"]=out
    report["sheet_name"]=sheet
    report["report_template"]=file_info(path)
    report["template_unchanged_columns"]=[i+1 for i in range(width) if i not in (13,14)]
    extras=[]
    regenerated=[]
    for name,values in sheets.items():
        if name==sheet: continue
        if name=='逐户核对' and values and [text(v) for v in values[0][:12]] in (GENERATED_AUDIT_HEADERS,LEGACY_GENERATED_AUDIT_HEADERS):
            # Our prior diagnostic output is not an input source. Rebuild it from
            # this run; never reuse its historic prices, quantities or decisions.
            regenerated.append(name)
            continue
        if any(text(v) for row in values for v in row):
            raise InputError("申报表附页“"+name+"”有额外内容，需核对新版模板结构，未静默丢弃")
        extras.append(name)
    report["template_empty_sheets"]=extras
    report['template_regenerated_sheets']=regenerated
    return report
