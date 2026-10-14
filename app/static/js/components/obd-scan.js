// 스캔하기 화면: 차량번호 조회 → 진단기 연결 → 계획대로 명령 전송(응답·오류 기록) → 서버 해석·저장 → 결과 화면.
(() => {
  "use strict";

  const configNode = document.getElementById("scanner-config");
  const root = document.getElementById("scanner");
  const obdConfig = window.WecarObd?.readConfig();
  if (!configNode || !root || !obdConfig) return;
  const config = JSON.parse(configNode.textContent);
  const link = window.WecarObd.bindPanel(root.querySelector("[data-obd-panel]"), obdConfig);
  const q = (selector) => root.querySelector(selector);

  const form = q("[data-lookup-form]");
  const lookupStatus = q("[data-lookup-status]");
  const lookupResult = q("[data-lookup-result]");
  const lookupWarning = q("[data-lookup-warning]");
  const startSection = q("[data-scan-start]");
  const runBtn = q("[data-scan-run]");
  const stopBtn = q("[data-scan-stop]");
  const retryBtn = q("[data-scan-retry]");
  const progress = q("[data-scan-progress]");
  const bar = q("[data-scan-bar]");
  const scanStatus = q("[data-scan-status]");
  const counts = q("[data-scan-counts]");
  const logList = q("[data-scan-log]");

  const RECONNECT_WAIT_MS = 20000;
  const BROADCAST = { can11: "7DF", can29: "18DB33F1" };
  const BUS = { 1: "serial", 2: "serial", 3: "serial", 4: "serial", 5: "serial", 6: "can11", 7: "can29",
    8: "can11", 9: "can29", A: "can29", B: "can11", C: "can11" };
  const CAR_FIELDS = [
    ["diag_company", "제조사"], ["diag_model", "모델"], ["diag_submodel", "세부모델"], ["diag_grade", "등급"],
    ["diag_year", "연식"], ["diag_registred_date", "최초 등록일"], ["diag_fuel", "연료"],
    ["diag_displacement", "배기량", " cc"], ["diag_mission", "변속기"], ["diag_color", "색상"],
    ["diag_car_id", "차대번호"],
  ];
  const STATUS_TEXT = { ok: "성공", timeout: "시간 초과", disconnected: "연결 끊김", skipped: "건너뜀" };

  const state = { carNo: "", car: null, lookupError: null, running: false, stop: false, pending: null };

  async function post(url, body) {
    const response = await fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": form.elements.csrf_token.value },
      body: JSON.stringify(body),
    });
    let data;
    try {
      data = await response.json();
    } catch {
      data = { message: response.status === 400
        ? "보안 토큰이 만료되었습니다. 화면을 새로고침하세요."
        : `서버 응답을 읽지 못했습니다(HTTP ${response.status}).` };
    }
    if (!response.ok) {
      const error = new Error(data.message || `HTTP ${response.status}`);
      error.data = data;
      throw error;
    }
    return data;
  }

  function renderCar(carNo, car, cached) {
    const list = lookupResult.querySelector("dl");
    const rows = [["차량번호", carNo], ...CAR_FIELDS.map(([key, label, unit]) => {
      const value = car[key];
      return [label, value === null || value === undefined || value === "" ? "-" : `${value}${unit || ""}`];
    })];
    list.replaceChildren(...rows.flatMap(([label, value]) => {
      const dt = document.createElement("dt");
      dt.textContent = label;
      const dd = document.createElement("dd");
      dd.textContent = value;
      return [dt, dd];
    }));
    lookupResult.querySelector("[data-lookup-cache]").textContent = cached
      ? "저장된 조회 결과를 썼습니다(일일 조회 한도 절약)."
      : "차량정보 조회 API에서 새로 받았습니다.";
    lookupResult.hidden = false;
  }

  function updateRunButton() {
    runBtn.disabled = state.running || !link.ready || !state.carNo;
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const carNo = form.elements.car_no.value.replace(/\s+/g, "");
    if (!carNo) {
      lookupStatus.textContent = "차량번호를 입력하세요.";
      form.elements.car_no.focus();
      return;
    }
    const button = form.querySelector("[type=submit]");
    button.disabled = true;
    lookupStatus.textContent = "차량 정보를 조회하는 중…";
    lookupResult.hidden = true;
    lookupWarning.hidden = true;
    try {
      const data = await post(config.lookupUrl, { carNo });
      Object.assign(state, { carNo: data.car_no, car: data.car, lookupError: null });
      renderCar(data.car_no, data.car, data.cached);
      lookupStatus.textContent = "조회했습니다. 진단기를 연결하고 '스캔하기'를 누르세요.";
    } catch (error) {
      const detail = error.data?.detail && error.data.detail !== error.message ? ` (원문: ${error.data.detail})` : "";
      Object.assign(state, { carNo, car: null, lookupError: `${error.message}${detail}` });
      lookupStatus.textContent = `조회 실패: ${error.message}${detail}`;
      lookupWarning.hidden = false;
    } finally {
      button.disabled = false;
      startSection.hidden = false;
      updateRunButton();
    }
  });

  link.addEventListener("status", updateRunButton);

  function busOf(reply) {
    const tokens = (reply || "").toUpperCase().split(/[\s>]+/).reverse();
    const token = tokens.find((t) => /^A?[1-9A-C]$/.test(t));
    return token ? BUS[token.slice(-1)] : null;
  }

  function logStep(record) {
    const item = document.createElement("li");
    const result = record.error
      ? (STATUS_TEXT[record.error] || record.error) + (record.reason ? ` — ${record.reason}` : "")
      : record.reply.replace(/[\r\n>]+/g, " ").replace(/\s+/g, " ").trim().slice(0, 80) || "빈 응답";
    item.textContent = `${record.header ? `${record.header} ` : ""}${record.command} · ${record.label} → ${result}`;
    if (record.error && record.error !== "skipped") item.className = "text-danger";
    logList.append(item);
    logList.scrollTop = logList.scrollHeight;
  }

  async function runPlan(steps) {
    const started = performance.now();
    const results = [];
    const dead = new Set();
    const tally = { ok: 0, failed: 0, skipped: 0 };
    let header = null;
    let bus = null;
    for (const [index, step] of steps.entries()) {
      bar.value = Math.round((index / steps.length) * 100);
      scanStatus.textContent = `${index + 1}/${steps.length} ${step.label} 읽는 중…`;
      const record = { ...step, reply: null, error: null, reason: null, tMs: Math.round(performance.now() - started) };
      const skip = (reason) => Object.assign(record, { error: "skipped", reason });
      if (state.stop) skip("사용자가 스캔을 중지했습니다.");
      else if (step.header && dead.has(step.header)) skip(`${step.header} 제어기가 응답하지 않아 건너뛰었습니다.`);
      else if (step.bus === "can" && bus === "serial") skip("K-Line·J1850 차량이라 CAN 전용 조회를 건너뛰었습니다.");
      else if (step.header && step.header.length === 3 && bus === "can29") {
        skip("29비트 CAN 차량이라 11비트 주소 조회를 건너뛰었습니다.");
      } else {
        if (!link.ready) {
          scanStatus.textContent = "진단기 연결이 끊겼습니다. 다시 연결되기를 기다리는 중…";
          const deadline = Date.now() + RECONNECT_WAIT_MS;
          const back = await link.waitReady(() => state.stop || Date.now() > deadline);
          header = null;
          if (!back) record.error = "disconnected";
        }
        if (!record.error) {
          try {
            const want = step.header || (header ? BROADCAST[bus] || "7DF" : null);
            if (want && want !== header) {
              if (want.length === 8) {
                await link.send(`ATCP${want.slice(0, 2)}`);
                await link.send(`ATSH${want.slice(2)}`);
              } else {
                await link.send(`ATSH${want}`);
              }
              header = want;
            }
            const reply = await link.send(step.command, step.timeout);
            record.tMs = Math.round(performance.now() - started);
            if (reply.trim()) record.reply = reply;
            else record.error = link.ready ? "timeout" : "disconnected";
          } catch (error) {
            header = null;
            record.error = link.ready ? `단말기 오류: ${error.message}` : "disconnected";
          }
        }
        if (step.command === "ATDPN" && record.reply) bus = busOf(record.reply);
        if (step.probe && step.header && (!record.reply || /NO DATA|CAN ERROR|UNABLE/i.test(record.reply))) {
          dead.add(step.header);
        }
      }
      results.push(record);
      if (record.error === "skipped") tally.skipped += 1;
      else if (record.error) tally.failed += 1;
      else tally.ok += 1;
      counts.textContent = `응답 ${tally.ok} · 실패 ${tally.failed} · 건너뜀 ${tally.skipped}`;
      logStep(record);
    }
    bar.value = 100;
    return results;
  }

  async function save() {
    scanStatus.textContent = "결과를 해석하고 저장하는 중…";
    retryBtn.hidden = true;
    try {
      const saved = await post(config.runUrl, state.pending);
      scanStatus.textContent = saved.status === "ok"
        ? "스캔을 마쳤습니다. 결과 화면으로 이동합니다…"
        : "스캔을 마쳤지만 오류가 있습니다. 결과 화면의 오류 기록을 확인하세요…";
      state.pending = null;
      window.location.assign(saved.url);
    } catch (error) {
      scanStatus.textContent = `저장 실패: ${error.message}. '저장 다시 시도'를 누르세요.`;
      retryBtn.hidden = false;
    }
  }

  async function scan() {
    if (!link.ready || state.running) return;
    Object.assign(state, { running: true, stop: false, pending: null });
    updateRunButton();
    stopBtn.disabled = false;
    retryBtn.hidden = true;
    progress.hidden = false;
    logList.replaceChildren();
    counts.textContent = "";
    bar.value = 0;
    try {
      scanStatus.textContent = "스캔 계획을 받는 중…";
      const plan = await post(config.planUrl, { car: state.car });
      const steps = await runPlan(plan.steps);
      state.pending = {
        carNo: state.carNo, car: state.car, steps, transport: link.transport,
        device: link.info.name || "", lookupError: state.lookupError,
      };
      await save();
    } catch (error) {
      scanStatus.textContent = `스캔 실패: ${error.message}`;
    } finally {
      state.running = false;
      stopBtn.disabled = true;
      updateRunButton();
    }
  }

  runBtn.addEventListener("click", scan);
  stopBtn.addEventListener("click", () => {
    state.stop = true;
    scanStatus.textContent = "중지하는 중… 남은 단계는 건너뛰고 지금까지의 결과를 저장합니다.";
  });
  retryBtn.addEventListener("click", save);
  if (form.elements.car_no.value) form.requestSubmit();
})();
