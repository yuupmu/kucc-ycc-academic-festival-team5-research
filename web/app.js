"use strict";

// API keys are submitted separately and never included in saved configurations.
const $ = id => document.getElementById(id);
$('toggle-rules').addEventListener('click', () => {
  const panel = $('grading-rules');
  panel.hidden = !panel.hidden;
  $('toggle-rules').setAttribute('aria-expanded', String(!panel.hidden));
  updateTaskUI();
});
const configForm = $("configuration");
const storageKey = "research-project-monitor-configuration-v2";
const monitorIds = [1, 2, 3];
const modelFields = ['main-model', ...monitorIds.map(id => 'model-' + id)];
const modelNames = {'gpt-6.1-sol':'Sol', 'gpt-6-astra':'Astra', 'gpt-6.1-terra':'Terra', 'gpt-6-luna':'Luna', 'gpt-4o':'GPT-4o', 'gpt-4o-mini':'GPT-4o mini'};
const defaultModels = Object.keys(modelNames);
let availableModels = [];
let modelsConnected = false;
function modelOption(value, unavailable = false) {
  const option = document.createElement('option');
  option.value = value;
  option.disabled = unavailable;
  option.textContent = (modelNames[value] ? modelNames[value] + ' · ' : '') + value + (unavailable ? ' · 지원 목록에 없음' : '');
  return option;
}
function fillModelOptions() {
  const choices = modelsConnected ? availableModels : defaultModels;
  for (const id of modelFields) {
    const input = $(id), selected = input.value;
    input.replaceChildren();
    if (selected && !choices.includes(selected)) input.append(modelOption(selected, true));
    for (const model of choices) input.append(modelOption(model));
    if (selected) input.value = selected;
  }
}
const commonMonitorPrompt = "전달받은 프로젝트 상태를 담당 관점으로 검토하고, ‘계속 진행 / 추가 검증 / 인간 판단 필요’ 중 하나를 제안한다. 인간 판단이 필요하면 근거·질문·영향받는 작업을 제시한다.";
const monitorFields = monitorIds.flatMap(id => [`concept-${id}`, `model-${id}`, `instructions-${id}`]);
const fields = ["task-id", "run-mode", "architecture", "project-name", "main-model", "main-prompt", ...monitorFields];
const limits = { "project-name": 120, "main-prompt": 20000 };
const taskInfo = {
  cancellation_basic: {name:'기본 예약 취소', total:40, project:'기본 예약 취소 판정'},
  cancellation: {name:'예약 취소', total:100, project:'예약 취소 판정 프로그램'},
  allocation: {name:'예약·대기열·자원 배정', total:150, project:'예약·대기열·자원 배정 프로그램'}
};
const defaultPrompts = {cancellation: $('main-prompt').value};
defaultPrompts.cancellation_basic = '안내문에 맞춰 예약 취소 함수를 구현한다. 판정을 바꾸는 운영 기준이 불명확하면 담당자에게 질문하고 받은 답을 코드에 반영한다.';
defaultPrompts.allocation = defaultPrompts.cancellation.replace('예약 취소 여부를 판정하는 Python 프로그램을 구현한다.', '예약·대기열·자원 배정을 처리하는 Python 프로그램을 구현한다.');
const loadedRules = new Set();
function updateTaskUI() {
  const task = $('task-id').value;
  const solo = $('architecture').value === 'main-only';
  $('monitor-fields').hidden = solo;
  $('cancellation-rules').hidden = task !== 'cancellation';
  $('allocation-rules').hidden = task !== 'allocation';
  $('basic-rules').hidden = task !== 'cancellation_basic';
  const mock = Array.from($('run-mode').options).find(o => o.value === 'mock');
  if (mock) mock.disabled = solo || task !== 'cancellation';
  if (mock?.disabled && $('run-mode').value === 'mock') $('run-mode').value = 'openai';
  if (task !== 'cancellation' && !$('grading-rules').hidden && !loadedRules.has(task) && location.protocol !== 'file:') {
    const panel = $(task === 'allocation' ? 'allocation-rules' : 'basic-rules');
    loadedRules.add(task);
    panel.textContent = '불러오는 중';
    api('/api/tasks/' + task + '/rules').then(result => {panel.textContent = result.text;})
      .catch(() => {loadedRules.delete(task); panel.textContent = '규칙을 불러오지 못했습니다.';});
  }
}
$('architecture').addEventListener('change', () => {updateTaskUI(); controls();});
function loadBaseline() {
  $('architecture').value = 'main-only';
  $('task-id').value = 'cancellation_basic';
  $('project-name').value = taskInfo.cancellation_basic.project;
  $('main-prompt').value = defaultPrompts.cancellation_basic;
  $('run-mode').value = 'openai';
  if (!Array.from($('main-model').options).some(option => option.value === 'gpt-4o-mini')) {
    $('main-model').append(modelOption('gpt-4o-mini', modelsConnected));
  }
  $('main-model').value = 'gpt-4o-mini';
  fillModelOptions();
  updateTaskUI();
}
$('baseline-preset').addEventListener('click', () => {loadBaseline(); controls();});
$('task-id').addEventListener('change', () => {
  const id = $('task-id').value;
  if (Object.values(defaultPrompts).includes($('main-prompt').value)) $('main-prompt').value = defaultPrompts[id];
  else $('config-status').textContent = '선택한 과제에 맞게 메인 프롬프트를 확인하세요.';
  if (Object.values(taskInfo).some(t => t.project === $('project-name').value)) $('project-name').value = taskInfo[id].project;
  updateTaskUI(); controls();
});

for (const id of monitorIds) { limits[`concept-${id}`] = 80; limits[`instructions-${id}`] = 12000; }

function readConfiguration() {
  return {
    version: 6,
    task_id: $('task-id').value,
    mode: $('run-mode').value,
    architecture: $('architecture').value,
    project: { name: $("project-name").value.trim() },
    mainAgent: { model: $("main-model").value, prompt: $("main-prompt").value },
    monitors: ($('architecture').value === 'main-only' ? [] : monitorIds).map(id => ({ id, model: $("model-" + id).value,
      concept: $("concept-" + id).value.trim(), instructions: $("instructions-" + id).value })),
    workflow: { observeDuringExecution: $('architecture').value !== 'main-only', waitForAllMonitors: false,
      deduplicateRequests: true, pauseAffectedTasksOnly: true, verifyAfterHumanDecision: true,
      benchmarkTrigger: "manual_after_project_completion" }
  };
}
function updateConceptLabels() {
  for (const id of monitorIds) $("monitor-name-" + id).textContent = $("concept-" + id).value.trim() || "미입력";
}
function validInputs() {
  for (const id of fields) {
    const input = $(id);
    if (input.disabled) { input.setCustomValidity(''); continue; }
    input.setCustomValidity(input.value.trim() ? "" : "공백이 아닌 내용을 입력하세요.");
    if (modelFields.includes(id) && $('run-mode').value === 'openai' && modelsConnected && !availableModels.includes(input.value)) {
      input.setCustomValidity('연결된 API 키의 모델 목록에서 선택하세요.');
    }
  }
  return configForm.reportValidity();
}
function restoreConfiguration(config, migrateSaved = false) {
  const solo = config?.architecture === 'main-only';
  if (!config || ![2, 3, 4, 5, 6].includes(config.version) || (!solo && config.architecture !== "main-agent-with-three-observers") ||
      !Array.isArray(config.monitors) || config.monitors.length !== (solo ? 0 : 3)) throw new Error("Unsupported configuration");
  const aliases = {'GPT-6.1 Sol':'gpt-6.1-sol', 'GPT-6 Astra':'gpt-6-astra', 'GPT-6.1 Terra':'gpt-6.1-terra', 'GPT-6 Luna':'gpt-6-luna'};
  const values = { 'task-id': config.task_id || 'cancellation', 'run-mode': config.mode || 'openai', "project-name": config.project?.name, "main-model": aliases[config.mainAgent?.model] || config.mainAgent?.model, "main-prompt": config.mainAgent?.prompt };
  values.architecture = config.architecture;
  for (const id of solo ? [] : monitorIds) {
    const matches = config.monitors.filter(m => m && m.id === id);
    if (matches.length !== 1) throw new Error("Invalid monitor configuration");
    const monitor = matches[0];
    values[`concept-${id}`] = monitor.concept;
    values[`model-${id}`] = aliases[monitor.model] || monitor.model;
    values[`instructions-${id}`] = monitor.instructions;
    if (migrateSaved && config.version === 2 && typeof monitor.instructions === 'string' &&
        !monitor.instructions.includes(commonMonitorPrompt)) {
      values[`instructions-${id}`] += '\n' + commonMonitorPrompt;
    }
  }
  // Validate every field before applying any saved values.
  for (const [id, value] of Object.entries(values)) {
    if (typeof value !== "string" || !value.trim() || (limits[id] && value.length > limits[id])) throw new Error("Invalid saved value");
    const input = $(id);
    if (input.tagName === "SELECT" && !modelFields.includes(id) && !Array.from(input.options).some(option => option.value === value)) throw new Error("Unknown selection");
    if (modelFields.includes(id) && value.length > 512) throw new Error('Invalid model ID');
  }
  for (const [id, value] of Object.entries(values)) {
    if (modelFields.includes(id) && !Array.from($(id).options).some(o => o.value === value)) $(id).append(modelOption(value));
    $(id).value = value;
  }
  fillModelOptions();
  updateConceptLabels();
  updateTaskUI();
}

for (const id of fields) {
  $(id).addEventListener("input", () => {
    $(id).setCustomValidity("");
    updateConceptLabels();
    $("config-status").textContent = "변경됨";
  });
}
configForm.addEventListener("submit", event => {
  event.preventDefault();
  if (!validInputs()) return;
  try {
    localStorage.setItem(storageKey, JSON.stringify(readConfiguration()));
    $("config-status").textContent = "저장됨";
  } catch {
    $("config-status").textContent = "저장 실패 · JSON 내려받기 가능";
  }
});
$("export-config").addEventListener("click", () => {
  if (!validInputs()) return;
  const blob = new Blob([JSON.stringify(readConfiguration(), null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "project-monitor-config.json";
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
try {
  const saved = localStorage.getItem(storageKey);
  if (saved) {
    restoreConfiguration(JSON.parse(saved), true);
    $("config-status").textContent = "불러옴";
  } else loadBaseline();
} catch {
  $("config-status").textContent = "불러오기 실패";
}

let online = false;
let currentRun = null;
let selectedRequest = null;
let formRequest = null;
let lastRevision = null;
let busy = false;
let operationVersion = 0;
let apiConnected = false;
let modelList = '';
const activeStates = ['running', 'waiting', 'applying'];
const statusLabels = {acknowledged:'맥락 확인', waiting:'답변 대기', answered:'답변받음', applying:'반영 중', applied:'정책 반영 확인',
  completed:'완료', paused:'계속하기 대기', stopped:'중단', interrupted:'중단됨', failed:'실패', running:'진행 중', not_run:'채점 전'};
const decisionLabels = {human:'인간 판단 필요', continue:'계속 진행', verify:'추가 검증'};
const acceptsAnswer = request => ['waiting', 'needs_example'].includes(request?.status);
async function api(path, body) {
  const response = await fetch(path, body === undefined ? {} : {
    method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || '요청 실패');
  return data;
}
function executionDisplay(state, connected, keyConnected = false) {
  if (!connected) return ['연결 끊김', '서버 연결이 없어 실행 상태를 확인할 수 없습니다.'];
  if (!state) return ['실행 전', ''];
  if (state.test?.status === 'running') return ['채점 중', '테스트 결과 대기'];
  const labels = {running:'진행 중', applying:'진행 중', waiting:'답변 대기', paused:'일시 정지 · 멈춤',
    interrupted:'중단됨', stopped:'중단됨', failed:'오류 · 멈춤', completed:'완료'};
  if (['paused','interrupted','failed'].includes(state.status)) {
    return [labels[state.status], '자동 진행 안 됨 · ' + (keyConnected ? '계속하기 필요' : 'API 키 연결 후 계속하기') + (state.last_error ? ' — ' + state.last_error : '')];
  }
  if (state.status === 'stopped') return ['중단됨', '사용자가 중단한 실행'];
  if (state.status === 'completed') return ['완료', '테스트하기 가능'];
  const calls = (state.calls || []).filter(c=>c.status === 'running');
  const pending = calls.map(c=>c.agent === 'main' ? '메인' : c.agent.replace('monitor-', '감시 '));
  const detail = pending.length ? [...new Set(pending)].join(', ') + ' 응답 대기' : (state.phase || '작업 처리 중');
  return [labels[state.status] || state.status, state.status === 'waiting' ? '인간 답변 필요 · ' + detail : detail];
}
function controls() {
  const [status, hint] = executionDisplay(currentRun, online, apiConnected);
  $('execution-status').textContent = status;
  $('execution-hint').textContent = hint;
  const running = currentRun && activeStates.includes(currentRun.status);
  const testing = currentRun && currentRun.test.status === 'running';
  const resumable = currentRun?.mode === 'openai' && ['paused', 'interrupted', 'failed'].includes(currentRun.status);
  $('resume-run').hidden = !resumable;
  $('resume-run').disabled = !online || busy || !resumable || !apiConnected;
  const solo = $('architecture').value === 'main-only';
  for (const id of fields) $(id).disabled = !!running || (solo && monitorFields.includes(id));
  $('baseline-preset').disabled = !!running;
  $('observations').hidden = currentRun?.config ? currentRun.config.monitors.length === 0 : solo;
  if (!currentRun) $('score-value').textContent = '— / ' + taskInfo[$('task-id').value].total;
  $('start-run').disabled = !online || busy || running || testing || ($('run-mode').value === 'openai' && !apiConnected);
  $('api-key').disabled = !online || busy || running;
  $('connect-api').disabled = !online || busy || running;
  $('disconnect-api').disabled = !online || busy || running || !apiConnected;
  $('refresh-models').disabled = !online || busy || running || !apiConnected;
  $('stop-run').disabled = !online || busy || !running;
  $('test-project').disabled = !online || busy || !currentRun || currentRun.status !== 'completed' || testing;
  $('download-run').disabled = !currentRun;
  $('download-code').disabled = !currentRun || !currentRun.artifact;
  const request = currentRun?.requests.find(r => r.id === selectedRequest);
  const canAnswer = online && !busy && (running || resumable) && acceptsAnswer(request);
  $('submit-answer').disabled = !canAnswer;
  $('human-answer').disabled = !canAnswer;
  for (const input of $('answer-fields').querySelectorAll('input,select,textarea')) input.disabled = !canAnswer;
}
function pendingSelection(requests, selected) {
  const current = requests.find(r => r.id === selected);
  if (acceptsAnswer(current)) return selected;
  return requests.find(acceptsAnswer)?.id || current?.id || null;
}
function answerForm() {
  const request = currentRun?.requests.find(r => r.id === selectedRequest);
  if (!request) {
    $('selected-question').textContent = '요청 없음';
    $('answer-fields').replaceChildren();
    formRequest = null;
    return;
  }
  const needsExample = request.status === 'needs_example';
  $('selected-question').textContent = request.question + (needsExample ?
    (request.clarification ? ' · ' + request.clarification :
     ' · 기존 답변 아래에 “검사 예약후경과초 시작까지남은초 허용/거부” 형식으로 해당 답을 확인할 사례를 추가하세요. 예: 검사 100000 172800 허용. 코드 변경이 없는 설명이면 “맥락만”을 입력하세요.') : '');
  const formKey = request.id + (needsExample ? '-example' : '');
  if (formRequest !== formKey) {
    $('answer-fields').replaceChildren();
    $('human-answer').value = '';
    for (const field of request.fields) {
      const label = document.createElement('label');
      label.textContent = field.label;
      const input = document.createElement(field.type === 'boolean' ? 'select' : field.type === 'text' ? 'textarea' : 'input');
      input.id = 'policy-' + field.name;
      input.dataset.field = field.name;
      input.required = !['dates', 'weekdays'].includes(field.type);
      if (field.type === 'boolean') {
        for (const [value, text] of [['','선택'],['true','예'],['false','아니요']]) {
          const option = document.createElement('option'); option.value = value; option.textContent = text; input.append(option);
        }
      } else if (field.type === 'text') {
        input.rows = 3; input.maxLength = 12000;
      } else {
        input.type = ['dates', 'weekdays'].includes(field.type) ? 'text' : field.type;
        if (field.type === 'number') { input.min = field.min; input.max = field.max; input.step = '1'; }
        if (field.type === 'time') input.step = '1';
      }
      if (request.answer) {
        const value = request.answer[field.name];
        input.value = Array.isArray(value) ? value.join(', ') : String(value);
      }
      label.append(input); $('answer-fields').append(label);
    }
    formRequest = formKey;
  }
}
function diagnosticText(state) {
  const records = state.diagnostics || [];
  if (!records.length) return state.last_error ? state.last_error + '\n이전 버전 기록: 실패 응답 원문과 상세 조건이 저장되지 않아 복원할 수 없습니다.' : '';
  return records.slice(-10).reverse().map(error => {
    const call = (state.calls || []).find(c => c.id === error.call_id);
    const agent = error.agent === 'main' ? '메인' : error.agent.replace('monitor-', '감시 ');
    const lines = [new Date(error.at).toLocaleString('ko-KR', {timeZone:'Asia/Seoul',hour12:false}),
      agent + ' · ' + (error.model || '모델 정보 없음') + ' · 코드 v' + error.code_version,
      '작업: ' + error.action + ' / 단계: ' + error.stage + ' / 경과: ' + (error.elapsed_ms ?? '?') + 'ms',
      error.exception_type + ': ' + error.message];
    if (error.ignored) lines.push('이전 호출의 늦은 오류: 현재 실행에는 반영하지 않음');
    if (Object.keys(error.details || {}).length) lines.push('실패 조건:\n' + JSON.stringify(error.details,null,2));
    if (error.response_id) lines.push('응답 ID: ' + error.response_id);
    lines.push('모델 응답:\n' + (call && 'output' in call ? JSON.stringify(call.output,null,2) : call?.raw_response ? JSON.stringify(call.raw_response,null,2) : '저장된 응답 없음 (요청 실패 등)'));
    if (error.trace?.length) lines.push('발생 위치:\n' + error.trace.map(f=>f.file+':'+f.line+' '+f.function).join('\n'));
    return lines.join('\n');
  }).join('\n\n────────\n\n');
}
function renderReviewHistory(state) {
  const reviews = state.review_log || [];
  $('review-history').hidden = !reviews.length;
  $('review-entries').replaceChildren();
  for (const review of reviews) {
    const row = document.createElement('div');
    const delivery = review.delivered_version ? '메인 v' + review.delivered_version + '에 전달' : '메인 전달 대기';
    row.textContent = '감시 ' + review.monitor_id + ' · v' + review.version + ' · ' + delivery + ' — ' + review.reason;
    for (const request of review.requests) row.append(document.createTextNode(' · ' + request.question));
    for (const id of review.request_ids || []) {
      const linked = state.requests.find(r => r.id === id);
      if (!linked) continue;
      const status = linked.verified_version ? 'v' + linked.verified_version + ' 검사 통과' : statusLabels[linked.status] || linked.status;
      row.append(document.createTextNode(' · 담당자 ' + (linked.answer?.text || '답변 대기') + ' (' + status + ')'));
    }
    if (review.checks.length) {
      const details = document.createElement('details');
      const title = document.createElement('summary'); title.textContent = '제안한 검사 ' + review.checks.length + '건';
      const body = document.createElement('pre'); body.textContent = JSON.stringify(review.checks, null, 2);
      details.append(title, body); row.append(details);
    }
    const noteKey = 'note_' + review.id.slice(0,32);
    if (!state.requests.some(r => r.key === noteKey) && (activeStates.includes(state.status) || ['paused','failed','interrupted'].includes(state.status))) {
      const button = document.createElement('button');
      button.type = 'button'; button.textContent = '이 의견에 답변 연결';
      button.addEventListener('click', () => operation(async () => {
        const updated = await api('/api/runs/' + state.id + '/reviews/' + review.id + '/request', {});
        selectedRequest = updated.requests.find(r => r.key === noteKey).id;
        render(updated);
      }));
      row.append(button);
    }
    $('review-entries').append(row);
  }
}

function render(state) {
  currentRun = state;
  if (!state) { controls(); return; }
  if (lastRevision === state.id + ':' + state.revision) { controls(); return; }
  lastRevision = state.id + ':' + state.revision;
  const runTask = taskInfo[state.config.task_id || 'cancellation'];
  $('run-task').textContent = runTask.name + ' · ' + runTask.total + (runTask.total === 150 ? '세트' : '문항');
  $('run-configuration').textContent = state.config.mainAgent.model + ' · 검토자 ' + state.config.monitors.length + '명';
  const detail = diagnosticText(state);
  $('error-details').hidden = !detail;
  $('error-detail-text').textContent = detail;
  $('run-phase').textContent = state.phase + (['failed','interrupted','stopped'].includes(state.status) ? ' · ' + statusLabels[state.status] : '');
  $('active-tasks').textContent = state.tasks.filter(t => ['running','pending'].includes(t.status)).map(t => t.name).join(', ') || '없음';
  $('blocked-tasks').textContent = state.tasks.filter(t => t.status === 'blocked').map(t => t.name).join(', ') || '없음';
  $('code-version').textContent = 'v' + state.code_version;
  $('shared-goal').textContent = state.config.project.name;
  $('shared-plan').textContent = state.plan.join(' → ');
  $('shared-assumptions').textContent = (state.assumptions || state.requests.filter(r => r.status === 'waiting').map(r => r.key)).join(', ') || '없음';
  $('shared-decisions').textContent = state.decisions.map(d => d.key).join(', ') || '없음';
  $('shared-tests').textContent = state.test.report ? state.test.report.score + '/' + state.test.report.total : statusLabels[state.test.status] || state.test.status;
  for (const monitor of state.monitors) {
    $('monitor-name-' + monitor.id).textContent = state.config.monitors.find(m => m.id === monitor.id).concept;
    $('monitor-state-' + monitor.id).textContent = monitor.status === 'observing' ? '관찰 중' : decisionLabels[monitor.decision] || (monitor.status === 'idle' ? '관찰 전' : '오류');
    $('monitor-state-' + monitor.id).title = monitor.reason || '';
  }
  $('request-count').textContent = state.requests.length + '건';
  renderReviewHistory(state);
  $('request-rows').replaceChildren();
  for (const request of state.requests) {
    const tr = document.createElement('tr');
    const first = document.createElement('td');
    const button = document.createElement('button'); button.textContent = request.id.slice(0,6);
    button.type = 'button';
    button.addEventListener('click', () => { selectedRequest = request.id; answerForm(); controls(); });
    first.append(button); tr.append(first);
    for (const text of [request.sources.map(s => s === 'main' ? '메인' : '감시 ' + s).join(', '), request.question + ' ' + request.reason,
      request.affected_tasks.join(', '), request.priority === 'high' ? '높음' : '보통',
      request.verified_version === state.code_version && request.verified_version ? '확정 사례 통과' :
      request.status === 'needs_example' ? (request.clarification ? '배정 조건 추가 질문' : '담당자 검사 예시 필요') : request.status === 'check_failed' ? '확정 사례 실패' :
      request.status === 'applied' && state.mode === 'openai' ? '코드 반영 보고' : statusLabels[request.status] || request.status]) {
      const td = document.createElement('td'); td.textContent = text; tr.append(td);
    }
    $('request-rows').append(tr);
  }
  if (!state.requests.length) {
    const row = document.createElement('tr'), td = document.createElement('td'); td.colSpan=6; td.textContent='없음'; row.append(td); $('request-rows').append(row);
  }
  selectedRequest = pendingSelection(state.requests, selectedRequest);
  answerForm();
  $('decision-record').textContent = state.decisions.length + '건';
  $('applied-version').textContent = state.requests.filter(r => r.applied_version).map(r => r.key + ': v' + r.applied_version).join(', ') || '없음';
  $('verification-result').textContent = state.verification ? (state.verification.type === 'syntax_and_public_checks' ?
    (state.verification.error || ({unverified:'미검증', failed:'검사 실패', passed:'검사 통과'}[state.verification.status]) || '자체 검증') + ' ' + state.verification.correct + '/' + state.verification.total : '정책 값·문법 확인') + ' (v' + state.verification.code_version + ')' : '없음';
  const failedChecks = (state.verification?.results || []).filter(row => !row.passed);
  $('failed-checks').hidden = !failedChecks.length;
  $('failed-check-list').textContent = failedChecks.map(row => {
    const source = row.request_id ? '담당자 답변 ' + row.request_id.slice(0, 6) : row.monitor_id ? '감시 ' + row.monitor_id : '메인';
    const describe = value => typeof value === 'boolean' ? (value ? '허용' : '거부') : JSON.stringify(value);
    const input = row.input || {now:row.now, booked_at:row.booked_at, starts_at:row.starts_at};
    return source + ' · ' + JSON.stringify(input) + '\n기대 ' + describe(row.expected) + ' / 실제 ' + (row.error || describe(row.actual));
  }).join('\n\n');
  $('test-status').textContent = state.test.error || statusLabels[state.test.status] || state.test.status;
  $('score-value').textContent = state.test.report ? state.test.report.score + ' / ' + state.test.report.total : '— / ' + runTask.total;
  if (state.test.report) $('score-value').textContent += ' (' + state.test.report.accuracy_percent + '%)';
  $('test-details').hidden = !state.test.report;
  $('category-scores').replaceChildren();
  if (state.test.report) for (const [name, score] of Object.entries(state.test.report.categories)) {
    const p = document.createElement('p'); p.textContent = name + ': ' + score.correct + '/' + score.total; $('category-scores').append(p);
  }
  for (const [key, label] of Object.entries({event_results:'사건별 결과',final_state:'최종 상태',notifications:'알림'})) {
    const score = state.test.report?.components?.[key];
    if (score) {const p=document.createElement('p'); p.textContent=label+': '+score.correct+'/'+score.total; $('category-scores').append(p);}
  }
  $('event-log').replaceChildren();
  for (const event of state.events.slice(-100)) {
    const li = document.createElement('li');
    li.textContent = new Date(event.at).toLocaleTimeString('ko-KR', {timeZone:'Asia/Seoul',hour12:false}) + ' [' + event.source + '] ' + event.message;
    $('event-log').append(li);
  }
  controls();
}
async function operation(action) {
  if (busy) return;
  operationVersion += 1;
  busy = true; controls(); $('operation-status').textContent = '';
  try { await action(); } catch (error) { $('operation-status').textContent = error.message; }
  finally { busy = false; controls(); }
}
$('start-run').addEventListener('click', () => {
  if (!validInputs()) return;
  operation(async () => { selectedRequest = null; formRequest = null; render(await api('/api/runs', readConfiguration())); });
});
$('stop-run').addEventListener('click', () => operation(async () => render(await api('/api/runs/' + currentRun.id + '/stop', {}))));
$('resume-run').addEventListener('click', () => operation(async () => render(await api('/api/runs/' + currentRun.id + '/resume', {}))));
$('test-project').addEventListener('click', () => operation(async () => render(await api('/api/runs/' + currentRun.id + '/test', {}))));
$('human-form').addEventListener('submit', event => {
  event.preventDefault();
  const request = currentRun?.requests.find(r => r.id === selectedRequest);
  if (!acceptsAnswer(request) || !$('human-form').reportValidity()) return;
  const answer = {};
  for (const field of request.fields) {
    const value = $('policy-' + field.name).value;
    answer[field.name] = field.type === 'boolean' ? value === 'true' : field.type === 'number' ? Number(value) :
      field.type === 'dates' ? value.split(',').map(x => x.trim()).filter(Boolean) :
      field.type === 'weekdays' ? value.split(',').map(x => x.trim()).filter(Boolean).map(Number) : value;
  }
  operation(async () => {
    const state = await api('/api/runs/' + currentRun.id + '/requests/' + request.id + '/answer', {answer, note:$('human-answer').value});
    selectedRequest = state.requests.find(acceptsAnswer)?.id || request.id;
    render(state);
  });
});
function download(data, name, type) {
  const url = URL.createObjectURL(new Blob([data], {type}));
  const link = document.createElement('a'); link.href=url; link.download=name; link.click();
  setTimeout(() => URL.revokeObjectURL(url),1000);
}
$('download-run').addEventListener('click', () => { if(currentRun) download(JSON.stringify(currentRun,null,2),'run-'+currentRun.id+'.json','application/json'); });
$('download-code').addEventListener('click', () => { if(currentRun?.artifact) download(currentRun.artifact.code,currentRun.artifact.filename,'text/x-python'); });
function showConnection(connection) {
  apiConnected = connection.connected;
  const models = [...new Set(connection.models)].sort();
  $('api-status').textContent = apiConnected ? '연결됨 · 지원 모델 ' + models.length + '개' : '미연결';
  const signature = JSON.stringify([apiConnected, models]);
  if (signature !== modelList) {
    modelList = signature;
    availableModels = models;
    modelsConnected = apiConnected;
    fillModelOptions();
  }
  controls();
}
$('run-mode').addEventListener('change', controls);
$('api-form').addEventListener('submit', event => {
  event.preventDefault();
  if (!$('api-key').value.trim()) { $('api-status').textContent = '키를 입력하세요.'; return; }
  operation(async () => {
    let key = $('api-key').value.trim();
    $('api-key').value = '';
    $('api-status').textContent = '연결 확인 중';
    try { showConnection(await api('/api/connection', {key})); }
    catch (error) { $('api-status').textContent = '연결 실패'; throw error; }
    finally { key = ''; }
  });
});
$('disconnect-api').addEventListener('click', () => operation(async () => showConnection(await api('/api/connection/disconnect', {}))));
$('refresh-models').addEventListener('click', () => operation(async () => showConnection(await api('/api/connection/refresh', {}))));
async function poll() {
  const version = operationVersion;
  try {
    const [state, connection] = await Promise.all([api('/api/runs/latest'), api('/api/connection')]);
    online = true;
    $('connection-status').textContent = state ? (state.mode === 'openai' ? 'OpenAI API' : '모의 실행') : '서버 연결됨';
    if (!busy && version === operationVersion) {
      showConnection(connection);
      if (state && state.id !== currentRun?.id) { restoreConfiguration(state.config); selectedRequest = null; formRequest = null; }
      render(state);
    }
  } catch { online = false; $('connection-status').textContent = '서버 연결 끊김'; controls(); }
  setTimeout(poll, 800);
}
if (location.protocol === 'http:' || location.protocol === 'https:') poll();
else { $('connection-status').textContent = '서버에서 열기: localhost:8000'; controls(); }
