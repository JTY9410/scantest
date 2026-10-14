// Web Bluetooth로 ELM327 호환 BLE 진단기에 연결해 UDS 응답을 '# WECAR-ELM 1' 형식으로 기록한다.
(() => {
  "use strict";

  const root = document.getElementById("ble-capture");
  if (!root) return;
  const form = root.querySelector("[data-ble-form]");
  const statusEl = root.querySelector("[data-ble-status]");
  const logEl = root.querySelector("[data-ble-log]");
  const startBtn = root.querySelector("[data-ble-start]");
  const stopBtn = root.querySelector("[data-ble-stop]");
  const saveBtn = root.querySelector("[data-ble-save]");
  const requests = Array.from(root.querySelectorAll("[data-ble-requests] li")).map((li) => ({
    header: li.dataset.header,
    command: li.dataset.command,
  }));
  // 프로필 초기화 뒤에 기록 형식(헤더·공백 표시, 자동 포맷)을 고정한다.
  const FORMAT_COMMANDS = ["ATH1", "ATS1", "ATCAF1"];
  const FRAME = /^([0-9A-F]{3}|[0-9A-F]{8})((?:\s[0-9A-F]{2})+)$/;

  let lines = [];
  let started = 0;
  let stopRequested = false;
  let device = null;

  function setStatus(text) {
    statusEl.textContent = text;
  }

  function log(text) {
    logEl.textContent += `${text}\n`;
    logEl.scrollTop = logEl.scrollHeight;
  }

  function uuid(value) {
    const text = (value || "").trim().toLowerCase();
    return /^[0-9a-f]{4}$/.test(text) ? BluetoothUUID.canonicalUUID(parseInt(text, 16)) : text;
  }

  function stamp() {
    return (performance.now() - started).toFixed(1);
  }

  function hexBytes(text) {
    return text.match(/.{2}/g).join(" ");
  }

  async function connect(option) {
    device = await navigator.bluetooth.requestDevice({
      filters: [{ namePrefix: option.dataset.namePrefix }],
      optionalServices: [uuid(option.dataset.service)],
    });
    device.addEventListener("gattserverdisconnected", () => setStatus("진단기 연결이 끊겼습니다."));
    const server = await device.gatt.connect();
    const service = await server.getPrimaryService(uuid(option.dataset.service));
    const writer = await service.getCharacteristic(uuid(option.dataset.write));
    const notifier = await service.getCharacteristic(uuid(option.dataset.notify));
    await notifier.startNotifications();
    return { writer, notifier };
  }

  function makeSender({ writer, notifier }, timeoutMs) {
    const decoder = new TextDecoder();
    let buffer = "";
    let waiting = null;
    notifier.addEventListener("characteristicvaluechanged", (event) => {
      buffer += decoder.decode(event.target.value);
      if (waiting && buffer.includes(">")) {
        const reply = buffer.slice(0, buffer.indexOf(">"));
        buffer = buffer.slice(buffer.indexOf(">") + 1);
        waiting(reply);
        waiting = null;
      }
    });
    const encoder = new TextEncoder();
    return (command) =>
      new Promise((resolve) => {
        const timer = setTimeout(() => {
          waiting = null;
          resolve("");
        }, timeoutMs);
        waiting = (reply) => {
          clearTimeout(timer);
          resolve(reply);
        };
        const bytes = encoder.encode(`${command}\r`);
        const write = writer.properties.writeWithoutResponse
          ? writer.writeValueWithoutResponse(bytes)
          : writer.writeValue(bytes);
        write.catch(() => resolve(""));
      });
  }

  function record(header, command, reply) {
    const payload = command.match(/.{2}/g);
    lines.push(`${stamp()} TX ${header} ${hexBytes((payload.length).toString(16).padStart(2, "0").toUpperCase() + command)}`);
    let frames = 0;
    reply.split(/[\r\n]+/).forEach((raw) => {
      const text = raw.trim().toUpperCase();
      const match = FRAME.exec(text);
      if (!match) return;
      lines.push(`${stamp()} RX ${match[1]} ${match[2].trim()}`);
      frames += 1;
    });
    return frames;
  }

  async function start() {
    if (!navigator.bluetooth) {
      setStatus("이 브라우저는 Web Bluetooth를 지원하지 않습니다. 안드로이드·PC Chrome을 쓰세요.");
      return;
    }
    const vehicle = form.elements.vehicle.value.trim();
    if (!vehicle) {
      setStatus("차량 이름을 입력하세요.");
      form.elements.vehicle.focus();
      return;
    }
    const option = form.elements.profile.selectedOptions[0];
    const rounds = Math.max(1, Math.min(30, parseInt(form.elements.rounds.value, 10) || 1));
    const timeout = parseInt(option.dataset.timeout, 10) || 2000;

    startBtn.disabled = true;
    saveBtn.disabled = true;
    stopBtn.disabled = false;
    stopRequested = false;
    logEl.textContent = "";
    lines = [];
    try {
      setStatus("진단기를 고르세요…");
      const channel = await connect(option);
      const send = makeSender(channel, timeout);
      started = performance.now();
      lines.push("# WECAR-ELM 1", `# vehicle: ${vehicle}`, `# device: ${device.name || "-"}`,
        `# started: ${new Date().toISOString()}`, "# source: web");
      setStatus("진단기 초기화 중…");
      const init = (option.dataset.init || "").split("|").filter(Boolean);
      for (const command of [...init, ...FORMAT_COMMANDS]) {
        const reply = await send(command);
        log(`${command} → ${reply.trim().replace(/\s+/g, " ") || "(응답 없음)"}`);
      }
      let header = null;
      for (let round = 1; round <= rounds && !stopRequested; round += 1) {
        setStatus(`수집 중 (${round}/${rounds})…`);
        for (const req of requests) {
          if (stopRequested) break;
          if (req.header !== header) {
            await send(`ATSH${req.header}`);
            header = req.header;
          }
          const reply = await send(req.command);
          const frames = record(req.header, req.command, reply);
          log(`${req.header} ${req.command} → ${frames ? `${frames}개 프레임` : reply.trim() || "응답 없음"}`);
        }
      }
      const rx = lines.filter((l) => l.includes(" RX ")).length;
      setStatus(rx ? `수집 완료: 응답 프레임 ${rx}개. '기록 저장'을 누르세요.` : "응답을 받지 못했습니다. 시동과 진단기 연결을 확인하세요.");
      saveBtn.disabled = rx === 0;
    } catch (error) {
      setStatus(error.name === "NotFoundError" ? "진단기 선택을 취소했습니다." : `연결 실패: ${error.message}`);
    } finally {
      startBtn.disabled = false;
      stopBtn.disabled = true;
      if (device?.gatt?.connected) device.gatt.disconnect();
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
      const response = await fetch(root.dataset.saveUrl, { method: "POST", body, credentials: "same-origin" });
      const result = await response.json();
      if (!response.ok) throw new Error(result.message || `HTTP ${response.status}`);
      statusEl.textContent = "저장했습니다. ";
      const link = document.createElement("a");
      link.href = result.report_url;
      link.className = "underline";
      link.textContent = "이 기록으로 결과지 만들기";
      statusEl.append(link);
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
