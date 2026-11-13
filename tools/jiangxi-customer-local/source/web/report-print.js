// Print from the displayed calculation snapshot; restore screen folds after preview closes.
let reportPrintState=null;
const printParams=document.createElement('p');printParams.className='paramsprint';printParams.id='print-params';document.querySelector('.controls').after(printParams);
function reportFilenameBase(customer,parameters){
 const full=String(customer.name||'客户').trim();
 // Filename uses a short company label; the report body retains the full legal name.
 const short=full.replace(/(?:医疗科技)?(?:股份有限公司|有限责任公司|有限公司)$/,'').trim()||full;
 const number=v=>Number.isFinite(Number(v))?String(Number(v)):String(v);
 return `${short}${number(parameters.linkage)}联动${number(parameters.service_fee)}服务用电测算报告`.replace(/[\\/:*?"<>|\u0000-\u001f]/g,'_').replace(/[. ]+$/,'');
}
function prepareReportPrint(){
 if(reportPrintState)return true;
 const customer=report?.scenario.customers.find(c=>c.account===selected);
 if(!customer)return false;
 const p=report.scenario.params;
 reportPrintState={title:document.title,folds:[...document.querySelectorAll('#report>details')].map(el=>({el,open:el.open}))};
 for(const item of reportPrintState.folds)if(!item.el.hidden&&!item.el.classList.contains('method'))item.el.open=true;
 for(const {el} of reportPrintState.folds){
  if(el.hidden||el.classList.contains('method'))continue;
  const copy=document.createElement('section');copy.className=el.className+' report-print-copy';
  const heading=document.createElement('h2');heading.textContent=el.querySelector('summary').textContent;copy.append(heading);
  for(const child of [...el.children]){if(child.tagName==='SUMMARY')continue;const body=child.cloneNode(true);if(body.id)body.id='print-'+body.id;copy.append(body)}
  el.after(copy);
 }
 document.title=reportFilenameBase(customer,p);
 printParams.textContent=`${p.package==='rule-full'?'规则联动 · 全电量计服务费':'原模板 · 非联动部分加价'}　联动比例：${p.linkage}%　服务费：${p.service_fee}厘/度`;
}
function finishReportPrint(){
 if(!reportPrintState)return;
 document.querySelectorAll('.report-print-copy').forEach(el=>el.remove());
 document.title=reportPrintState.title;for(const {el,open} of reportPrintState.folds)el.open=open;
 reportPrintState=null;
}
function printReport(){
 if(document.body.classList.contains('busy')||!selected)return;
 prepareReportPrint();window.print();
}
window.addEventListener('beforeprint',prepareReportPrint);window.addEventListener('afterprint',finishReportPrint);
