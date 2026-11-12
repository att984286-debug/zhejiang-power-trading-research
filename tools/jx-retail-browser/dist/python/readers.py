"""Read business inputs. Completed reporting workbooks are never input sources."""
from __future__ import annotations

import calendar
import hashlib
import json
import re
import sys
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "vendor"))


class InputError(ValueError):
    pass


def text(x):
    return ("" if x is None else str(x)).replace("\ufeff", "").replace("\n", "").replace("\r", "").strip()


def identifier(x):
    if x is None or x == "":
        raise InputError("用户号或计量点ID为空")
    if isinstance(x, float):
        if not x.is_integer() or abs(x) >= 10**15:
            raise InputError("标识符以数值保存且可能失真，请从平台重新导出为文本")
        return str(int(x))
    return str(x).strip()


def number(x, label="数值"):
    if x is None or isinstance(x, bool) or text(x) == "":
        raise InputError(f"{label}缺失")
    try:
        result = Decimal(str(x).replace(",", "").strip())
    except InvalidOperation as e:
        raise InputError(f"{label}不是有效数字：{x}") from e
    if not result.is_finite():
        raise InputError(f"{label}不是有限数字")
    return result


def month(x):
    if isinstance(x, (datetime, date)):
        return x.strftime("%Y-%m")
    match = re.fullmatch(r"(\d{4})[-年/.](\d{1,2})(?:月)?", text(x))
    if not match or not 1 <= int(match[2]) <= 12:
        raise InputError(f"月份格式应为YYYY-MM：{x}")
    return f"{match[1]}-{int(match[2]):02}"


def file_info(path):
    p = Path(path).resolve()
    return {"name": p.name, "path": str(p), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}


def workbook_rows(path):
    p = Path(path)
    if p.stat().st_size>50*1024*1024:
        raise InputError('单文件超过50MB，请分月或简化导出')
    if p.suffix.lower() == ".xls":
        import xlrd
        w = xlrd.open_workbook(p)
        return {s.name: [[xlrd.xldate_as_datetime(c.value,w.datemode)
                         if c.ctype==xlrd.XL_CELL_DATE else c.value for c in s.row(i)]
                        for i in range(s.nrows)] for s in w.sheets()}
    if p.suffix.lower() == ".xlsx":
        from zipfile import ZipFile
        with ZipFile(p) as archive:
            if len(archive.infolist())>10000 or sum(z.file_size for z in archive.infolist())>512*1024*1024:
                raise InputError('工作簿解压体积过大，请重新导出')
        from openpyxl import load_workbook
        w = load_workbook(p, data_only=True, read_only=True)
        try:
            if any((s.max_row or 0)>100000 or (s.max_column or 0)>256 for s in w):
                raise InputError('工作簿行列超出本助手处理范围')
            return {s.title: [list(r) for r in s.iter_rows(values_only=True)] for s in w}
        finally:
            w.close()
    raise InputError(f"不支持的表格格式：{p.suffix}；请使用xls或xlsx")


def table_with_headers(sheets, required):
    for sheet, rows in sheets.items():
        for i, row in enumerate(rows[:25]):
            headers = {text(v): c for c, v in enumerate(row) if text(v)}
            if all(k in headers for k in required):
                return sheet, i, headers, rows
    raise InputError("找不到表头：" + "、".join(required))


def reject_answer_table(sheets):
    """Reject entire completed reports, including their tempting parameter columns."""
    for rows in sheets.values():
        for i, row in enumerate(rows[:25]):
            heads = {text(v): j for j, v in enumerate(row)}
            if "零售用户交易价格" in heads:
                c = heads["零售用户交易价格"]
                if any(len(r) > c and r[c] is not None and text(r[c]) != "" for r in rows[i+1:]):
                    raise InputError("已填申报结果表只允许交给独立比对器，不能作为计算或套餐来源")


def read_meters(path, requested_month):
    sheets = workbook_rows(path)
    reject_answer_table(sheets)
    sheet, start, h, rows = table_with_headers(
        sheets, ["用户号", "计量点ID", "电量月份", "本月电量"])
    name_col = h.get("代理零售用户名称", h.get("零售用户名称"))
    if name_col is None:
        raise InputError("电量表缺少客户名称")
    records, seen = [], set()
    for i, r in enumerate(rows[start+1:], start+2):
        if not text(r[h["电量月份"]]):
            continue
        if month(r[h["电量月份"]]) != requested_month:
            raise InputError(f"电量表第{i}行月份与价格表月份不一致")
        auth = h.get("用户是否授权查询")
        if auth is not None and text(r[auth]) != "已授权":
            continue
        name = text(r[name_col])
        if not name or name == "合计":
            continue
        key = (identifier(r[h["用户号"]]), identifier(r[h["计量点ID"]]))
        if key in seen:
            raise InputError(f"重复计量点：{name}，第{i}行")
        seen.add(key)
        q = number(r[h["本月电量"]], f"电量表第{i}行电量")
        if q < 0:
            raise InputError(f"电量表第{i}行出现负电量，需要明确更正电量处理口径")
        def opt(label):
            return text(r[h[label]]) if label in h else ""
        records.append({
            "name": name, "uid": key[0], "meter": key[1], "quantity": str(q),
            "unit_name": opt("用电单元名称"), "category": opt("用电类别"),
            "voltage": opt("电压等级"), "source": f"{Path(path).name}/{sheet}/{i}",
        })
    if not records:
        raise InputError("电量表没有本月有效记录")
    return records


def pdf_curve_records(path):
    """Reconstruct Excel horizontal print bands using repeated text baselines.

    No fixed page count, customer count or answer-derived row list is used.
    """
    from pypdf import PdfReader
    pdf = PdfReader(path)
    pages = []
    for pi, p in enumerate(pdf.pages):
        grouped = defaultdict(list)
        def visit(t, cm, tm, font, size):
            t = t.strip()
            if t:
                grouped[round(tm[5], 3)].append(t)
        p.extract_text(visitor_text=visit)
        groups = []
        for y, items in sorted(grouped.items(), reverse=True):
            if any("时段" in z and "电量" in z for z in items):
                continue
            ds = [i for i, z in enumerate(items) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", z)]
            if ds:
                if len(ds) != 1:
                    raise InputError(f"PDF第{pi+1}页日期定位不唯一")
                i = ds[0]
                groups.append({"name": "".join(items[:i]), "date": items[i],
                               "q": [number(z, "PDF曲线电量") for z in items[i+1:]],
                               "y": y, "page": pi+1})
            else:
                try:
                    qs = [number(z) for z in items]
                except InputError:
                    continue
                if qs:
                    groups.append({"q": qs, "y": y, "page": pi+1})
        if not groups:
            raise InputError(f"PDF第{pi+1}页无法还原曲线；请优先提供原Excel")
        pages.append(groups)
    flags = [all("name" in r for r in p) for p in pages]
    lead_pages = 0
    while lead_pages < len(flags) and flags[lead_pages]:
        lead_pages += 1
    if lead_pages == 0 or any(flags[lead_pages:]) or len(pages) % lead_pages:
        raise InputError("PDF分页结构不受支持，请提供原Excel")
    bands = []
    for j in range(0, len(pages), lead_pages):
        band = [r for page in pages[j:j+lead_pages] for r in page]
        bands.append(band)
    size = len(bands[0])
    if any(len(b) != size for b in bands):
        raise InputError("PDF横向分页记录数不一致")
    records = []
    for i, first in enumerate(bands[0]):
        qs = list(first["q"])
        for b in bands[1:]:
            other = b[i]
            if other["y"] != first["y"] or (other["page"]-1) % lead_pages != (first["page"]-1) % lead_pages:
                raise InputError("PDF横向分页行位置不一致")
            qs += other["q"]
        if len(qs) != 48:
            raise InputError("PDF每日曲线不是48点")
        records.append({"name": first["name"], "date": first["date"], "q": qs})
    return records


def read_curves(path, requested_month):
    p = Path(path)
    if p.suffix.lower() == ".pdf":
        records = pdf_curve_records(p)
    else:
        sheets = workbook_rows(p)
        reject_answer_table(sheets)
        candidates = []
        for sn, rows in sheets.items():
            for i, r in enumerate(rows[:25]):
                hs = [text(x) for x in r]
                slots = [j for j, v in enumerate(hs) if re.search(r"时段\s*\d+.*电量", v)]
                if len(slots) == 48:
                    names = [j for j, v in enumerate(hs) if v in ("客户名称", "电力用户名称", "用户名称", "零售用户名称", "代理零售用户名称", "名称")]
                    dates = [j for j, v in enumerate(hs) if "日期" in v or v in ("时间", "抄表时间")]
                    if not names or not dates:
                        # Supplied platform export has customer and date in the first two columns.
                        if slots == list(range(2, 50)):
                            names, dates = [0], [1]
                        else:
                            raise InputError("曲线表无法确定客户名称或日期列")
                    slots.sort(key=lambda j:int(re.search(r"时段\s*(\d+)",hs[j])[1]))
                    if [int(re.search(r"时段\s*(\d+)",hs[j])[1]) for j in slots]!=list(range(1,49)):
                        raise InputError("曲线时段必须完整覆盖1—48")
                    candidates.append((sn, rows, i, names[0], dates[0], slots))
        if len(candidates) != 1:
            raise InputError("应有且仅有一张48点曲线表")
        sn, rows, head, nc, dc, slots = candidates[0]
        records = []
        for ri, r in enumerate(rows[head+1:], head+2):
            if not text(r[nc]):
                continue
            d = r[dc]
            ds = d.strftime("%Y-%m-%d") if isinstance(d, (datetime, date)) else text(d)[:10]
            records.append({"name": text(r[nc]), "date": ds,
                            "q": [number(r[j], f"曲线第{ri}行时段{k+1}") for k,j in enumerate(slots)]})
    grouped = {}
    for r in records:
        try:
            d = date.fromisoformat(r["date"])
        except ValueError as e:
            raise InputError("曲线日期无效：" + r["date"]) from e
        if d.strftime("%Y-%m") != requested_month:
            raise InputError("曲线表包含其他月份的数据")
        g = grouped.setdefault(r["name"], {"q": [Decimal(0)]*48, "dates": set()})
        if d in g["dates"]:
            raise InputError(f"客户{name if (name := r['name']) else ''}的{d}曲线重复")
        if any(q < 0 for q in r["q"]):
            raise InputError(f"{r['name']}曲线含负电量，需明确修正口径")
        g["dates"].add(d)
        g["q"] = [a+b for a,b in zip(g["q"], r["q"])]
    return grouped


def read_prices(path):
    sheets = workbook_rows(path)
    reject_answer_table(sheets)
    sn, start, h, rows = table_with_headers(sheets, ["月份", "价格类型", "价格"])
    regular, months, seen = {}, set(), set()
    unavailable={"regular":{},"vectors":{}}
    for r in rows[start+1:]:
        if not text(r[h["价格类型"]]):
            continue
        months.add(month(r[h["月份"]]))
        label = text(r[h["价格类型"]])
        if label in seen:
            raise InputError("常规价格指标重复：" + label)
        seen.add(label)
        try:
            regular[label] = number(r[h["价格"]], label)
        except InputError:
            # A published workbook can legitimately contain unused, pending indicators.
            unavailable["regular"][label]=text(r[h["价格"]]) or "空白"
    if len(months) != 1:
        raise InputError("价格定义表必须只包含一个月份")
    m = next(iter(months))
    slot_candidates=[rows for rows in sheets.values() if any(
        "时段" in [text(v) for v in r] and "月份" in [text(v) for v in r]
        and any("时段类型" in text(v) for v in r) for r in rows[:25])]
    if len(slot_candidates)!=1:
        raise InputError("价格表应有且仅有一张含月份、时段、时段类型的分时价格表")
    slot_sheet = slot_candidates[0]
    header_i = next((i for i,r in enumerate(slot_sheet[:25]) if "时段" in [text(v) for v in r]), None)
    if header_i is None:
        raise InputError("找不到分时价格表头")
    headers = [text(v) for v in slot_sheet[header_i]]
    sc = headers.index("时段")
    mc = headers.index("月份")
    catc = next((j for j,v in enumerate(headers) if "时段类型" in v), None)
    if catc is None:
        raise InputError("价格表没有峰平谷时段分类")
    values = {}
    for r in slot_sheet[header_i+1:]:
        if not text(r[sc]):
            continue
        k = int(number(r[sc], "时段编号"))
        if k not in range(1,49) or k in values:
            raise InputError("分时价格时段重复或超出1—48")
        if month(r[mc]) != m:
            raise InputError("价格定义月份不一致")
        values[k] = r
    if set(values) != set(range(1,49)):
        raise InputError("分时价格缺少时段，必须完整覆盖1—48")
    vectors = {}
    # All price columns are indexed by exact indicator names, not cached column numbers.
    for j, label in enumerate(headers):
        if label and j not in (mc, sc, catc) and label != "浮动比例":
            if label in vectors:
                raise InputError("分时价格指标重复：" + label)
            vector=[]
            for k in range(1,49):
                try:
                    vector.append(number(values[k][j], f"{label}时段{k}"))
                except InputError:
                    vector.append(None)
                    unavailable["vectors"].setdefault(label,{})[k]=text(values[k][j]) or "空白"
            vectors[label]=vector
    cats = [text(values[k][catc]) for k in range(1,49)]
    return {"month": m, "regular": regular, "vectors": vectors, "categories": cats,"unavailable":unavailable,
            "source": file_info(path)}


def read_contracts(path, requested_month, allow_prior=False):
    sheets = workbook_rows(path)
    reject_answer_table(sheets)
    sn, start, h, rows = table_with_headers(sheets, ["客户名称", "套餐类型", "套餐参数"])
    contracts = {}
    prior = {}
    for ri, r in enumerate(rows[start+1:], start+2):
        name = text(r[h["客户名称"]])
        if not name:
            continue
        params = text(r[h["套餐参数"]])
        if not params:
            continue
        def val(label, default=""):
            return text(r[h[label]]) if label in h else default
        begin = val("生效月份")
        end = val("截止月份")
        if not begin:
            raise InputError(f"套餐第{ri}行需要生效月份")
        expired = bool(end and month(end)<requested_month)
        if month(begin) > requested_month or (expired and not allow_prior):
            continue
        source = val("参数来源")
        if not source:
            raise InputError(f"{name}缺少独立套餐来源说明")
        if (not source.startswith("白名单套餐输入：")
            and any(x in source for x in ("交易价格申报9月", "reconciliation.json", "rounding_candidates"))):
            raise InputError(f"{name}的套餐来源指向结果表或历史回算，禁止使用")
        contract = {
            "mode": val("套餐类型"), "params": params, "source": source,
            "start": month(begin), "end": month(end) if end else "",
            "cap_override": val("执行价格封顶"),
            "continued": expired,
        }
        if expired:
            old=prior.get(name)
            if old and old["end"]==contract["end"]:
                raise InputError(f"{name}存在多个相同截止月的历史套餐")
            if not old or old["end"]<contract["end"]:
                prior[name]=contract
        else:
            if name in contracts:
                raise InputError(f"{name}存在重叠的有效套餐")
            contracts[name]=contract
    for name, contract in prior.items():
        contracts.setdefault(name,contract)
    return contracts
