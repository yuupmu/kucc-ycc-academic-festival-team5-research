"use strict";

// Independent local demo branches; no LLM requests or policy decisions.
(() => {
  const copy = value => JSON.parse(JSON.stringify(value));
  const questions = [
    "예시 질문: 예약 시작 몇 시간 전까지 취소할 수 있고, 정확한 마감 시각도 포함하나요?",
    "예시 질문: 취소 마감이 금·토·일 또는 추가 휴일에 걸리면 언제로 조정하나요?",
    "예시 질문: 예약 직후 취소 유예가 있나요? 이미 시작한 예약에도 적용하나요?"
  ];
  function wait(ms, signal) {
    return new Promise((resolve, reject) => {
      if (signal.aborted) return reject(new Error("stopped"));
      const abort = () => { clearTimeout(timer); reject(new Error("stopped")); };
      const timer = setTimeout(() => { signal.removeEventListener("abort", abort); resolve(); }, ms);
      signal.addEventListener("abort", abort, { once: true });
    });
  }
  class MonitorRun {
    constructor(configs, context, options = {}) {
      if (configs.length !== 3 || new Set(configs.map(c => c.id)).size !== 3) throw new Error("Three unique branches required");
      this.controller = new AbortController();
      this.pending = new Map();
      this.onChange = options.onChange || (() => {});
      this.onEvent = options.onEvent || (() => {});
      this.analysisDelay = options.analysisDelay ?? 500;
      this.resumeDelay = options.resumeDelay ?? 400;
      this.branches = configs.map((config, index) => ({ id: config.id, config: copy(config), context: copy(context),
        state: "idle", question: questions[index], answer: null, result: null, events: [] }));
      this.outcome = "idle";
      this.startedAt = null;
      this.finishedAt = null;
      this.mergedResults = [];
    }
    snapshot() {
      return copy({ mode: "three-branch-demo", startedAt: this.startedAt, finishedAt: this.finishedAt,
        outcome: this.outcome, branches: this.branches, mergedResults: this.mergedResults, score: null });
    }
    emit(branch, state, message) {
      branch.state = state;
      const event = { at: new Date().toISOString(), branchId: branch.id, state, message };
      branch.events.push(event);
      this.onEvent(copy(event));
      this.onChange(this.snapshot());
    }
    ask(branch) {
      return new Promise((resolve, reject) => {
        const signal = this.controller.signal;
        if (signal.aborted) return reject(new Error("stopped"));
        const abort = () => { this.pending.delete(branch.id); reject(new Error("stopped")); };
        signal.addEventListener("abort", abort, { once: true });
        this.pending.set(branch.id, answer => {
          signal.removeEventListener("abort", abort);
          this.pending.delete(branch.id);
          resolve(answer);
        });
        this.emit(branch, "waiting", branch.question);
      });
    }
    async execute(branch) {
      const signal = this.controller.signal;
      try {
        this.emit(branch, "running", `${branch.config.concept}: 독립 분기 시작 (데모)`);
        await wait(this.analysisDelay, signal);
        const answer = await this.ask(branch);
        if (signal.aborted) throw new Error("stopped");
        branch.answer = answer;
        this.emit(branch, "resuming", "이 분기의 답변을 기록하고 후속 처리 중 (데모)");
        await wait(this.resumeDelay, signal);
        branch.result = { branchId: branch.id, concept: branch.config.concept,
          instructions: branch.config.instructions, question: branch.question, answer, verification: "not-connected" };
        this.emit(branch, "completed", "분기 응답 기록 완료 · 코드 반영은 미연결");
        return branch.result;
      } catch (error) {
        this.emit(branch, signal.aborted ? "stopped" : "error", signal.aborted ? "분기 중단" : String(error.message));
        return null;
      }
    }
    async start() {
      if (this.outcome !== "idle") throw new Error("Run already started");
      this.outcome = "running";
      this.startedAt = new Date().toISOString();
      const results = await Promise.all(this.branches.map(branch => this.execute(branch)));
      this.outcome = this.controller.signal.aborted ? "stopped" : results.every(Boolean) ? "completed" : "error";
      this.mergedResults = this.outcome === "completed" ? results : [];
      this.finishedAt = new Date().toISOString();
      this.onChange(this.snapshot());
      return this.snapshot();
    }
    answer(id, text) {
      const branch = this.branches.find(item => item.id === id);
      const value = typeof text === "string" ? text.trim() : "";
      if (this.controller.signal.aborted || !branch || branch.state !== "waiting" || !value || !this.pending.has(id)) return false;
      this.pending.get(id)(value);
      return true;
    }
    stop() { this.controller.abort(); }
  }
  if (typeof module !== "undefined" && module.exports) module.exports = { MonitorRun };
  else globalThis.MonitorRun = MonitorRun;
})();
