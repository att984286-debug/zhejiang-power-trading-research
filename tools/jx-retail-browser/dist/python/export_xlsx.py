"""Production exporter: explicit value cells; never evaluate source strings."""
from pathlib import Path
import xlsxwriter

def export_report(r,output):
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    with xlsxwriter.Workbook(output,{'strings_to_formulas':False,'strings_to_urls':False}) as w:
        head=w.add_format({'bold':True,'bg_color':'#D9D9D9','text_wrap':True,'valign':'vcenter'})
        normal=w.add_format({'valign':'vcenter','font_size':10})
        num=w.add_format({'num_format':'0.000','bg_color':'#EAF1F7','valign':'vcenter'})
        wrap=w.add_format({'text_wrap':True,'valign':'vcenter','font_size':10})
        def table(name,heads,rows,widths):
            s=w.add_worksheet(name);s.freeze_panes(1,0);s.hide_gridlines(2)
            s.write_row(0,0,heads,head);s.set_row(0,36)
            for col,width in enumerate(widths):s.set_column(col,col,width)
            for i,row in enumerate(rows,1):
                s.set_row(i,42)
                for j,v in enumerate(row):
                    s.write(i,j,v,normal)
            return s
        s=table(r.get('sheet_name','申报结果'),r['headers'],r['rows'],
            [7,43,60,22,23,16,12,14,18,18,15,80,43,20,23,18,17,24,24,24,43])
        for i,row in enumerate(r['rows'],1):
            for j in (13,14):s.write(i,j,row[j],num)
            s.write(i,11,row[11],wrap)
        for name in r.get('template_empty_sheets',[]):w.add_worksheet(name)
        heads=['客户名称','计量点数','计量点电量MWh','原曲线电量MWh','月结与原曲线差额MWh',
            '分时电费元','调平电费元','封顶前均价元/MWh','封顶价元/MWh','申报均价元/MWh','处理情况','套餐来源']
        def n(x):return None if x in (None,'') else float(x)
        rows=[]
        for c in r['customers']:
            a=c.get('calc') or {};f=c.get('fitting')
            note=('本月已核对正差修正；' if f else '')+('已封顶；' if a.get('cap_applied') else '')+a.get('cap_note','')
            rows.append([c['name'],c['meter_count'],n(c['official_q']),n(c.get('original_curve_q',c.get('curve_q'))),
                n(c.get('delta_q')),n(a.get('curve_fee')),n(a.get('balance_fee')),n(a.get('before_cap')),
                n(a.get('cap_price')),n(a.get('price')),c.get('status') or note,c.get('source','')])
        for c in r.get('unmatched_curves',[]):rows.append([c['name'],None,None,n(c['quantity']),None,None,None,None,None,None,c['issue'],''])
        d=table('逐户核对',heads,rows,[43,12,22,22,22,23,21,26,24,24,75,80])
        for i,row in enumerate(rows,1):
            d.set_row(i,54)
            for j in (10,11):d.write(i,j,row[j],wrap)
        b=r.get('batch',{})
        notes=[['计算版本',r.get('engine_version')],['批次',b.get('id')],['资料修订',b.get('revision')],
            ['答案隔离','N/O未参与计算，导出时覆盖'],['取舍','时段价3位，时段费2位，调平费2位，最终单价3位']]
        for role,sha in b.get('selected',{}).items():notes.append([role,b['inputs'][sha]['name']+'；SHA256 '+sha])
        d.set_column(13,13,20);d.set_column(14,14,85)
        for i,row in enumerate(notes):d.write_row(i,13,row,wrap)
    return output
