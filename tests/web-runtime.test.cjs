const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');
const root = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(root, 'web/index.html'), 'utf8');
const script = fs.readFileSync(path.join(root, 'web/app.js'), 'utf8');

function setup(saved) {
  const elements = new Map();
  for (const match of html.matchAll(/<(\w+)\b([^>]*\bid="([^"]+)"[^>]*)>/g)) {
    const [,tag,attrs,id] = match;
    const contents = html.slice(match.index + match[0].length).split('</' + tag + '>')[0];
    const options = tag === 'select' ? [...contents.matchAll(/<option(?: value="([^"]*)")?>([^<]*)<\/option>/g)].map(m=>({value:m[1] || m[2]})) : [];
    elements.set(id, {tagName:tag.toUpperCase(), options,
      value: tag === 'textarea' ? contents : tag === 'select' ? options[0].value : attrs.match(/\bvalue="([^"]*)"/)?.[1] || '',
      textContent:'', hidden:/\bhidden\b/.test(attrs), listeners:{}, attributes:{},
      addEventListener(event, listener){this.listeners[event]=listener;},
      setAttribute(name,value){this.attributes[name]=value;},
      append(option){this.options.push(option);}, replaceChildren(){this.options=[];},
      setCustomValidity(message){this.validationMessage=message;}, reportValidity(){return true;}, querySelectorAll(){return [];} });
  }
  const context = {document:{createTextNode(text){return {textContent:text};},createElement(tag){
    return {tagName:tag.toUpperCase(),value:'',textContent:'',children:[], listeners:{},
      append(...nodes){this.children.push(...nodes);},addEventListener(event,fn){this.listeners[event]=fn;}};
  },getElementById(id){assert.ok(elements.has(id), 'missing ID: ' + id); return elements.get(id);}},
    localStorage:{getItem(){return saved ? JSON.stringify(saved) : null;}}, location:{protocol:'file:'}};
  vm.createContext(context);
  vm.runInContext(script + '\nglobalThis.probe = {readConfiguration,restoreConfiguration,commonMonitorPrompt,showConnection,validInputs,pendingSelection,executionDisplay,diagnosticText,renderReviewHistory,setRuntime(state, connected) {currentRun=state; online=true; apiConnected=connected; selectedRequest=state.requests[0]?.id; controls();}};', context);
  return {probe:context.probe, elements};
}

function enableMonitors(elements) {
  const architecture = elements.get('architecture');
  architecture.value = 'main-agent-with-three-observers';
  architecture.listeners.change();
}

test('review history shows full prose, its answer and the verified version', () => {
  const {probe, elements} = setup();
  const entry = {id:'abc', monitor_id:2, version:1, reason:'정각에도 허용합니까?', requests:[], checks:[], request_ids:['r1']};
  const state = {status:'running', requests:[{id:'r1', answer:{text:'정각에는 거부합니다.'}, verified_version:4}], review_log:[entry]};
  probe.renderReviewHistory(state);
  let row = elements.get('review-entries').options[0];
  assert.match(row.textContent, /메인 전달 대기.*정각에도 허용합니까/);
  assert.ok(row.children.some(n => n.tagName === 'BUTTON'));
  assert.ok(row.children.some(n => /정각에는 거부합니다.*v4 검사 통과/.test(n.textContent)));
  entry.delivered_version = 3;
  state.status = 'completed';
  probe.renderReviewHistory(state);
  row = elements.get('review-entries').options[0];
  assert.match(row.textContent, /메인 v3에 전달/);
  assert.ok(!row.children.some(n => n.tagName === 'BUTTON'));
  probe.renderReviewHistory({requests:[]});
  assert.ok(elements.get('review-history').hidden);
});

test('fresh baseline uses a small model, basic task and no observers', () => {
  const {probe,elements} = setup();
  const config = probe.readConfiguration();
  assert.equal(config.architecture, 'main-only');
  assert.equal(config.monitors.length, 0);
  assert.equal(config.mainAgent.model, 'gpt-4o-mini');
  assert.equal(config.task_id, 'cancellation_basic');
  assert.ok(elements.get('instructions-1').disabled);
  assert.equal(JSON.stringify(setup(config).probe.readConfiguration()), JSON.stringify(config));
});

test('default instructions include common judgment prompt for all three monitors', () => {
  const {probe,elements} = setup();
  enableMonitors(elements);
  assert.equal(probe.readConfiguration().monitors.length, 3);
  for (const m of probe.readConfiguration().monitors) assert.ok(m.instructions.includes(probe.commonMonitorPrompt));
});

test('paused, interrupted and failed runs accept answers before key reconnection', () => {
  const {probe, elements} = setup();
  const input = {};
  elements.get('answer-fields').querySelectorAll = () => [input];
  for (const status of ['paused', 'interrupted', 'failed']) {
    const state = {mode:'openai', status, test:{status:'not_run'}, requests:[{id:'pending',status:'waiting'}]};
    probe.setRuntime(state, false);
    assert.equal(input.disabled, false);
    assert.equal(elements.get('submit-answer').disabled, false);
    assert.equal(elements.get('resume-run').hidden, false);
    assert.equal(elements.get('resume-run').disabled, true);
    probe.setRuntime(state, true);
    assert.equal(elements.get('resume-run').disabled, false);
    state.requests[0].status = 'answered';
    probe.setRuntime(state, true);
    assert.equal(input.disabled, true);
  }
});

test('rules toggle is initially closed and excluded from agent configuration', () => {
  const {probe, elements} = setup();
  const panel = elements.get('grading-rules'), button = elements.get('toggle-rules');
  assert.equal(panel.hidden, true);
  button.listeners.click();
  assert.equal(panel.hidden, false);
  assert.equal(button.attributes['aria-expanded'], 'true');
  button.listeners.click();
  assert.equal(panel.hidden, true);
  assert.equal(button.attributes['aria-expanded'], 'false');
  const config = JSON.stringify(probe.readConfiguration());
  for (const hidden of ['2026-11-10', '2026-12-24', '24시간', '금·토·일', 'UTC+9']) assert.ok(!config.includes(hidden));
});

test('task selection changes defaults, preserves custom prompts and saves the task', () => {
  const {probe, elements} = setup();
  assert.equal(probe.readConfiguration().task_id, 'cancellation_basic');
  const task = elements.get('task-id');
  task.value = 'allocation'; task.listeners.change();
  assert.equal(probe.readConfiguration().task_id, 'allocation');
  assert.ok(elements.get('main-prompt').value.startsWith('예약·대기열·자원 배정'));
  assert.equal(elements.get('cancellation-rules').hidden, true);
  assert.equal(elements.get('allocation-rules').hidden, false);
  const restored = setup(probe.readConfiguration());
  assert.equal(restored.probe.readConfiguration().task_id, 'allocation');
  elements.get('main-prompt').value = '  사용자 원문\n보존  ';
  task.value = 'cancellation'; task.listeners.change();
  assert.equal(elements.get('main-prompt').value, '  사용자 원문\n보존  ');
  assert.equal(elements.get('cancellation-rules').hidden, false);
});
test('old saved prompts migrate once and edited version 3 prompts stay verbatim', () => {
  const legacy = setup();
  enableMonitors(legacy.elements);
  const initial = legacy.probe.readConfiguration();
  initial.version = 2;
  initial.mainAgent.prompt = '  메인 원문\n  ';
  initial.monitors.forEach(m => {m.instructions='  직접 입력\n관점 ' + m.id;});
  const {probe} = setup(initial);
  const updated = probe.readConfiguration();
  assert.equal(updated.mainAgent.prompt, initial.mainAgent.prompt);
  for (const m of updated.monitors) assert.equal(m.instructions, initial.monitors[m.id-1].instructions + '\n' + probe.commonMonitorPrompt);
  const twice = setup(updated).probe.readConfiguration();
  assert.equal(JSON.stringify(twice), JSON.stringify(updated));
  updated.monitors[0].instructions = '  새 지침\n원문  ';
  assert.equal(setup(updated).probe.readConfiguration().monitors[0].instructions, '  새 지침\n원문  ');
});


test('supported account model IDs are selectable independently, including Luna and GPT-4o', () => {
  const {probe,elements}=setup();
  enableMonitors(elements);
  const models=['gpt-6-luna','gpt-4o','gpt-4o-mini','gpt-4o-2024-11-20','gpt-5.4','gpt-5.4-mini'];
  probe.showConnection({connected:true,models});
  const ids=['main-model','model-1','model-2','model-3'];
  ids.forEach((id,i)=>{
    const input=elements.get(id);
    for(const model of models) assert.ok(input.options.some(o=>o.value===model));
    input.value=models[i];
  });
  probe.showConnection({connected:true,models:[...models,'gpt-5.5']});
  const cfg=probe.readConfiguration();
  assert.equal(cfg.mainAgent.model,models[0]);
  assert.deepEqual(Array.from(cfg.monitors,m=>m.model),models.slice(1,4));
  const restored=setup(cfg).probe.readConfiguration();
  assert.equal(JSON.stringify(restored),JSON.stringify(cfg));
});

test('unavailable saved model stays visible but cannot be used with a connected key', () => {
  const cfg=setup().probe.readConfiguration();
  cfg.mainAgent.model='ft:'+ 'x'.repeat(100);
  const {probe,elements}=setup(cfg);
  probe.showConnection({connected:true,models:['gpt-4o']});
  const main=elements.get('main-model');
  assert.equal(main.value,cfg.mainAgent.model);
  assert.ok(main.options.find(o=>o.value===main.value).textContent.includes('지원 목록에 없음'));
  assert.equal(main.options.find(o=>o.value===main.value).disabled,true);
  probe.validInputs();
  assert.ok(main.validationMessage.includes('모델 목록'));
  main.value='gpt-4o';
  probe.validInputs();
  assert.equal(main.validationMessage,'');
  probe.showConnection({connected:false,models:[]});
  assert.equal(main.value,'gpt-4o');
  assert.ok(main.options.some(o=>o.value==='gpt-6-luna'));
});


test('new pending questions replace the locked answered selection without stealing an active draft', () => {
  const {probe}=setup();
  const requests=[{id:'old',status:'answered'},{id:'new',status:'waiting'},{id:'third',status:'waiting'}];
  assert.equal(probe.pendingSelection(requests,'old'),'new');
  assert.equal(probe.pendingSelection(requests,'third'),'third');
  assert.equal(probe.pendingSelection([requests[0]],'old'),'old');
  assert.equal(probe.pendingSelection([requests[0],{id:'clarify',status:'needs_example'}],'old'),'clarify');
});


test('execution status distinguishes waiting for a model, paused and disconnected', () => {
  const {probe}=setup();
  const run={status:'running',phase:'코드 작성',test:{status:'not_run'},calls:[{agent:'main',status:'running'}]};
  assert.deepEqual(Array.from(probe.executionDisplay(run,true)),['진행 중','메인 응답 대기']);
  run.status='paused';run.last_error='보고 누락';
  const paused=probe.executionDisplay(run,true);
  assert.equal(paused[0],'일시 정지 · 멈춤');
  assert.ok(paused[1].includes('자동 진행 안 됨'));
  assert.ok(paused[1].includes('보고 누락'));
  assert.equal(probe.executionDisplay(run,false)[0],'연결 끊김');
  run.status='waiting';assert.equal(probe.executionDisplay(run,true)[0],'답변 대기');
  run.status='completed';assert.equal(probe.executionDisplay(run,true)[0],'완료');
  run.test.status='running';assert.equal(probe.executionDisplay(run,true)[0],'채점 중');
});


test('diagnostics show exact limits and failed responses, with a truthful legacy fallback', () => {
  const {probe}=setup();
  const state={calls:[{id:'call-1',output:{requests:[{question:'확인'}]}}],diagnostics:[{
    at:'2026-10-30T03:00:00Z',agent:'monitor-3',model:'gpt-5',call_id:'call-1',code_version:0,
    action:'observe',stage:'response_validation',exception_type:'ResponseValidationError',
    message:'질문 8개 초과',details:{field:'requests.length',expected:'<= 6',actual:8},elapsed_ms:1200
  }]};
  const text=probe.diagnosticText(state);
  for(const part of ['감시 3','gpt-5','requests.length','<= 6','질문 8개 초과','확인']) assert.ok(text.includes(part));
  assert.ok(probe.diagnosticText({last_error:'이전 오류'}).includes('복원할 수 없습니다'));
});
