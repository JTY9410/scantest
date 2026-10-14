// 스캔 흐름: 진단기 연결 → 스캔하기 → 차량번호 조회 → 계획대로 명령 전송(응답·오류 기록) → 서버 해석·PDF 저장 → 결과 화면.
// 스캔하기 화면과 대시보드 카드가 같은 페이지의 연결(WecarObd.bindPanel)을 넘겨 mount한다.
(() => {
  "use strict";

  const RECONNECT_WAIT_MS = 20000;
  const BROADCAST = { can11: "7DF", can29: "18DB33F1" };
  const BUS = { 1: "serial", 2: "serial", 3: "serial", 4: "serial", 5: "serial", 6: "can11", 7: "can29",
    8: "can11", 9: "can29", A: "can29", B: "can11", C: "can11" };
  const STAGES = ["connect", "lookup", "scan", "analyze"];
  const CAR_FIELDS = [
    ["diag_company", "제조사"], ["diag_model", "모델"], ["diag_submodel", "세부모델"], ["diag_grade", "등급"],
    ["diag_year", "연식"], ["diag_registred_date", "최초 등록일"], ["diag_fuel", "연료"],
    ["diag_displacement", "배기량", " cc"], ["diag_mission", "변속기"], ["diag_color", "색상"],
    ["diag_car_id", "차대번호"],
  ];
  const STATUS_TEXT = { ok: "성공", timeout: "시간 초과", disconnected: "연결 끊김", skipped: "건너뜀" };
  const SUPPORT_RANGE = /^01(00|20|40|60|80|A0|C0)$/;

  const byteTokens = (line) => line.trim().toUpperCase().split(/\s+/).filter((t) => /^[0-9A-F]{2}$/.test(t));

  // '41 <base> A B C D' 비트맵 → 지원 PID 번호. 여러 제어기가 답하면 합친다.
  function supportedFrom(reply, base) {
    const found = new Set();
    for (const line of (reply || "").split(/[\r\n]+/)) {
      const bytes = byteTokens(line);
      for (let i = 0; i + 5 < bytes.length; i += 1) {
        if (bytes[i] !== "41" || parseInt(bytes[i + 1], 16) !== base) continue;
        bytes.slice(i + 2, i + 6).forEach((value, k) => {
          for (let bit = 0; bit < 8; bit += 1) {
            if (parseInt(value, 16) & (0x80 >> bit)) found.add(base + k * 8 + bit + 1);
          }
        });
        break;
      }
    }
    return found;
  }

  // '41 01 A ...'의 A 하위 7비트 = 저장된 고장코드 수. 답이 없으면 null.
  function dtcCountFrom(reply) {
    let count = null;
    for (const line of (reply || "").split(/[\r\n]+/)) {
      const bytes = byteTokens(line);
      const i = bytes.findIndex((b, k) => b === "41" && bytes[k + 1] === "01");
      if (i >= 0 && bytes[i + 2]) count = (count || 0) + (parseInt(bytes[i + 2], 16) & 0x7f);
    }
    return count;
  }

  function busOf(reply) {
    const tokens = (reply || "").toUpperCase().split(/[\s>]+/).reverse();
    const token = tokens.find((t) => /^A?[1-9A-C]$/.test(t));
    return token ? BUS[token.slice(-1)] : null;
  }

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

    const state = { carNo: "", car: null, lookupError: null, running: false, stop: false, pending: null,
      needConnect: false };

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
        notice.textContent = `진단기 연결됨(${link.info.name || "이름 없음"}). '스캔하기'를 누르세요.`;
        stage("lookup");
      } else if (!state.needConnect) {
        notice.textContent = "시동을 켜고 진단기를 연결한 뒤 '스캔하기'를 누르세요.";
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
      const result = record.error
        ? (STATUS_TEXT[record.error] || record.error) + (record.reason ? ` — ${record.reason}` : "")
        : record.reply.replace(/[\r\n>]+/g, " ").replace(/\s+/g, " ").trim().slice(0, 80) || "빈 응답";
      item.textContent = `${record.header ? `${record.header} ` : ""}${record.command} · ${record.label} → ${result}`;
      if (record.error && record.error !== "skipped") item.className = "text-danger";
      logList.append(item);
      logList.scrollTop = logList.scrollHeight;
    }

    function skipReason(step, ctx) {
      if (state.stop) return "사용자가 스캔을 중지했습니다.";
      if (step.header && ctx.dead.has(step.header)) return `${step.header} 제어기가 응답하지 않아 건너뛰었습니다.`;
      if (step.bus === "can" && ctx.bus === "serial") return "K-Line·J1850 차량이라 CAN 전용 조회를 건너뛰었습니다.";
      if (step.header && step.header.length === 3 && ctx.bus === "can29") return "29비트 CAN 차량이라 11비트 주소 조회를 건너뛰었습니다.";
      const mode01 = /^01([0-9A-F]{2})$/.exec(step.command);
      if (mode01 && ctx.supported.size && step.command !== "0100") {
        if (!ctx.supported.has(parseInt(mode01[1], 16))) return "차량이 지원하지 않는 항목입니다(지원 PID 목록에 없음).";
      }
      if (step.group === "freeze") {
        if (ctx.dtcCount === 0) return "저장된 고장코드가 없어 고장 당시 값이 없습니다.";
        const pid = parseInt(step.command.slice(2, 4), 16);
        if (pid !== 2 && ctx.supported.size && !ctx.supported.has(pid)) return "차량이 지원하지 않는 항목입니다(지원 PID 목록에 없음).";
      }
      return null;
    }

    async function runPlan(steps, results) {
      const started = performance.now();
      const ctx = { dead: new Set(), supported: new Set(), bus: null, dtcCount: null };
      const tally = { ok: 0, failed: 0, skipped: 0 };
      let header = null;
      for (const [index, step] of steps.entries()) {
        bar.value = Math.round((index / steps.length) * 100);
        scanStatus.textContent = `${index + 1}/${steps.length} ${step.label} 읽는 중…`;
        const record = { ...step, reply: null, error: null, reason: null, tMs: Math.round(performance.now() - started) };
        const reason = skipReason(step, ctx);
        if (reason) {
          Object.assign(record, { error: "skipped", reason });
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
              const want = step.header || (header ? BROADCAST[ctx.bus] || "7DF" : null);
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
          if (step.command === "ATDPN" && record.reply) ctx.bus = busOf(record.reply);
          if (SUPPORT_RANGE.test(step.command) && record.reply) {
            supportedFrom(record.reply, parseInt(step.command.slice(2), 16)).forEach((pid) => ctx.supported.add(pid));
          }
          if (step.command === "0101" && record.reply) ctx.dtcCount = dtcCountFrom(record.reply);
          if (step.probe && step.header && (!record.reply || /NO DATA|CAN ERROR|UNABLE/i.test(record.reply))) {
            ctx.dead.add(step.header);
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
      Object.assign(state, { running: true, stop: false, pending: null });
      runBtn.disabled = true;
      stopBtn.disabled = false;
      retryBtn.hidden = true;
      lookupFailed.hidden = true;
      progress.hidden = false;
      logList.replaceChildren();
      counts.textContent = "";
      bar.value = 0;
      stage("scan");
      notice.textContent = "차량을 스캔하는 중입니다. 시동을 끄거나 진단기를 뽑지 마세요.";
      const results = [];
      let clientError = null;
      try {
        scanStatus.textContent = "스캔 계획을 받는 중…";
        const plan = await post(config.planUrl, { car: state.car });
        await runPlan(plan.steps, results);
      } catch (error) {
        clientError = `${results.length ? `${results.length}번째 단계 뒤 ` : ""}스캔이 중단되었습니다: ${error.message}`;
      }
      try {
        if (!results.length) {
          stage("scan", true);
          scanStatus.textContent = clientError || "보낸 명령이 없습니다.";
          return;
        }
        state.pending = {
          carNo: state.carNo || form.elements.car_no.value.replace(/\s+/g, ""), car: state.car, steps: results,
          transport: link.transport, device: link.info.name || "", lookupError: state.lookupError, clientError,
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
