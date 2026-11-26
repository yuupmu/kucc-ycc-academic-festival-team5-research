"use strict";
const $ = id => document.getElementById(id);
const ids = [1, 2, 3];
const labels = { idle: "대기", running: "검토 중 (데모)", waiting: "답변 대기", resuming: "응답 처리 중 (데모)", completed: "완료 (데모)", stopped: "중단", error: "오류" };
let activeRun = null;
let generation = 0;
let events = [];

function lockSettings(locked) {
  $("start").disabled = locked;
  $("stop").disabled = !locked;
  $("worker-model").disabled = locked;
  for (const id of ids) for (const field of ["concept", "instructions", "model"]) $(field + "-" + id).disabled = locked;
}
function log(event) {
  events.push(event);
  const row = document.createElement("li");
  const time = document.createElement("time");
  time.dateTime = event.at;
  time.textContent = new Date(event.at).toLocaleTimeString("ko-KR", { hour12: false, timeZone: "Asia/Seoul" });
  const text = document.createElement("span");
  text.textContent = `${event.branchId ? "[감시 " + event.branchId + "] " : ""}${event.message}`;
  row.append(time, text);
  $("log").append(row);
  $("log").scrollTop = $("log").scrollHeight;
  $("log-empty").hidden = true;
  $("download").disabled = false;
}
function render(snapshot) {
  const complete = snapshot.branches.filter(branch => branch.state === "completed").length;
  $("completed-count").textContent = `${complete} / 3 완료`;
  const finished = ["completed", "stopped", "error"].includes(snapshot.outcome);
  lockSettings(!finished);
  $("run-state").textContent = snapshot.outcome === "completed" ? "세 분기 데모 완료" : snapshot.outcome === "stopped" ? "중단됨" : snapshot.outcome === "error" ? "오류" : "세 분기 병렬 진행 (데모)";
  for (const branch of snapshot.branches) {
    const id = branch.id;
    $("branch-state-" + id).textContent = labels[branch.state];
    $("branch-concept-" + id).textContent = branch.config.concept;
    $("question-" + id).textContent = branch.question;
    $("answer-form-" + id).hidden = branch.state !== "waiting";
    $("branch-empty-" + id).hidden = branch.state === "waiting" || branch.answer !== null;
    $("branch-empty-" + id).textContent = labels[branch.state];
    $("answer-summary-" + id).hidden = branch.answer === null;
    $("answer-summary-" + id).textContent = branch.answer === null ? "" : "답변: " + branch.answer;
  }
  for (const id of ["a", "b", "c"]) $("state-" + id).textContent = finished ? "실제 작업 미연결" : id === "b" ? "독립 작업 진행 예시" : "감시 결과 대기 예시";
  $("merged-results").replaceChildren();
  if (snapshot.outcome === "completed") {
    $("merge-status").textContent = "3개 분기의 응답을 모았습니다. 실제 정책 판단·코드 반영은 미연결입니다.";
    for (const result of snapshot.mergedResults) {
      const item = document.createElement("li");
      item.textContent = `${result.concept}: ${result.answer}`;
      $("merged-results").append(item);
    }
  } else {
    $("merge-status").textContent = finished ? "실행이 중단되거나 실패하여 통합하지 않았습니다." : `${complete} / 3 분기 완료. 다른 분기의 답변과 무관하게 각 분기는 진행합니다.`;
  }
}
function reset() {
  generation += 1;
  if (activeRun) activeRun.stop();
  activeRun = null;
  events = [];
  lockSettings(false);
  $("run-state").textContent = "대기";
  $("completed-count").textContent = "0 / 3 완료";
  for (const id of ["a", "b", "c"]) $("state-" + id).textContent = "대기";
  for (const id of ids) {
    $("branch-state-" + id).textContent = "대기";
    $("branch-concept-" + id).textContent = $("concept-" + id).value;
    $("answer-form-" + id).hidden = true;
    $("answer-" + id).value = "";
    $("answer-" + id).setCustomValidity("");
    $("answer-summary-" + id).hidden = true;
    $("answer-summary-" + id).textContent = "";
    $("branch-empty-" + id).hidden = false;
    $("branch-empty-" + id).textContent = "실행 대기";
  }
  $("merge-status").textContent = "세 분기의 응답을 기다립니다.";
  $("merged-results").replaceChildren();
  $("log").replaceChildren();
  $("log-empty").hidden = false;
  $("download").disabled = true;
}
for (const id of ids) {
  for (const field of ["concept", "instructions", "answer"]) $(field + "-" + id).addEventListener("input", () => $(field + "-" + id).setCustomValidity(""));
  $("answer-form-" + id).addEventListener("submit", event => {
    event.preventDefault();
    const answer = $("answer-" + id).value.trim();
    if (!answer) { $("answer-" + id).setCustomValidity("답변을 입력하세요."); $("answer-" + id).reportValidity(); return; }
    if (activeRun && activeRun.answer(id, answer)) $("answer-form-" + id).hidden = true;
  });
}
$("settings").addEventListener("submit", event => {
  event.preventDefault();
  if (activeRun && activeRun.outcome === "running") return;
  for (const id of ids) for (const field of ["concept", "instructions"]) {
    const input = $(field + "-" + id);
    if (!input.value.trim()) { input.setCustomValidity("공백이 아닌 내용을 입력하세요."); input.reportValidity(); return; }
  }
  reset();
  const currentGeneration = generation;
  const configs = ids.map(id => ({ id, concept: $("concept-" + id).value.trim(), instructions: $("instructions-" + id).value.trim(), model: $("model-" + id).value }));
  const context = { task: "예약 취소 판정", workerModel: $("worker-model").value, workers: ["A: 취소 판정", "B: 목록 반영", "C: 알림 반영"], closedWeekdays: ["금", "토", "일"] };
  activeRun = new MonitorRun(configs, context, {
    onChange: snapshot => { if (generation === currentGeneration) render(snapshot); },
    onEvent: event => { if (generation === currentGeneration) log(event); }
  });
  log({ at: new Date().toISOString(), message: "감시 분기 3개를 병렬 시작합니다. 질문은 고정 예시이며 실제 GPT 호출은 없습니다." });
  activeRun.start().catch(error => {
    if (generation !== currentGeneration) return;
    lockSettings(false);
    $("run-state").textContent = "실행 오류";
    log({ at: new Date().toISOString(), message: String(error.message) });
  });
});
$("stop").addEventListener("click", () => { if (activeRun) activeRun.stop(); });
$("reset").addEventListener("click", reset);
$("download").addEventListener("click", () => {
  if (!activeRun) return;
  const url = URL.createObjectURL(new Blob([JSON.stringify({ ...activeRun.snapshot(), events }, null, 2)], { type: "application/json" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = "three-branch-demo.json";
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
