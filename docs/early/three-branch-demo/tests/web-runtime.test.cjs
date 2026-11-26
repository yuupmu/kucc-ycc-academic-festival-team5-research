const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { MonitorRun } = require('../web/branch-runner.js');
const configs = [1, 2, 3].map(id => ({ id, concept: `컨셉 ${id}`, instructions: `지침 ${id}`, model: 'GPT-6.1 Sol' }));
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
async function until(condition) {
  for (let i = 0; i < 100; i++) { if (condition()) return; await pause(5); }
  assert.fail('State transition timed out');
}
function makeRun(options = {}) { return new MonitorRun(configs, { workers: ['A', 'B', 'C'] }, { analysisDelay: 0, resumeDelay: 0, ...options }); }

test('three branches start together, resume independently, and merge after all answers', async () => {
  const run = makeRun();
  const done = run.start();
  assert.deepEqual(run.branches.map(b => b.state), ['running', 'running', 'running']);
  await until(() => run.branches.every(b => b.state === 'waiting'));
  assert.equal(run.answer(2, '두 번째 답변'), true);
  assert.equal(run.answer(2, '중복 답변'), false);
  await until(() => run.branches[1].state === 'completed');
  assert.deepEqual(run.branches.map(b => b.state), ['waiting', 'completed', 'waiting']);
  assert.equal(run.mergedResults.length, 0);
  assert.equal(run.answer(1, '첫 번째 답변'), true);
  assert.equal(run.answer(3, '세 번째 답변'), true);
  const result = await done;
  assert.equal(result.outcome, 'completed');
  assert.deepEqual(result.mergedResults.map(b => b.answer), ['첫 번째 답변', '두 번째 답변', '세 번째 답변']);
  assert.deepEqual(result.branches.map(b => b.config.instructions), ['지침 1', '지침 2', '지침 3']);
});

test('inputs and returned snapshots are independent copies', () => {
  const shared = { workers: ['A'] };
  const run = new MonitorRun(configs, shared);
  shared.workers.push('outside');
  run.branches[0].context.workers.push('only-1');
  assert.deepEqual(run.branches[1].context.workers, ['A']);
  const snapshot = run.snapshot();
  snapshot.branches[0].config.instructions = 'changed';
  assert.equal(run.branches[0].config.instructions, '지침 1');
});

test('stop releases waiting branches and preserves completed branch without merging', async () => {
  const run = makeRun();
  const done = run.start();
  await until(() => run.branches.every(b => b.state === 'waiting'));
  run.answer(1, '완료한 답변');
  await until(() => run.branches[0].state === 'completed');
  run.stop();
  const result = await done;
  assert.equal(result.outcome, 'stopped');
  assert.deepEqual(result.branches.map(b => b.state), ['completed', 'stopped', 'stopped']);
  assert.equal(run.pending.size, 0);
  assert.equal(run.answer(2, '너무 늦은 답변'), false);
  assert.deepEqual(result.mergedResults, []);
});

test('early stop cancels scheduled questions, empty and unknown answers are rejected', async () => {
  const run = makeRun({ analysisDelay: 100 });
  const done = run.start();
  assert.equal(run.answer(7, '답변'), false);
  assert.equal(run.answer(1, '  '), false);
  run.stop();
  assert.equal((await done).outcome, 'stopped');
  assert.ok(run.branches.every(b => b.state === 'stopped'));
  assert.equal(run.pending.size, 0);
});

test('UI routes custom configs and per-branch answers; reset ignores old callbacks', async () => {
  const root = path.join(__dirname, '..', 'web');
  const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
  const ids = [...html.matchAll(/id="([^"]+)"/g)].map(m => m[1]);
  assert.equal(new Set(ids).size, ids.length);
  const elements = {};
  function element() { return { value: '', disabled: false, hidden: false, textContent: '', children: [], listeners: {},
    addEventListener(name, fn) { this.listeners[name] = fn; }, setCustomValidity(message) { this.validationMessage = message; },
    reportValidity() {}, append(...children) { this.children.push(...children); }, replaceChildren() { this.children = []; }, click() {} }; }
  ids.forEach(id => elements[id] = element());
  for (let i = 1; i <= 3; i++) {
    elements[`concept-${i}`].value = `직접 작성 ${i}`;
    elements[`instructions-${i}`].value = `개별 지침 ${i}`;
    elements[`model-${i}`].value = 'GPT-6.1 Sol';
  }
  elements['worker-model'].value = 'GPT-6.1 Sol';
  const runs = [];
  class FastRun extends MonitorRun {
    constructor(config, context, options) { super(config, context, { ...options, analysisDelay: 0, resumeDelay: 0 }); runs.push(this); }
  }
  const context = vm.createContext({ document: { getElementById(id) { assert.ok(elements[id], id); return elements[id]; }, createElement: element },
    MonitorRun: FastRun, Date, Blob, URL, setTimeout, clearTimeout });
  vm.runInContext(fs.readFileSync(path.join(root, 'app.js'), 'utf8'), context);
  const fire = (id, event) => elements[id].listeners[event]({ preventDefault() {} });
  fire('settings', 'submit');
  await until(() => runs[0].branches.every(b => b.state === 'waiting'));
  assert.equal(elements['instructions-1'].disabled, true);
  assert.equal(runs[0].branches[2].config.instructions, '개별 지침 3');
  elements['answer-3'].value = '분기 3 전용 답변';
  fire('answer-form-3', 'submit');
  await until(() => runs[0].branches[2].state === 'completed');
  assert.equal(elements['completed-count'].textContent, '1 / 3 완료');
  assert.equal(elements['answer-form-1'].hidden, false);
  assert.equal(elements['answer-summary-3'].textContent, '답변: 분기 3 전용 답변');
  assert.equal(runs[0].branches[0].answer, null);
  fire('reset', 'click');
  fire('settings', 'submit');
  await until(() => runs[1].branches.every(b => b.state === 'waiting'));
  assert.equal(elements['completed-count'].textContent, '0 / 3 완료');
  assert.equal(elements['run-state'].textContent, '세 분기 병렬 진행 (데모)');
  fire('stop', 'click');
  await until(() => runs[1].outcome === 'stopped');
  assert.equal(elements['instructions-1'].disabled, false);
});
