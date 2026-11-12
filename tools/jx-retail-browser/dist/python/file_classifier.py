"""Content-based monthly input identification. Names are labels, never evidence."""
import re
from datetime import date, datetime
from pathlib import Path
from readers import InputError, file_info, month, text, workbook_rows, pdf_curve_records

ROLES = {"prices":"价格定义表", "report_template":"当月申报表（含套餐）",
         "curves":"全月48点曲线", "meters":"计量点月度电量"}

def identify(path):
    path = Path(path)
    found = {}
    if path.suffix.lower() == ".pdf":
        records = pdf_curve_records(path)
        months = {r["date"][:7] for r in records}
        found["curves"] = months
    else:
        for sheet, rows in workbook_rows(path).items():
            for i, row in enumerate(rows[:25]):
                h = {text(v):j for j,v in enumerate(row) if text(v)}
                role = None
                if {"用户号","计量点ID","电量月份","本月电量"} <= h.keys():
                    role, mc = "meters", h["电量月份"]
                elif {"零售用户名称","用户号","计量点ID","月份","比例系数K(%)","代理销售价模式",
                      "计量点用电量","零售用户交易价格"} <= h.keys():
                    role, mc = "report_template", h["月份"]
                elif {"月份","价格类型","价格"} <= h.keys():
                    role, mc = "prices", h["月份"]
                elif len([s for s in h if re.fullmatch(r"时段\s*\d+.*电量",s)]) == 48:
                    ds = [j for s,j in h.items() if "日期" in s or s in ("时间","抄表时间")]
                    if len(ds) != 1:
                        raise InputError("48点曲线无法唯一识别日期列")
                    role, mc = "curves", ds[0]
                if role:
                    values = set()
                    for r in rows[i+1:]:
                        v = r[mc] if mc < len(r) else None
                        if not text(v):
                            continue
                        if role == "curves":
                            d = v.date() if isinstance(v,datetime) else v
                            if not isinstance(d,date):
                                try: d = date.fromisoformat(text(v)[:10])
                                except ValueError as e: raise InputError("曲线日期无效："+text(v)) from e
                            values.add(d.strftime("%Y-%m"))
                        else:
                            values.add(month(v))
                    if not values:
                        raise InputError(ROLES[role]+"没有可识别的数据月份")
                    found.setdefault(role,set()).update(values)
                    break
    if not found:
        raise InputError("未识别文件内容；支持价格定义、含套餐的申报表、48点曲线、计量点月电量")
    months = set().union(*found.values())
    if len(months) != 1:
        raise InputError("同一文件含多个数据月份："+"、".join(sorted(months))+"；请分别导出")
    return {**file_info(path),"month":next(iter(months)),"roles":sorted(found)}
