"""Pure Decimal retail calculations; no answer tables, fitting, AI or target prices."""
from __future__ import annotations

import calendar
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
from readers import InputError, number, text

D = Decimal
VERSION = "1.1.0"
ROUNDING = {"slot_price": 3, "slot_fee": 2, "balance_fee": 2, "final_price": 3}
REPORT_HEADERS = [
    "序号", "零售用户名称", "用电单元名称", "用户号", "计量点ID", "交易类型",
    "时段类型", "月份", "月度合同均价", "用电类别", "电压等级", "比例系数K(%)",
    "代理销售价模式", "计量点用电量", "零售用户交易价格", "代理销售费用",
    "状态", "售电公司提交时间", "出错信息", "交易中心驳回意见",
]


def rounded(x, places):
    return x.quantize(D(10) ** -places, rounding=ROUND_HALF_UP)

def quantity_review(curve_q,official_q):
    delta=official_q-curve_q
    ratio=abs(delta)/official_q if official_q>0 else None
    return {"delta_q":str(delta),"ratio":str(ratio) if ratio is not None else "",
            "large_difference":ratio is not None and ratio>=D(".05") and abs(delta)>=D(2),
            "rule":"结算细则第82条；大差错需核实修正状态，逾期未提供修正另有按调平结算例外"}

def annex5_positive_monthly_projection(q,official_q):
    """Monthly equivalent of a confirmed positive Annex 5 allocation.

    Full precision only. Does not pretend to reproduce grid daily rounding.
    Negative adjustments and zero original curves require their own Annex 5 rules.
    """
    original=sum(q)
    if original<=0 or official_q<=original:
        raise InputError("本口径仅适用于原曲线非零且日累计小于月结的正差分配")
    projected=[v*official_q/original for v in q]
    projected[-1]=official_q-sum(projected[:-1])
    return projected


def parameters(raw):
    result = {}
    for piece in raw.replace("，", ",").split(","):
        if not piece.strip():
            continue
        parts = piece.replace("：", ":").split(":", 1)
        if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
            raise InputError("套餐参数需使用“名称:数值”，并以逗号分隔")
        key, value = (x.strip() for x in parts)
        if key in result:
            raise InputError("套餐参数重复：" + key)
        result[key] = value
    return result


def pct(value):
    return number(text(value).removesuffix("%"), "百分比") / 100


def reference(prices, label):
    label = text(label)
    if label in prices["vectors"]:
        vector=prices["vectors"][label]
        missing=[i+1 for i,v in enumerate(vector) if v is None]
        if missing:
            raw=prices.get("unavailable",{}).get("vectors",{}).get(label,{})
            raise InputError("参考价尚未公布："+label+"；时段"+str(missing[0])+"为"+str(raw.get(missing[0],"待定")))
        return vector
    if label in prices["regular"]:
        return [prices["regular"][label]] * 48
    pending=prices.get("unavailable",{}).get("regular",{})
    if label in pending:
        raise InputError("参考价尚未公布："+label+"；"+str(pending[label]))
    raise InputError("本月价格表没有所选参考价：" + label)


def slot_prices(contract, prices):
    p = parameters(contract["params"])
    mode = contract["mode"]
    if "固定" in mode:
        allowed = {"尖峰固定价", "峰段固定价", "平段固定价", "谷段固定价", "深谷固定价",
                   "联动电量比例", "联动价格", "浮动费价", "执行价格封顶"}
        unknown = set(p) - allowed
        if unknown:
            raise InputError("未支持的套餐参数：" + "、".join(sorted(unknown)))
        a = pct(p["联动电量比例"])
        if not D(0) <= a <= 1:
            raise InputError("联动电量比例应为0—100")
        linked = reference(prices, p["联动价格"]) if a != 0 else [D(0)] * 48
        fee = number(p.get("浮动费价", 0), "浮动费价")
        if fee<0: raise InputError("浮动费价不能为负")
        keys = {"平段": "平段固定价", "谷段": "谷段固定价",
                "深谷": "深谷固定价", "峰段": "峰段固定价", "尖峰": "尖峰固定价"}
        out = []
        for cat, l in zip(prices["categories"], linked):
            if cat not in keys:
                raise InputError("无法识别本月峰平谷类型：" + cat)
            if a == 1:
                b = D(0)
            else:
                if keys[cat] not in p:
                    raise InputError("缺少" + keys[cat])
                b = number(p[keys[cat]], keys[cat])
            out.append((1-a)*b + a*l + fee)
    elif "价差" in mode:
        allowed = {"参考价", "约定价差", "分成比例", "浮动价", "执行价格封顶",
                   "参考价1", "参考价2", "参考价3", "价差分成比例"}
        unknown = set(p) - allowed
        if unknown:
            raise InputError("未支持的套餐参数：" + "、".join(sorted(unknown)))
        triple = any(k in p for k in ("参考价1","参考价2","参考价3"))
        if triple and any(k in p for k in ("参考价","约定价差")):
            raise InputError("三参考价套餐不能同时填写固定约定价差或单参考价")
        ref = reference(prices, p["参考价1"] if triple else p["参考价"])
        b = pct(p["价差分成比例"] if triple else p["分成比例"])
        if not D(0) <= b <= 1:
            raise InputError("分成比例应为0—100")
        fee = number(p.get("浮动价", 0))
        if fee<0: raise InputError("浮动价不能为负")
        if triple:
            r2, r3 = (reference(prices,p["参考价2"]),reference(prices,p["参考价3"])) if b else ([D(0)]*48,[D(0)]*48)
            out = [v-b*(v2-v3)+fee for v,v2,v3 in zip(ref,r2,r3)]
        else:
            spread = number(p["约定价差"])
            if spread<0: raise InputError("约定价差不能为负")
            out = [v-b*spread+fee for v in ref]
    else:
        raise InputError("暂未支持的套餐类型：" + mode)
    return [rounded(v, ROUNDING["slot_price"]) for v in out]


def cap_setting(contract):
    p = parameters(contract["params"])
    raw = contract.get("cap_override") or p.get("执行价格封顶", "")
    if raw and raw not in ("是", "否"):
        raise InputError("执行价格封顶只能填是、否或留空")
    return raw != "否", ("合同明确不执行封顶" if raw == "否" else
                        "合同明确执行封顶" if raw == "是" else "按本次用户确认默认执行封顶")


def compute_customer(q, official_q, contract, prices, cap_factor=None,confirmed_balance_basis=None):
    """Returns auditable quantities and fees, preserving zero vs unavailable."""
    if len(q) != 48:
        raise InputError("客户曲线必须包含48个时段")
    if official_q <= 0:
        raise InputError("客户全月电量为零，无法计算加权均价")
    review=quantity_review(sum(q),official_q)
    if review["large_difference"] and not (isinstance(confirmed_balance_basis,str) and confirmed_balance_basis.strip()):
        percent=rounded(D(review["ratio"])*100,3)
        raise InputError("月结与曲线相差"+review["delta_q"]+"MWh（"+str(percent)+
            "%），达到第82条大差错校核门槛；需修正后曲线，或确认逾期未修正按调平结算的依据")
    points = slot_prices(contract, prices)
    enabled, cap_note = cap_setting(contract)
    factor = number(cap_factor) if cap_factor is not None else (
        D("1.15") if "尖峰" in prices["categories"] else D("1.10"))
    if factor not in (D("1.10"), D("1.15")):
        raise InputError("本版封顶倍数仅支持1.10或1.15")
    fees = [rounded(a*b, 2) for a,b in zip(q, points)]
    curve_q, curve_fee = sum(q), sum(fees)
    delta = official_q-curve_q
    if delta == 0:
        balance_price, balance_fee = None, D("0.00")
    else:
        label = "省内现货实时市场加权平均价"
        balance_price = reference(prices,label)[0]
        balance_fee = rounded(delta*balance_price, 2)
    before = (curve_fee+balance_fee)/official_q
    limit = None
    if enabled:
        label = "市场化用户中长期交易平段合同加权平均价"
        limit = reference(prices,label)[0] * factor
    after = min(before, limit) if enabled else before
    return {
        "curve_q": str(curve_q), "official_q": str(official_q), "delta_q": str(delta),
        "curve_fee": str(curve_fee), "balance_price": str(balance_price) if balance_price is not None else "",
        "balance_fee": str(balance_fee), "before_cap": str(before),
        "cap_factor": str(factor), "cap_price": str(limit) if limit is not None else "",
        "cap_applied": bool(enabled and before > limit), "cap_note": cap_note,
        "price": str(rounded(after, 3)), "final_fee": str(rounded(after*official_q, 2)),
        "slot_prices": list(map(str, points)), "slot_fees": list(map(str, fees)),
        "quantity_review":review,"confirmed_balance_basis":confirmed_balance_basis or "",
    }


def build_report(meters, curves, contracts, prices, *, cap_factor=None,confirmed_balance_bases=None,confirmed_curve_fittings=None):
    grouped = defaultdict(list)
    for m in meters:
        grouped[m["name"]].append(m)
    year, mon = map(int, prices["month"].split("-"))
    expected_days = calendar.monthrange(year, mon)[1]
    customers = []
    for name, records in grouped.items():
        item = {"name": name, "meter_count": len(records),
                "official_q": str(sum(number(x["quantity"]) for x in records)),
                "status": "", "source": "", "contract": contracts.get(name), "calc": None}
        try:
            if name not in curves:
                raise InputError("缺少本月曲线")
            c = curves[name]
            if len(c["dates"]) != expected_days:
                raise InputError(f"曲线只有{len(c['dates'])}天，应为{expected_days}天；需核实是否中途入退市")
            item["curve_q"] = str(sum(c["q"]))
            item["quantity_review"]=quantity_review(sum(c["q"]),number(item["official_q"]))
            item["delta_q"]=item["quantity_review"]["delta_q"]
            item["original_curve_q"]=item["curve_q"]
            if name not in contracts:
                raise InputError("缺少独立来源的有效套餐参数")
            if contracts[name].get("error"):
                raise InputError(contracts[name]["error"])
            item["source"] = contracts[name]["source"]
            if contracts[name].get("continued"):
                item["source"] += "；本次已确认沿用至"+prices["month"]
            q_used=c["q"]
            fitting=(confirmed_curve_fittings or {}).get(name)
            if fitting and item["quantity_review"]["large_difference"]:
                if fitting.get("method")!="annex5_positive_monthly_full_precision" or not fitting.get("basis","").strip():
                    raise InputError("大差错拟合方法或核对依据不完整")
                q_used=annex5_positive_monthly_projection(c["q"],number(item["official_q"]))
                item["fitting"]={**fitting,"original_curve_q":item["curve_q"],
                    "fitted_curve_q":str(sum(q_used)),"fitted_curve":list(map(str,q_used)),
                    "scope":"已核对的本月本户全精度月度等效口径，未模拟逐日取舍"}
                item["source"] += "；"+fitting["basis"]
            item["calc"] = compute_customer(q_used, number(item["official_q"]),
                contracts[name],prices,cap_factor,
                confirmed_balance_basis=(confirmed_balance_bases or {}).get(name))
        except (InputError, KeyError) as e:
            item["status"] = str(e)
        customers.append(item)
    indexed = {c["name"]: c for c in customers}
    rows = []
    for i, meter in enumerate(meters, 1):
        c = indexed[meter["name"]]
        contract = c.get("contract") or {}
        row = [i, meter["name"], meter["unit_name"], meter["uid"], meter["meter"],
               "常规交易", "", prices["month"], None, meter["category"], meter["voltage"],
               contract.get("params", ""), contract.get("mode", ""), float(number(meter["quantity"])),
               float(number(c["calc"]["price"])) if c["calc"] else None,
               0, "", "", "", ""]
        rows.append(row)
    unmatched = [{"name": n, "days": len(c["dates"]),
                  "quantity": str(sum(c["q"])),
                  "issue": "曲线有记录，但本月有效计量点电量表无对应客户；需确认结算归属"}
                 for n,c in curves.items() if n not in grouped]
    return {
        "engine_version": VERSION, "month": prices["month"],
        "rounding": ROUNDING, "headers": REPORT_HEADERS, "rows": rows,
        "customers": customers, "unmatched_curves": unmatched,
        "summary": {"customers": len(customers), "meters": len(meters),
                    "official_q": str(sum(number(x["quantity"]) for x in meters)),
                    "calculated": sum(c["calc"] is not None for c in customers),
                    "pending": sum(c["calc"] is None for c in customers),
                    "unmatched_curves": len(unmatched)},
    }
