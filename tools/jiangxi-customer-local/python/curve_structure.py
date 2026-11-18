"""Display-only curve time-of-use totals; pricing quantities remain untouched."""
from decimal import Decimal as D,InvalidOperation,ROUND_HALF_UP

KINDS=('尖峰','峰','平','谷','深谷')

def summarize_curve(row,pack):
    base={'source_type':'curve','source_label':'曲线计算','account':row['account'],'month':row['month'],
          'q':row['q'],'unit':'kWh','curve_records':row.get('curve_records',[])}
    def pending(reason):
        return {**base,'status':'待确认','buckets':dict.fromkeys(KINDS),'shares':dict.fromkeys(KINDS),'issues':[reason]}
    if row.get('issues') or row.get('partial'):return pending('；'.join(row.get('issues',[])) or '曲线未覆盖完整月份')
    if row['month'][:4]!=str(pack['year']):return pending('缺少该年度已确认的分时划分')
    try:model=pack['months'].get(str(int(row['month'][-2:])))
    except (ValueError,TypeError):model=None
    if not model or len(model['slots'])!=48:return pending('缺少对应月份的48时段划分')
    try:
        values=[D(v) for v in row.get('slots_kwh',[])];q=D(row['q'])
        if len(values)!=48 or not q.is_finite() or q<=0 or any(not v.is_finite() or v<0 for v in values) or sum(values)!=q:
            return pending('曲线48点与月总电量未核对通过')
    except (InvalidOperation,TypeError,ValueError):return pending('曲线电量缺失或无效')
    # Monthly clock-point sums cannot identify holiday-only volumes without an
    # explicitly confirmed date mapping. Never label the whole month as deep valley.
    for rule in model.get('special_allocations',{}).values():
        if any(values[i]!=0 for i in rule['slot_indices']):
            return pending('该月含节假日专属分时，缺少已确认的具体日期，曲线分时占比待确认')
    buckets={k:D(0) for k in KINDS};indices={k:[] for k in KINDS}
    for i,(value,slot) in enumerate(zip(values,model['slots'])):
        kind=slot['kind']
        if kind not in buckets:return pending('存在未确认的时段类别')
        buckets[kind]+=value;indices[kind].append(i)
    if sum(buckets.values())!=q:return pending('分时分类电量合计未与曲线总量核对一致')
    return {**base,'status':'已核对','buckets':{k:str(v) for k,v in buckets.items()},
            'shares':{k:str((v/q*100).quantize(D('.0001'),rounding=ROUND_HALF_UP)) for k,v in buckets.items()},
            'issues':[],'slot_indices':indices,'period_template':pack['id'],
            'basis':'按对应月份模板的半小时时段分类，汇总曲线电量；占比按曲线总电量计算'}
