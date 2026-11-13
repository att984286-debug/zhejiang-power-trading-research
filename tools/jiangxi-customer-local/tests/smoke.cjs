// Only fictional input. Run after tests/make_fixture.py; no customer documents required.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const path=require('node:path'),fs=require('node:fs'),os=require('node:os'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..'),fixture=process.argv[2];
if(!fixture)throw Error('Usage: node tests/smoke.cjs /path/to/fictional-fixture.xlsx');
(async()=>{
 const browser=await chromium.launch({channel:process.env.BROWSER_CHANNEL||'chrome',headless:true});
 const network=[],errors=[];
 const watch=page=>{page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(/^https?:/.test(r.url()))network.push(r.url())})};
 const ctx=await browser.newContext({offline:true,acceptDownloads:true,viewport:{width:1440,height:1000}}),page=await ctx.newPage();watch(page);
 const url='file://'+path.join(root,'dist/index.html');
 await page.goto(url);await page.waitForFunction(()=>!document.querySelector('#files').disabled,{timeout:120000});
 await page.locator('#files').setInputFiles(path.resolve(fixture));
 await page.waitForSelector('#rows .rowbutton',{timeout:120000});
 const report=(p,query='linkage=10&service_fee=0&package=linkage')=>p.evaluate(async query=>await(await fetch('/api/report?'+query)).json(),query);
 const base=await report(page);assert.equal(base.scenario.months.length,1);assert.equal(base.curve_records.length,31);assert.equal(base.scenario.months[0].q,'1488.000');assert.equal(base.scenario.months[0].status,'exact');
 const fee=await report(page,'linkage=10&service_fee=5&package=linkage');
 assert.ok(Math.abs(Number(fee.scenario.months[0].revenue.low)-Number(base.scenario.months[0].revenue.low)-6.696)<=0.011);
 const full0=await report(page,'linkage=100&service_fee=0&package=linkage'),full5=await report(page,'linkage=100&service_fee=5&package=linkage');
 assert.deepEqual(full0.scenario.months[0].revenue,full5.scenario.months[0].revenue);
 // Concurrent UI/API requests must not reenter the Python runtime.
 const simultaneous=await page.evaluate(()=>Promise.all(Array.from({length:6},(_,i)=>fetch('/api/report?linkage='+i+'&service_fee=0').then(r=>r.json()))));
 assert.ok(simultaneous.every(r=>r.scenario&&!r.error));
 // UI parameter changes and downloads are also browser-local.
 await page.locator('#fee').fill('5');await page.waitForFunction(()=>!document.body.classList.contains('busy')&&document.querySelector('#feehint').textContent.includes('全电量'));
 const csvEvent=page.waitForEvent('download');await page.locator('#export').click();const csv=await csvEvent;assert.match(csv.suggestedFilename(),/\.csv$/);
 const csvPath=path.join(os.tmpdir(),'jx-fictional-report-'+process.pid+'.csv');await csv.saveAs(csvPath);assert.match(fs.readFileSync(csvPath,'utf8'),/2026-07/);
 await page.locator('#files').setInputFiles(path.resolve(fixture));await page.waitForFunction(()=>document.querySelector('#progress').textContent.includes('跳过重复'));
 assert.equal((await report(page)).curve_records.length,31);
 const backupEvent=page.waitForEvent('download');await page.locator('#backup').click();const backup=await backupEvent;
 const backupPath=path.join(os.tmpdir(),'jx-fictional-backup-'+process.pid+'.json');await backup.saveAs(backupPath);
 await page.reload();await page.waitForSelector('#rows .rowbutton',{timeout:120000});assert.equal((await report(page)).curve_records.length,31);
 const fresh=await browser.newContext({offline:true,viewport:{width:1440,height:1000}}),p2=await fresh.newPage();watch(p2);await p2.goto(url);await p2.waitForFunction(()=>!document.querySelector('#files').disabled,{timeout:120000});
 await p2.locator('#restore-local').setInputFiles(backupPath);await p2.waitForSelector('#rows .rowbutton',{timeout:120000});
 const restored=await report(p2);assert.deepEqual(restored.scenario.months[0].profit,base.scenario.months[0].profit);
 await p2.locator('#restore-local').setInputFiles(backupPath);await p2.waitForFunction(()=>document.querySelector('#progress').textContent.includes('已恢复'));
 assert.equal((await report(p2)).curve_records.length,31);assert.deepEqual(network,[]);assert.deepEqual(errors,[]);
 await browser.close();fs.unlinkSync(csvPath);fs.unlinkSync(backupPath);
 console.log('PASS: file:// offline boot, 31 fictional days, 1488 kWh, fees, concurrent requests, CSV, dedup, reload, merged restore; zero HTTP');
})().catch(e=>{console.error(e);process.exit(1)});
