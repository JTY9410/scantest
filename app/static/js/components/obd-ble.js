// 블루투스 수집 화면: 이 화면의 연결 패널로 진단기에 붙어 요청을 반복해 보내고 기록을 저장한다.
(() => {
  "use strict";

  const config = window.WecarObd?.readConfig();
  const panel = document.querySelector("[data-obd-panel]");
  if (!config || !panel) return;
  const link = window.WecarObd.bindPanel(panel, config);

  const root = document.getElementById("ble-capture");
  const form = root.querySelector("[data-ble-form]");
  if (!form) return;
  const statusEl = root.querySelector("[data-ble-status]");
  const logEl = root.querySelector("[data-ble-log]");
  const startBtn = root.querySelector("[data-ble-start]");
  const stopBtn = root.querySelector("[data-ble-stop]");
  const saveBtn = root.querySelector("[data-ble-save]");

  let lines = [];
  let running = false;
  let stopRequested = false;

  function setStatus(text) {
    statusEl.textContent = text;
  }

  function log(text) {
    logEl.textContent += `${text}\n`;
    logEl.scrollTop = logEl.scrollHeight;
  }

  link.addEventListener("status", ({ detail }) => {
    startBtn.disabled = running || detail.state !== "ready" || link.busy;
    if (running && detail.state === "lost") setStatus("연결이 끊겼습니다. 다시 연결되면 하던 곳부터 이어서 수집합니다…");
  });

  async function start() {
    const vehicle = form.elements.vehicle.value.trim();
    if (!vehicle) {
      setStatus("차량 이름을 입력하세요.");
      form.elements.vehicle.focus();
      return;
    }
    const rounds = Math.max(1, Math.min(30, parseInt(form.elements.rounds.value, 10) || 1));
    running = true;
    stopRequested = false;
    startBtn.disabled = true;
    saveBtn.disabled = true;
    stopBtn.disabled = false;
    logEl.textContent = "";
    try {
      lines = await window.WecarObd.capture(link, config.requests, {
        vehicle,
        rounds,
        onLog: log,
        onRound: (round, total) => setStatus(`수집 중 (${round}/${total})…`),
        stop: () => stopRequested,
      });
      const rx = lines.filter((line) => line.includes(" RX ")).length;
      setStatus(rx ? `수집 완료: 응답 프레임 ${rx}개. '기록 저장'을 누르세요.` : "응답을 받지 못했습니다. 시동과 진단기 연결을 확인하세요.");
      saveBtn.disabled = rx === 0;
    } catch (error) {
      setStatus(`수집 실패: ${error.message}`);
    } finally {
      running = false;
      startBtn.disabled = !link.ready;
      stopBtn.disabled = true;
    }
  }

  async function save() {
    saveBtn.disabled = true;
    setStatus("저장 중…");
    const body = new FormData();
    body.append("csrf_token", form.elements.csrf_token.value);
    body.append("vehicle", form.elements.vehicle.value.trim());
    body.append("filename", `live-${new Date().toISOString().replace(/[:.]/g, "-")}.txt`);
    body.append("content", `${lines.join("\n")}\n`);
    try {
      const response = await fetch(config.saveUrl, { method: "POST", body, credentials: "same-origin" });
      const result = await response.json().catch(() => ({ message: "서버 응답을 읽지 못했습니다" }));
      if (!response.ok) throw new Error(result.message || `HTTP ${response.status}`);
      statusEl.textContent = "저장했습니다. ";
      const anchor = document.createElement("a");
      anchor.href = result.report_url;
      anchor.className = "underline";
      anchor.textContent = "이 기록으로 결과지 만들기";
      statusEl.append(anchor);
    } catch (error) {
      setStatus(`저장 실패: ${error.message}`);
      saveBtn.disabled = false;
    }
  }

  startBtn.addEventListener("click", start);
  stopBtn.addEventListener("click", () => {
    stopRequested = true;
    setStatus("중지하는 중…");
  });
  saveBtn.addEventListener("click", save);
})();
