// 스캔 흐름: 진단기 연결 → 스캔하기 → 차량번호 조회 → 계획대로 명령 전송(응답·오류 기록) → 서버 해석·PDF 저장 → 결과 화면.
// 스캔하기 화면과 대시보드 카드가 같은 페이지의 연결(WecarObd.bindPanel)을 넘겨 mount한다.
(() => {
  "use strict";

  const RECONNECT_WAIT_MS = 20000;
  const CONSECUTIVE_TIMEOUT_LIMIT = 5;
  const P = window.WecarObdPlan;
  const STAGES = ["connect", "lookup", "scan", "analyze"];
  const CAR_FIELDS = [
    ["diag_company", "제조사"], ["diag_model", "모델"], ["diag_submodel", "세부모델"], ["diag_grade", "등급"],
    ["diag_year", "연식"], ["diag_registred_date", "최초 등록일"], ["diag_fuel", "연료"],
    ["diag_displacement", "배기량", " cc"], ["diag_mission", "변속기"], ["diag_color", "색상"],
    ["diag_car_id", "차대번호"],
  ];
  const STATUS_TEXT = { ok: "성공", timeout: "시간 초과", disconnected: "연결 끊김", skipped: "건너뜀" };

  function mount(root, link) {
    if (!root || !link || root.dataset.mounted) return null;
    root.dataset.mounted = "1";
    const config = JSON.parse(root.querySelector("[data-scan-config]").textContent);
    const q = (selector) => root.querySelector(selector);

    const stagesEl = q("[data-flow-stages]");
    const runBtn = q("[data-scan-run]");
    const stopBtn = q("[data-scan-stop]");
    const notice = q("[data-scan-notice]");
    const lookupBox = q("[data-lookup]");
    const form = q("[data-lookup-form]");
    const lookupStatus = q("[data-lookup-status]");
    const lookupResult = q("[data-lookup-result]");
    const lookupFailed = q("[data-lookup-failed]");
    const skipBtn = q("[data-lookup-skip]");
    const progress = q("[data-scan-progress]");
    const bar = q("[data-scan-bar]");
    const scanStatus = q("[data-scan-status]");
    const counts = q("[data-scan-counts]");
    const retryBtn = q("[data-scan-retry]");
    const logList = q("[data-scan-log]");
    const problemsBox = q("[data-comm-problems]");
    const problemsList = q("[data-comm-problems-list]");
    const problemsBanner = q("[data-comm-problems-banner]");

    const state = { carNo: "", car: null, lookupError: null, running: false, stop: false, pending: null,
      needConnect: false, consecutiveTimeouts: 0 };

    function clearProblems() {
      state.consecutiveTimeouts = 0;
      if (problemsList) problemsList.replaceChildren();
      if (problemsBox) problemsBox.hidden = true;
      if (problemsBanner) {
        problemsBanner.hidden = true;
        problemsBanner.textContent = "";
      }
    }

    function pushProblem(record) {
      if (!problemsBox || !problemsList || !record.error || record.error === "skipped") return;
      problemsBox.hidden = false;
      const item = document.createElement("li");
      const status = STATUS_TEXT[record.error] || record.error;
      const reply = (record.reply || "").replace(/[\r\n>]+/g, " ").replace(/\s+/g, " ").trim();
      const parts = [
        `${record.header ? `${record.header} ` : ""}${record.command || ""} · ${record.label || ""}`,
        `→ ${status}${record.reason ? ` — ${record.reason}` : ""}`,
        reply ? `원문: ${reply}` : "원문: (없음)",
        record.tMs != null ? `${record.tMs} ms` : "",
      ].filter(Boolean);
      item.className = "text-danger";
      item.textContent = parts.join(" · ");
      problemsList.append(item);
      problemsList.scrollTop = problemsList.scrollHeight;
      if (record.error === "timeout" || record.error === "disconnected") {
        state.consecutiveTimeouts += 1;
      } else {
        state.consecutiveTimeouts = 0;
      }
      if (problemsBanner && state.consecutiveTimeouts >= CONSECUTIVE_TIMEOUT_LIMIT) {
        problemsBanner.hidden = false;
        problemsBanner.textContent =
          `연속 ${state.consecutiveTimeouts}회 무응답·끊김. 진단기·시동을 확인하거나 '중지' 후 다시 연결하세요.`;
        if (state.consecutiveTimeouts === CONSECUTIVE_TIMEOUT_LIMIT) {
          state.stop = true;
          scanStatus.textContent = "연속 무응답으로 스캔을 중단합니다. 지금까지의 결과를 저장합니다.";
        }
      }
    }

    function stage(current, failed = false) {
      const index = STAGES.indexOf(current);
      stagesEl.querySelectorAll("[data-stage]").forEach((item, i) => {
        item.classList.remove("badge-ink", "badge-success", "badge-danger");
        if (i < index) item.classList.add("badge-success");
        else if (i === index) item.classList.add(failed ? "badge-danger" : "badge-ink");
        if (i === index) item.setAttribute("aria-current", "step");
        else item.removeAttribute("aria-current");
      });
    }

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
          ? "보안 토큰이 만료되었습니다. 화면을 새로고침하세요"
          : "서버 응답을 읽지 못했습니다" };
      }
      if (!response.ok) {
        const error = new Error(`${data.message || "요청 실패"} (HTTP ${response.status})`);
        error.data = data;
        throw error;
      }
      return data;
    }

    function renderCar(carNo, car, cached) {
      const rows = [["차량번호", carNo], ...CAR_FIELDS.map(([key, label, unit]) => {
        const value = car[key];
        return [label, value === null || value === undefined || value === "" ? "-" : `${value}${unit || ""}`];
      })];
      lookupResult.querySelector("dl").replaceChildren(...rows.flatMap(([label, value]) => {
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

    function idleNotice() {
      if (state.running) return;
      if (link.ready) {
        state.needConnect = false;
        notice.textContent = `진단기 자동 인식됨(${link.info.name || "이름 없음"}). '스캔하기'를 누르세요.`;
        stage("lookup");
      } else if (!state.needConnect) {
        notice.textContent = link.message
          || "시동을 켜고 진단기를 OBD2 단자에 꽂아 두세요. 인식되면 '스캔하기'를 누르세요.";
        stage("connect");
      }
    }

    link.addEventListener("status", idleNotice);
    idleNotice();

    runBtn.addEventListener("click", () => {
      if (state.running) return;
      if (!link.ready) {
        state.needConnect = true;
        if (link.ble.supported) link.find().catch(() => {});
        stage("connect", true);
        notice.textContent = "진단기가 연결되지 않았습니다. 진단기를 고르는 창에서 연결하세요(블루투스 클래식·USB는 위의 버튼).";
        return;
      }
      stage("lookup");
      lookupBox.hidden = false;
      notice.textContent = "차량번호를 입력하고 '차량번호 조회하기'를 누르세요. 조회가 끝나면 바로 스캔합니다.";
      if (form.elements.car_no.value.trim()) form.requestSubmit();
      else form.elements.car_no.focus();
    });

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (state.running) return;
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
      lookupFailed.hidden = true;
      try {
        const data = await post(config.lookupUrl, { carNo });
        Object.assign(state, { carNo: data.car_no, car: data.car, lookupError: null });
        renderCar(data.car_no, data.car, data.cached);
        lookupStatus.textContent = "조회했습니다. 차량 스캔을 시작합니다.";
        await scan();
      } catch (error) {
        if (state.running) return;
        const detail = error.data?.detail && !error.message.includes(error.data.detail) ? ` (원문: ${error.data.detail})` : "";
        Object.assign(state, { carNo, car: null, lookupError: `${error.message}${detail}` });
        lookupStatus.textContent = `조회 실패: ${error.message}${detail}`;
        lookupFailed.hidden = false;
        stage("lookup", true);
      } finally {
        button.disabled = false;
      }
    });

    skipBtn.addEventListener("click", () => scan());

    function logStep(record) {
      const item = document.createElement("li");
      let result;
      if (record.error) {
        result = (STATUS_TEXT[record.error] || record.error) + (record.reason ? ` — ${record.reason}` : "");
        if (record.reply) {
          result += ` · ${String(record.reply).replace(/[\r\n>]+/g, " ").replace(/\s+/g, " ").trim()}`;
        }
      } else {
        result = record.reply.replace(/[\r\n>]+/g, " ").replace(/\s+/g, " ").trim().slice(0, 80) || "빈 응답";
      }
      item.textContent = `${record.header ? `${record.header} ` : ""}${record.command} · ${record.label} → ${result}`;
      if (record.error && record.error !== "skipped") item.className = "text-danger";
      logList.append(item);
      logList.scrollTop = logList.scrollHeight;
      pushProblem(record);
      if (!record.error || record.error === "skipped") state.consecutiveTimeouts = 0;
    }

    // 주소 설정·오류 복구는 진단기 드라이버(obd-driver.js)가 명령 체계에 맞게 한다.
    async function runPlan(steps, results) {
      const started = performance.now();
      const ctx = P.newContext();
      const tally = { ok: 0, failed: 0, skipped: 0 };
      // 제어기 순회 진행(주소 수 기준). 응답한 제어기 수를 함께 보여 준다.
      const sweep = { total: steps.filter((s) => s.sweep && s.probe).length, done: 0, answered: 0 };
      const finish = (record) => {
        results.push(record);
        if (record.error === "skipped") tally.skipped += 1;
        else if (record.error) tally.failed += 1;
        else tally.ok += 1;
        counts.textContent = `응답 ${tally.ok} · 실패 ${tally.failed} · 건너뜀 ${tally.skipped}`;
        logStep(record);
      };
      for (const [index, step] of steps.entries()) {
        bar.value = Math.round((index / steps.length) * 100);
        if (step.sweep) {
          if (step.probe) sweep.done += 1;
          scanStatus.textContent = `제어기 순회 ${sweep.done}/${sweep.total} (응답 ${sweep.answered}) · ${step.label}`;
        } else {
          scanStatus.textContent = `${index + 1}/${steps.length} ${step.label} 읽는 중…`;
        }
        const base = { ...step, reply: null, error: null, reason: null, tMs: Math.round(performance.now() - started) };
        delete base.expand;
        delete base.pids;
        const reason = state.stop ? "사용자가 스캔을 중지했습니다." : P.skipReason(step, ctx);
        const planned = reason ? { items: [] } : P.requests(step, ctx);
        if (reason || !planned.items.length) {
          finish({ ...base, error: "skipped", reason: reason || planned.reason });
          continue;
        }
        const target = P.headerFor(step, ctx);
        for (const item of planned.items) {
          const record = { ...base, command: item.command, label: item.label, header: target };
          if (state.stop) {
            finish({ ...record, error: "skipped", reason: "사용자가 스캔을 중지했습니다." });
            continue;
          }
          if (!link.ready) {
            scanStatus.textContent = "진단기 연결이 끊겼습니다. 다시 연결되기를 기다리는 중…";
            const deadline = Date.now() + RECONNECT_WAIT_MS;
            if (!(await link.waitReady(() => state.stop || Date.now() > deadline))) record.error = "disconnected";
          }
          if (!record.error && !link.supports(item.command)) {
            finish({ ...record, error: "skipped", reason: "이 진단기의 명령 체계에서는 쓰지 않는 명령입니다." });
            continue;
          }
          if (!record.error) {
            try {
              if (step.delay_ms) await new Promise((r) => setTimeout(r, step.delay_ms));
              const reply = await link.request({
                header: target, command: item.command, timeoutMs: step.timeout, st: step.st || null,
                pendingRetries: step.pending_retries, session_fallback: step.session_fallback, group: step.group,
              });
              record.tMs = Math.round(performance.now() - started);
              if (reply.trim()) record.reply = reply;
              else record.error = link.ready ? "timeout" : "disconnected";
            } catch (error) {
              record.error = link.ready ? `단말기 오류: ${error.message}` : "disconnected";
            }
          }
          P.observe(step, item.command, record.reply, ctx);
          if (step.sweep && step.probe && record.reply && !/NO DATA|CAN ERROR|UNABLE/i.test(record.reply)) sweep.answered += 1;
          if (step.probe && target && !record.reply) ctx.dead.add(target);
          if (item.command === "ATDPN" && ctx.bus) link.rememberProtocol(record.reply);
          finish(record);
        }
      }
      bar.value = 100;
    }

    async function save() {
      stage("analyze");
      scanStatus.textContent = "결과를 분석하고 PDF와 함께 저장하는 중…";
      retryBtn.hidden = true;
      try {
        const saved = await post(config.runUrl, state.pending);
        scanStatus.textContent = saved.status === "ok"
          ? "분석을 마쳤습니다. 결과 화면으로 이동하고 PDF를 내려받습니다…"
          : "분석을 마쳤지만 오류가 있습니다. 결과 화면의 오류 기록을 확인하세요…";
        state.pending = null;
        window.location.assign(`${saved.url}?pdf=1`);
      } catch (error) {
        stage("analyze", true);
        scanStatus.textContent = `저장 실패: ${error.message}. '저장 다시 시도'를 누르세요.`;
        retryBtn.hidden = false;
      }
    }

    async function scan() {
      if (state.running) return;
      if (!link.ready) {
        stage("connect", true);
        notice.textContent = "진단기 연결이 끊겼습니다. 다시 연결한 뒤 '조회 없이 스캔 계속' 또는 '스캔하기'를 누르세요.";
        return;
      }
      if (!link.lock("scan")) {
        notice.textContent = "빠른 점검이 진단기를 쓰는 중입니다. 끝난 뒤 다시 누르세요.";
        return;
      }
      Object.assign(state, { running: true, stop: false, pending: null });
      runBtn.disabled = true;
      stopBtn.disabled = false;
      retryBtn.hidden = true;
      lookupFailed.hidden = true;
      progress.hidden = false;
      logList.replaceChildren();
      clearProblems();
      counts.textContent = "";
      bar.value = 0;
      stage("scan");
      notice.textContent = "차량을 스캔하는 중입니다. 시동을 끄거나 진단기를 뽑지 마세요.";
      const results = [];
      let clientError = null;
      try {
        scanStatus.textContent = "스캔 계획을 받는 중…";
        // 고장코드 지우기는 저장한 스캔의 결과 화면에서 따로 한다(읽기 스캔은 지우지 않음).
        const plan = await post(config.planUrl, { car: state.car });
        await runPlan(plan.steps, results);
      } catch (error) {
        clientError = `${results.length ? `${results.length}번째 단계 뒤 ` : ""}스캔이 중단되었습니다: ${error.message}`;
      } finally {
        link.unlock("scan");
      }
      try {
        if (!results.length) {
          stage("scan", true);
          scanStatus.textContent = clientError || "보낸 명령이 없습니다.";
          return;
        }
        state.pending = {
          carNo: state.carNo || form.elements.car_no.value.replace(/\s+/g, ""), car: state.car, steps: results,
          transport: link.transport, device: link.info.name || "", dialect: link.dialect, lookupError: state.lookupError,
          clientError,
        };
        notice.textContent = "스캔을 마쳤습니다. 결과를 분석합니다.";
        await save();
      } finally {
        state.running = false;
        runBtn.disabled = false;
        stopBtn.disabled = true;
      }
    }

    stopBtn.addEventListener("click", () => {
      state.stop = true;
      scanStatus.textContent = "중지하는 중… 남은 단계는 건너뛰고 지금까지의 결과를 저장합니다.";
    });
    retryBtn.addEventListener("click", save);

    return {
      start() {
        runBtn.click();
      },
    };
  }

  window.WecarScanFlow = { mount };

  const page = document.getElementById("scanner");
  const obdConfig = window.WecarObd?.readConfig();
  if (page && obdConfig) {
    mount(page.querySelector("[data-scan-flow]"), window.WecarObd.bindPanel(page.querySelector("[data-obd-panel]"), obdConfig));
  }
})();
