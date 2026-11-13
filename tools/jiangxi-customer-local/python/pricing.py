"""Versioned monthly scenario calculation, independent of HTTP/PDF readers."""
import csv,io,json
from decimal import Decimal as D, ROUND_HALF_UP, ROUND_CEILING
from pathlib import Path
PACK=json.loads((Path(__file__).parent/'prices/template_2026.json').read_text())
Z=D(0)

def parameter(value,label,low,high):
 try:v=D(str(value))
 except Exception:raise ValueError(label+'请输入有效数字')
 if not v.is_finite() or not D(low)<=v<=D(high):raise ValueError(label+f'须在{low}至{high}之间')
 return v

def rounded(v,places='0.01'):
 return str(v.quantize(D(places),rounding=ROUND_HALF_UP))

def single(v,places='0.01'):
 value=rounded(v,places)
 # Retain the API fields used by previously saved pages, always equal.
 return {'low':value,'high':value}

def money(v):return v.quantize(D('.01'),rounding=ROUND_HALF_UP)

def compute_month(row,linkage,fee,pack=PACK,package='linkage'):
 base={'account':row['account'],'month':row['month'],'q':row['q'],'source_bills':row['bills'],'source_type':row.get('source_type','bill'),'reconciliation':row.get('reconciliation')}
 def blocked(reason):return {**base,'status':'blocked','reason':reason}
 if row['issues'] or row['partial']:return blocked('；'.join(row['issues']) or '不足整月，暂不作为完整月份测算')
 if row['month'][:4]!=str(pack['year']):return blocked('未内置此年度价格，未跨年套价')
 model=pack['months'].get(str(int(row['month'][-2:])))
 if not model:return blocked('缺少对应月份价格')
 slots=model['slots'];q=D(row['q']);qs={k:D(v) for k,v in row['buckets'].items()}
 if q<=0 or any(v<0 for v in qs.values()) or (row.get('source_type')!='curve' and sum(qs.values())!=q):return blocked('电量为零、负数或分时总量不平，待核对')
 l=linkage/100;rw=D(model['rolling_weight']);sw=D(model['spot_weight'])
 if len(slots)!=48 or rw+sw!=1:raise ValueError('价格包时段或采购权重错误')
 prices=[]
 for s in slots:
  sell=D(s['reference'])*(1-l)+l*D(s['rt'])+fee*(1 if package=='rule-full' else 1-l)
  if package=='rule-full':sell=D(rounded(sell,'.001'))
  cost=rw*D(s['rolling'])+sw*D(s[model['cost_spot']])
  prices.append((sell,cost))
 revenue=cost_total=allocated=Z;details=[];allocation_rules=[]
 items=list(qs.items()) if row.get('source_type')!='curve' else [(str(i),D(v)) for i,v in enumerate(row['slots_kwh'])]
 if row.get('source_type')=='curve' and (len(items)!=48 or any(v<0 for _,v in items) or sum(v for _,v in items)!=q):return blocked('曲线48点总量不平')
 for kind,volume in items:
  if volume==0:continue
  is_curve=row.get('source_type')=='curve'
  special=None if is_curve else model.get('special_allocations',{}).get(kind)
  ids=[int(kind)] if is_curve else special['slot_indices'] if special else [i for i,s in enumerate(slots) if s['kind']==kind]
  if is_curve:kind=slots[ids[0]]['kind']
  if not ids:return blocked(kind+'电量没有已确认的时段对应关系，未使用全天极值代算')
  if len(set(ids))!=len(ids) or any(not 0<=i<48 for i in ids):raise ValueError('特殊分时时段配置错误')
  scope='实际逐日曲线同一时段求和，未按峰平谷均摊' if is_curve else special['day_scope'] if special else '按该月常规分时划分'
  allocation_rules.append({'kind':kind,'q':str(volume),'slots':ids,'day_scope':scope,'half_hour_count':len(ids)})
  chunk=volume/len(ids);used=Z
  for n,i in enumerate(ids):
   energy=volume-used if n==len(ids)-1 else chunk;used+=energy;allocated+=energy
   p=prices[i];income=energy*p[0]/1000
   if package=='rule-full':income=money(income)
   revenue+=income;cost_total+=energy*p[1]/1000
   s=slots[i];label=s['label'].split('(')[0]+f'({kind}，{scope})' if special else s['label']
   detail_scope=scope
   if not special and not is_curve:
    for rule in model.get('special_allocations',{}).values():
     if i in rule['slot_indices'] and kind==rule.get('ordinary_kind'):detail_scope='春节法定节假日以外日期'
   details.append({'slot':i,'label':label,'source_label':s.get('source_label',s['label']),'kind':kind,'day_scope':detail_scope,'q':str(energy),
    'sell_yuan_mwh':str(p[0]),'cost_yuan_mwh':str(p[1]),'revenue':str(income),'cost':str(energy*p[1]/1000),
    'cells':s['cells'],'time_cell':s['time_cell']})
 if abs(allocated-q)>D('1e-18'):raise ValueError('分时电量未完整进入计算')
 profit=money(revenue)-money(cost_total)
 rule_note='春节法定节假日深谷12:00-14:00；平日保留原平段；使用月度时段均价' if model.get('special_allocations') else '9月深谷12:00-14:00，已修正原模板漏标' if row['month'].endswith('-09') else ''
 if row.get('source_type')=='curve':rule_note='真实48点曲线×月度时段价格；'+row['reconciliation']['note']
 return {**base,'status':'exact','reason':rule_note,'revenue':single(revenue),'cost':single(cost_total),'profit':single(profit),
  'sell_price':single(revenue/q,'.000001'),'cost_price':single(cost_total/q,'.000001'),'margin_li':single((revenue-cost_total)*1000/q,'.0001'),
  'cost_spot':model['cost_spot'],'unmapped':[],'allocated_q':str(allocated),'details':details,'allocation_rules':allocation_rules,
  'raw_totals':{'revenue':[str(revenue)]*2,'cost':[str(cost_total)]*2,'profit':[str(revenue-cost_total)]*2}}

def break_even_fee(rows,linkage,current_fee,package='linkage',inputs=None,pack=PACK):
 coefficient=D(1) if package=='rule-full' else 1-linkage/100
 if coefficient==0 or not rows:return None
 bases=[(D(r['raw_totals']['revenue'][0])-current_fee*D(r['q'])*coefficient/1000,
         money(D(r['raw_totals']['cost'][0])),D(r['q'])*coefficient/1000) for r in rows]
 def profit_at(cents):
  fee=D(cents)/100
  if package=='rule-full':return sum((D(compute_month(r,linkage,fee,pack,package)['profit']['low']) for r in inputs),Z)
  return sum((money(revenue+fee*k)-cost for revenue,cost,k in bases),Z)
 if profit_at(0)>=0:return single(Z)
 raw_gap=sum((cost-revenue for revenue,cost,k in bases),Z);slope=sum((k for _,_,k in bases),Z)
 hi=max(1,int((raw_gap/slope*100).to_integral_value(rounding=ROUND_CEILING)));lo=0
 while profit_at(hi)<0:hi=hi*2+1
 while hi-lo>1:
  mid=(hi+lo)//2
  if profit_at(mid)>=0:hi=mid
  else:lo=mid
 return single(D(hi)/100)

def calculate(months,linkage='10',service_fee='0',pack=PACK,package='linkage'):
 if package not in ('linkage','rule-full'):raise ValueError('不支持的套餐预设')
 l=parameter(linkage,'联动比例','0','100');f=parameter(service_fee,'服务费','-100','100')
 if package=='rule-full' and f<0:raise ValueError('规则全电量浮动费不能为负')
 result=[compute_month(r,l,f,pack,package) for r in months];customers=[]
 for account in sorted({r['account'] for r in months}):
  input_rows=[r for r in months if r['account']==account];rows=[r for r in result if r['account']==account];usable=[r for r in rows if r['status']=='exact']
  total_q=sum((D(r['q']) for r in usable),Z)
  totals={k:sum((D(r[k]['low']) for r in usable),Z) for k in ['revenue','cost','profit']};profit=totals['profit']
  if not usable:verdict='资料不足，暂不能测算';tone='neutral'
  elif profit<0:verdict='当前方案测算亏损，建议调价后再评估';tone='loss'
  elif profit>0:verdict='观察期测算为正，有继续谈价空间';tone='gain'
  else:verdict='观察期测算打平，需留意其他费用';tone='neutral'
  years={r['month'][:4] for r in rows};observed={int(r['month'][-2:]) for r in rows if r['month'][-2:].isdigit()}
  full_year=len(years)==1 and observed==set(range(1,13)) and len(usable)==12
  customers.append({'account':account,'name':input_rows[0]['name'],'months':[r['month'] for r in rows],'available':len(usable),'provided':len(rows),'ranges':0,'blocked':len(rows)-len(usable),
   'q':str(total_q),**{k:single(v) if usable else None for k,v in totals.items()},
   'weighted_sell':single(totals['revenue']/total_q,'.000001') if total_q else None,
   'weighted_cost':single(totals['cost']/total_q,'.000001') if total_q else None,
   'loss_months':sum(D(r['profit']['low'])<0 for r in usable),'uncertain_months':0,
   'worst':min(({'month':r['month'],'profit':r['profit']} for r in usable),key=lambda x:D(x['profit']['low']),default=None),
   'break_even_fee':break_even_fee(usable,l,f,package,[r for r in input_rows if any(x['month']==r['month'] for x in usable)],pack),'verdict':verdict,'tone':tone,'full_year':full_year})
 return {'params':{'linkage':str(l),'service_fee':str(f),'service_unit':'厘/度（等值元/兆瓦时）','package':package},'price_pack':{k:v for k,v in pack.items() if k!='months'},'customers':customers,'months':result,
 'notes':[('规则联动预设：参考固定价×(1−联动比例)+实时联动价×联动比例+全电量浮动费价。依据本地4.0修订版零售附件3；当前无封顶、考核条款输入，尚未计入。' if package=='rule-full' else '沿用原模板收费方式，以下为非联动部分加价。'),('当前比例超出4.0普通工商业10%—20%预设范围，仅作敏感性试算，不能直接作为合同报价。' if package=='rule-full' and not D(10)<=l<=D(20) else '当前为拟签方案回看，正式报价须绑定适用年份和最终合同。'),'曲线采用用户确认的MWh单位、时段1为00:00—00:30；导入转千瓦时一次，不再乘0.5。曲线按原分布求和，账单才按分时均摊。未提供最终月结电量时，调平费为未核算而不是已确认零。',('全电量浮动费按元/兆瓦时加到联动后的单价上，月总费用等于费价×全电量MWh。' if package=='rule-full' else '售电单价=(参考价+服务费)×(1−联动比例)+实时价×联动比例；服务费仅作用于非联动部分。'),'采购成本沿用原表：80%滚撮+20%现货，7、8月现货取日前，其余月份取实时。',
 '按各类月度电量在已确认的对应时段均摊；各类电量来自账单，不是实测48点负荷。',
 '9月12:00-14:00已由谷改为深谷，谷10段、深谷4段，各类电量完整进入收入和成本。',
 '2月普通日期12:00-14:00仍为平段，仅春节法定节假日为深谷。账单深谷电量单独分摊到这4个半小时；普通日平量保留，未把整个2月改成深谷。',
 '2月沿用所提供的月度48点均价，没有节假日逐日价格；平段和节假日深谷是不同日期的独立电量，钟点可相同，电量不重复。',
 '元/兆瓦时×千瓦时÷1000=元；月收入、成本各取两位后相减，合计按月度展示金额加总。尚未扣佣金、返还等其他费用。',
 '部分参考价及滚撮曲线多月相同，11、12月现货曲线与3月相同。沿用原表情景假设，不声称为真实已实现行情。',
 '分时修正依据：2026-11-13用户向师傅核实的业务口径；原Excel和原始账单保留。历史回看不代表2027年实际收益，不足12个月不外推全年。']}

def scenario_csv(report,account=None):
 s=io.StringIO(newline='');w=csv.writer(s);p=report['scenario'];params=p['params'];source=p['price_pack']
 w.writerow(['套餐',params.get('package','linkage'),'联动比例(%)',params['linkage'],'服务费(厘/度)',params['service_fee'],'价格包',source['id'],'来源SHA256',source['source_sha256']])
 w.writerow(['说明','售购毛差未扣佣金等；9月深谷12-14，2月仅春节法定假日深谷12-14，使用月度均价，不外推全年'])
 w.writerow(['企业','户号','月份','电量(千瓦时)','售电均价(元/度)','采购成本均价(元/度)','每度赚亏(厘/度)','售电收入(元)','采购成本(元)','本月赚亏(元)','状态','说明','电量来源','月结电量核对'])
 names={r['account']:r['name'] for r in p['customers']}
 def safe_name(n):return "'"+n if n.startswith(('=','+','-','@')) else n
 for r in p['months']:
  if account and r['account']!=account:continue
  vals=[safe_name(names[r['account']]),r['account'],r['month'],r['q']]
  vals += [r.get(k,{}).get('low') for k in ['sell_price','cost_price','margin_li','revenue','cost','profit']]
  w.writerow(vals+['已计算' if r['status']=='exact' else '未纳入',r['reason'],r.get('source_type','bill'),(r.get('reconciliation') or {}).get('note','账单拟合')])
 for c in p['customers']:
  if account and c['account']!=account:continue
  vals=[safe_name(c['name']),c['account'],'已纳入月份合计',c['q']]
  vals += [(c.get(k) or {}).get('low') for k in ['weighted_sell','weighted_cost']]
  vals += ['']+[(c.get(k) or {}).get('low') for k in ['revenue','cost','profit']]
  w.writerow(vals+['合计',c['verdict']])
 return ('\ufeff'+s.getvalue()).encode('utf-8')
