import {test, after} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import cp from 'node:child_process';
import util from 'node:util';
import {syncBuiltinESMExports} from 'node:module';
import {join, dirname} from 'node:path';
import {fileURLToPath} from 'node:url';

// Synthetic package/API: no browser, network, user profile or installed package.
const area=fs.realpathSync(fs.mkdtempSync(join(os.tmpdir(),'lookup-native-test-')));
const home=join(area,'home'), pkg=join(area,'package');
const savedHome=os.homedir, savedExec=cp.execFile;
const previousState=process.env.XDG_STATE_HOME;
process.env.XDG_STATE_HOME=join(area,'state');
const write=(path,body) => {fs.mkdirSync(dirname(path),{recursive:true});fs.writeFileSync(path,body)};
write(join(pkg,'package.json'),JSON.stringify({name:'@jackwener/opencli',version:'2.0.2',type:'module',exports:{'./registry':'./dist/src/registry-api.js','./errors':'./dist/src/errors.js'}}));
write(join(pkg,'main.js'),'');
write(join(pkg,'dist/src/registry-api.js'),`export const getRegistry=()=>globalThis.__syntheticRegistry??=new Map();export function cli(c){getRegistry().set(c.site+'/'+c.name,c);return c;}`);
write(join(pkg,'dist/src/errors.js'),'export class SyntheticError extends Error {}');
write(join(pkg,'dist/src/discovery.js'),`import {existsSync} from 'node:fs';import {pathToFileURL} from 'node:url';import {join} from 'node:path';export async function discoverClis(root){const path=join(root,'bilibili/subtitle.js');if(existsSync(path))await import(pathToFileURL(path));}`);
write(join(pkg,'dist/src/execution.js'),'export const prepareCommandArgs=(cmd,args)=>args;');
write(join(pkg,'dist/src/browser/stealth.js'),'export const generateStealthJs=()=>"stealth";');
write(join(pkg,'dist/src/browser/dom-helpers.js'),'export const waitForDomStableJs=()=>"settle";');
write(join(pkg,'dist/src/browser/errors.js'),'export const classifyBrowserError=e=>({kind:e.code==="nav"?"target-navigation":"other",delayMs:0});');
write(join(pkg,'dist/src/browser/utils.js'),'export const buildEvaluateExpression=x=>x;');
write(join(pkg,'clis/bilibili/subtitle.js'),`import {cli} from '@jackwener/opencli/registry';cli({site:'bilibili',name:'subtitle',access:'read',navigateBefore:'https://synthetic.invalid',args:[{name:'bvid',required:true,positional:true}],func:async(p,k)=>globalThis.__syntheticWork(p,k)});`);
fs.mkdirSync(join(home,'.opencli/clis'),{recursive:true});
os.homedir=()=>home;
let probeFailure;
const fakeExec=()=>{throw new Error('Unexpected synchronous subprocess')};
fakeExec[util.promisify.custom]=async(binary,args)=>{
  if(probeFailure) throw probeFailure;
  const marker=JSON.parse(args.at(-1))[0].title;
  return {stdout:JSON.stringify({ok:true,data:[{title:marker,url:'data:text/html,'+encodeURIComponent('<title>'+marker+'</title>')}]}),stderr:''};
};
cp.execFile=fakeExec;
syncBuiltinESMExports();
const n=await import('../scripts/opencli-native.mjs');
after(()=>{os.homedir=savedHome;cp.execFile=savedExec;syncBuiltinESMExports();if(previousState===undefined)delete process.env.XDG_STATE_HOME;else process.env.XDG_STATE_HOME=previousState;fs.rmSync(area,{recursive:true,force:true})});

async function scenario(name,behavior,options={}) {
  const root=join(area,name);fs.mkdirSync(root,{recursive:true});
  const binary=join(pkg,'main.js'), descriptor=n.describeSource(binary,'bilibili/subtitle');
  const request={binary,descriptor,home,args:['bilibili','subtitle','BV1AbcDefG23'],profile:'synthetic',jobRoot:root,leasePath:join(root,'lease.json')};
  write(join(root,'request.json'),JSON.stringify(request));
  const spaces=[{id:9,name:'unrelated',createdBy:'user',ownership:'user'}], events=[];
  const api={listTaskSpaces:async()=>spaces.map(x=>({...x})),taskSpace:async target=>{
    let space;
    if(typeof target==='string'){space={id:10,name:target,createdBy:'agent',ownership:'agent'};spaces.push(space);events.push('create')}
    else space=spaces.find(x=>x.id===target);
    return {name:space.name,spaceId:space.id,get ownership(){return space.ownership},page:()=>({goto:async url=>events.push(url.startsWith('data:')?'marker':'business'),evaluate:async()=>null}),finish:async()=>{events.push('finish');spaces.splice(spaces.indexOf(space),1);return {spaceId:space.id,closedSpace:true}}};
  }};
  globalThis.__syntheticWork=async(p,k)=>behavior({p,k,spaces,events,request});
  probeFailure=options.probeFailure;
  if(options.drift)fs.appendFileSync(join(pkg,'clis/bilibili/subtitle.js'),'\n// changed\n');
  const result=await n.runInEgo(join(root,'request.json'),api);
  return {result,events,spaces,request};
}

test('field projection preserves full output, null and empty; rejects every missing row',()=>{
  assert.deepEqual(n.project([{a:1,b:null}],null),[{a:1,b:null}]);
  assert.deepEqual(n.project([{a:null,b:2}],['a']),[{a:null}]);
  assert.deepEqual(n.project([],['a']),[]);
  assert.deepEqual(n.project([{field:'title',value:'synthetic'},{field:'likes',value:null}],['likes']),[{field:'likes',value:null}]);
  assert.throws(()=>n.project([{from:1},{to:2}],['from','to']),{code:'LOOKUP_FIELDS'});
  assert.throws(()=>n.project([{field:'a',value:1}],['b']),{code:'LOOKUP_FIELDS'});
});
test('lookup options are separate and standard terminator remains literal',()=>{
  assert.deepEqual(n.lookupOptions(['--lookup-engine','bridge','x','y','--','--lookup-fields','literal']).args,['x','y','--','--lookup-fields','literal']);
  for(const args of [['--lookup-engine','bad'],['--lookup-fields','a,a'],['--lookup-fields',''],['--lookup-engine']])assert.throws(()=>n.lookupOptions(args),{code:'LOOKUP_OPTIONS'});
});
test('missing, malformed and hollow native receipts remain unknown; stderr is supported',()=>{
  for(const text of ['', '@@LOOKUP_NATIVE@@{', '@@LOOKUP_NATIVE@@{"ok":true,"cleanup":{"status":"closed"}}'])assert.throws(()=>n.nativeReceipt(text,''),{code:'LOOKUP_NATIVE_UNKNOWN',outcome_unknown:true});
  const result={ok:true,data:[],cleanup:{status:'closed'}};
  assert.deepEqual(n.nativeReceipt('','@@LOOKUP_NATIVE@@'+JSON.stringify(result)),result);
});
test('complete adapter is called, gets required args, and only its space closes',async()=>{
  const s=await scenario('normal',async({k})=>[{content:k.bvid}]);
  assert.equal(s.result.ok,true);assert.deepEqual(s.result.data,[{content:'BV1AbcDefG23'}]);
  assert.deepEqual(s.events,['create','marker','business','finish']);assert.deepEqual(s.spaces.map(s=>s.id),[9]);
});
test('original authentication code and help survive',async()=>{
  const s=await scenario('auth',async()=>{throw Object.assign(new Error('Login required'),{code:'AUTH_REQUIRED',help:'manual login'})});
  assert.equal(s.result.error.code,'AUTH_REQUIRED');assert.equal(s.result.error.message,'Login required');assert.equal(s.result.error.hint,'manual login');assert.equal(s.result.ok,false);
});
test('late effects and execution stop uncertainty remain unknown',async()=>{
  const s=await scenario('unknown',async()=>{throw Object.assign(new Error('timeout'),{code:'execution_timeout',executionStopped:false,mayHaveLateEffects:true,outcome_unknown:true})});
  assert.equal(s.result.outcome_unknown,true);assert.equal(s.result.error.executionStopped,false);assert.equal(s.result.error.mayHaveLateEffects,true);
});
test('takeover and denied probe stop; no business or cleanup against user control',async()=>{
  const s=await scenario('takeover',async({spaces})=>{spaces[1].ownership='user';throw new Error('User control transferred')});
  assert.equal(s.result.ok,false);assert.ok(['denied','user_control'].includes(s.result.cleanup.status));assert.ok(!s.events.includes('finish'));
  const denied=await scenario('denied',async()=>{throw new Error('must not run')},{probeFailure:Object.assign(new Error('Permission denied'),{code:'PERMISSION_DENIED'})});
  assert.equal(denied.result.error.code,'PERMISSION_DENIED');assert.ok(!denied.events.includes('business'));assert.ok(!denied.events.includes('finish'));
});
test('cleanup corruption retains completed content and unknown lease',async()=>{
  const s=await scenario('corrupt',async({request})=>{write(request.leasePath,'{broken');return [{content:'done'}]});
  assert.equal(s.result.outcome_unknown,true);assert.equal(s.result.cleanup.status,'uncertain');assert.deepEqual(s.result.data,[{content:'done'}]);
  n.finishJob({root:s.request.jobRoot},s.result);assert.ok(fs.existsSync(s.request.leasePath));
});
test('no_space cannot delete an existing open lease',()=>{
  const root=join(area,'open');write(join(root,'lease.json'),JSON.stringify({state:'open'}));
  n.finishJob({root},{cleanup:{status:'no_space'}});assert.ok(fs.existsSync(root));
});
test('native page preserves adapter security retry and only retries target navigation',async()=>{
  const calls=[];let count=0;
  const raw={evaluate:async code=>{calls.push(code);return ++count===1?{securityBlock:true}:{title:'synthetic'}},goto:async()=>{}};
  const task={page:()=>raw};
  const helpers={settle:()=>'',stealth:()=>'',classify:e=>({kind:e.code==='nav'?'target-navigation':'other',delayMs:0}),expression:x=>x,markDispatched:()=>{}};
  const command={func:async p=>{const first=await p.evaluate('first');if(first.securityBlock){await p.wait({time:0});return p.evaluate('second')}return first}};
  assert.deepEqual(await n.executeAdapter(task,command,{},helpers),{title:'synthetic'});
  assert.deepEqual(calls,['first','second']);
  let tries=0;
  raw.evaluate=async()=>{if(++tries===1)throw Object.assign(new Error('navigation'),{code:'nav'});return 'ready'};
  assert.equal(await n.executeAdapter(task,{func:p=>p.evaluate('value')},{},helpers),'ready');assert.equal(tries,2);
  tries=0;raw.evaluate=async()=>{tries++;throw Object.assign(new Error('Permission denied'),{code:'denied'})};
  await assert.rejects(()=>n.executeAdapter(task,{func:p=>p.evaluate('value')},{},helpers),{code:'denied'});assert.equal(tries,1);
});
test('qualification needs actual closed equivalent samples and material benefit; drift invalidates',()=>{
  const plan={descriptor:n.describeSource(join(pkg,'main.js'),'bilibili/subtitle'),profile:'synthetic',egoVersion:'synthetic'};
  const evidence={equivalent:true,closed:true,samples:3,nativeMedian:2,bridgeMedian:3};
  for(const change of [{closed:false},{equivalent:false},{samples:2},{samples:undefined},{nativeMedian:2.9}])assert.throws(()=>n.recordQualification(plan,{...evidence,...change}),{code:'LOOKUP_NATIVE_QUALIFICATION'});
  n.recordQualification(plan,evidence);
  assert.ok(n.planNative(join(pkg,'main.js'),['bilibili','subtitle','BV1AbcDefG23'],'synthetic','auto','synthetic'));
  assert.equal(n.planNative(join(pkg,'main.js'),['bilibili','subtitle','BV1AbcDefG23'],'different','auto','synthetic'),null);
  assert.equal(n.planNative(join(pkg,'main.js'),['bilibili','subtitle','BV1AbcDefG23'],'synthetic','auto','synthetic','cdp'),null);
  for(const args of [['bilibili','subtitle','shortcode'],['bilibili','subtitle','https://b23.tv/synthetic'],['bilibili','subtitle','BV1AbcDefG23','--window','background'],['bilibili','subtitle','BV1AbcDefG23','--trace','on']])assert.equal(n.planNative(join(pkg,'main.js'),args,'synthetic','ego','synthetic'),null);
  write(join(pkg,'clis/bilibili/config.json'),'{"changed":true}');
  assert.equal(n.planNative(join(pkg,'main.js'),['bilibili','subtitle','BV1AbcDefG23'],'synthetic','auto','synthetic'),null);
  fs.rmSync(join(pkg,'clis/bilibili/config.json'));
  fs.appendFileSync(join(pkg,'dist/src/browser/stealth.js'),'\n// drift\n');
  assert.equal(n.planNative(join(pkg,'main.js'),['bilibili','subtitle','BV1AbcDefG23'],'synthetic','auto','synthetic'),null);
});
test('fingerprint changes stop before any space or business',async()=>{
  await assert.rejects(()=>scenario('drift',async()=>{throw new Error('must not run')},{drift:true}),{code:'LOOKUP_NATIVE_SOURCE_CHANGED'});
  assert.ok(!fs.existsSync(join(area,'drift/lease.json')));
});
