const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const ts = require('typescript')
const assert = require('node:assert/strict')
const compile = source => ts.transpileModule(source, {compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.React,target:ts.ScriptTarget.ES2020}}).outputText
const helper = {}
vm.runInNewContext(compile(fs.readFileSync(path.join(__dirname,'supplementTarget.ts'),'utf8')), {exports:helper})
const page = fs.readFileSync(path.join(__dirname,'index.tsx'),'utf8')
const source = page.slice(page.indexOf('const jobColumns ='),page.indexOf('const getMonthlyQueueRowKey ='))
const exported = {}
const icons = Object.fromEntries(['UploadOutlined','AimOutlined','LineChartOutlined','TagsOutlined','EyeOutlined','FileSearchOutlined','DeleteOutlined'].map(k=>[k,k]))
vm.runInNewContext(compile(source+'\nexports.columns=jobColumns'),{
 exports:exported,...icons,React:{createElement:(type,props,...children)=>({type,props:props??{},children})},Space:'Space',Button:'Button',Popconfirm:'Popconfirm',
 jobSupplementTarget:helper.jobSupplementTarget,processingStatuses:new Set(['queued','created','cleaning','matching','processing']),
 formatText:x=>x,formatPlatform:x=>x,formatNumber:x=>x,
})
const noop=()=>{}
let selected
function render(job,view='active',busy=false){
 const columns=exported.columns(noop,noop,noop,noop,noop,view,noop,noop,noop,false,target=>{selected=target},busy)
 return columns.at(-1).render(null,job).children.find(x=>x&&x.children?.[0]==='检查并补齐')
}
for(const category of ['projector','router','headphone','kids_smartwatch']){
 for(const status of ['reviewing','done','published']){
  const job={id:401,category_code:category,platform:'douyin',month:202610,status,source_scope:{months:[202610]}}
  const button=render(job)
  assert.equal(button.props.disabled,false,'every category retains the permanent task-level entry')
  button.props.onClick()
  assert.equal(selected.id,401)
  assert.equal(selected.category_code,category)
  assert.equal(render(job,'active',true).props.disabled,true)
  assert.equal(render(job,'archived'),undefined)
  assert.equal(render({...job,status:'queued'}).props.disabled,true)
 }
}
const progress={}
vm.runInNewContext(compile(fs.readFileSync(path.join(__dirname,'cleanProgress.ts'),'utf8')),{exports:progress})
assert.equal(progress.formatCleanProgress({status:'matching',execution_mode:'completion',execution_input_count:1,progress_stage:'补齐匹配结果',progress_total:1,progress_processed:0}),'本次补齐 1 条 · 补齐匹配结果：0 / 1 条')
