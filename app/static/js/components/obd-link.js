// ELM327 호환 OBD2 진단기 연결. BLE(Web Bluetooth)와 블루투스 클래식 SPP·USB(Web Serial)를 지원한다.
// 넓게 찾고, 통신 채널을 스스로 찾고, 끊기면 다시 붙는다.
// 화면 스크립트(obd-ble.js, obd-dashboard.js, obd-scan.js)는 window.WecarObd.bindPanel()이 돌려준 연결을 쓴다.
(() => {
  "use strict";

  const NAME_PREFIXES = [
    "OBD", "OBDII", "OBD2", "OBDBLE", "ELM", "ELM327", "Vlink", "vLinker", "VLINK", "V-LINK",
    "IOS-Vlink", "Android-Vlink", "VEEPEAK", "Veepeak", "FMM003", "KONNWEI", "Viecar", "OBDLink",
    "Carista", "iCar", "Vgate", "KIWI", "Kiwi", "LELink", "BlueDriver", "OBDCheck", "Bluetooth OBD",
    "V-Checker", "Autophix", "THINKCAR", "Topdon", "Foxwell",
  ];
  // ELM327 계열 BLE UART 서비스: 일반 클론(fff0·ffe0·18f0), Nordic UART, Microchip(vLinker·OBDLink CX), 기타 클론
  const KNOWN_SERVICES = [
    0xfff0, 0xffe0, 0x18f0, 0xae30, 0xbeef, "6e400001-b5a3-f393-e0a9-e50e24dcca9e",
    "e7810a71-73ae-499d-8c15-faa9aef0c3f2", "49535343-fe7d-4ae5-8fa9-9fafd205e455",
  ];
  const SPP_UUID = "00001101-0000-1000-8000-00805f9b34fb";
  const SERIAL_BAUDS = [38400, 9600, 115200, 500000];
  const TRANSPORT_KEY = "wecar.obd.transport";
  const DEFAULT_INIT = ["ATZ", "ATE0", "ATL0", "ATSP0"];
  const FORMAT_COMMANDS = ["ATH1", "ATS1", "ATCAF1"];
  const PROBE_MS = 3000;
  const RECONNECT_MS = 5000;
  const CONNECT_TRIES = 3;
  const STORAGE_KEY = "wecar.obd.lastDevice";
  const FRAME = /^([0-9A-F]{3}|[0-9A-F]{8})((?:\s[0-9A-F]{2})+)$/;

  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  function uuid(value) {
    if (typeof value === "number") return BluetoothUUID.canonicalUUID(value);
    const text = (value || "").trim().toLowerCase();
    return /^[0-9a-f]{4}$/.test(text) ? BluetoothUUID.canonicalUUID(parseInt(text, 16)) : text;
  }

  function remembered() {
    try {
      return JSON.parse(localStorage.getItem(STORAGE_KEY) || "null");
    } catch {
      return null;
    }
  }

  function clean(reply) {
    return reply.replace(/SEARCHING\.\.\./g, "").replace(/>/g, "").trim();
  }

  class Link extends EventTarget {
    constructor(profiles) {
      super();
      this.profiles = profiles || [];
      this.profile = null;
      this.device = null;
      this.state = "idle";
      this.info = {};
      this._channel = null;
      this._queue = Promise.resolve();
      this._manual = false;
      this._reconnecting = false;
      this._pending = null;
    }

    get supported() {
      return Boolean(navigator.bluetooth);
    }

    get transport() {
      return "ble";
    }

    get ready() {
      return this.state === "ready";
    }

    get lastDeviceName() {
      return remembered()?.name || "";
    }

    _emit(state, message) {
      this.state = state;
      this.dispatchEvent(new CustomEvent("status", { detail: { state, message } }));
    }

    _services() {
      const own = this.profiles.map((p) => p.service).filter(Boolean).map(uuid);
      return [...new Set([...own, ...KNOWN_SERVICES.map(uuid)])];
    }

    async find({ all = false } = {}) {
      if (!this.supported) throw new Error("이 브라우저는 Web Bluetooth를 지원하지 않습니다.");
      const services = this._services();
      const prefixes = [...new Set([...NAME_PREFIXES, ...this.profiles.map((p) => p.namePrefix).filter(Boolean)])];
      this._emit("searching", "진단기를 고르세요…");
      const options = all
        ? { acceptAllDevices: true, optionalServices: services }
        : {
            filters: [...prefixes.map((namePrefix) => ({ namePrefix })), ...services.map((s) => ({ services: [s] }))],
            optionalServices: services,
          };
      let device;
      try {
        device = await navigator.bluetooth.requestDevice(options);
      } catch (error) {
        this._emit("idle", error.name === "NotFoundError" ? "진단기 선택을 취소했습니다." : `찾기 실패: ${error.message}`);
        throw error;
      }
      await this.open(device);
    }

    // 이 사이트가 허락받은 기기(getDevices 지원 브라우저)에 버튼 없이 연결한다.
    async autoConnect() {
      if (!this.supported || !navigator.bluetooth.getDevices) return false;
      const last = remembered();
      const devices = await navigator.bluetooth.getDevices().catch(() => []);
      const device = devices.find((d) => last && d.id === last.id) || (devices.length === 1 ? devices[0] : null);
      if (!device) return false;
      this._attach(device);
      this._reconnect();
      return true;
    }

    _attach(device) {
      if (this.device === device) return;
      this.device = device;
      device.addEventListener("gattserverdisconnected", () => {
        this._channel = null;
        if (this._manual) return;
        this._emit("lost", "진단기 연결이 끊겼습니다. 다시 연결하는 중…");
        this._reconnect();
      });
    }

    async open(device) {
      this._manual = false;
      this._attach(device);
      this._emit("connecting", `${device.name || "진단기"}에 연결하는 중…`);
      let lastError;
      for (let attempt = 1; attempt <= CONNECT_TRIES; attempt += 1) {
        try {
          await this._setup();
          return;
        } catch (error) {
          lastError = error;
          if (attempt < CONNECT_TRIES) await sleep(1000);
        }
      }
      this._emit("idle", `연결 실패: ${lastError.message}`);
      throw lastError;
    }

    _setup() {
      if (!this._pending) this._pending = this._connectAndInit().finally(() => { this._pending = null; });
      return this._pending;
    }

    async _connectAndInit() {
      const server = await this.device.gatt.connect();
      this._channel = await this._detect(server);
      const init = this.profile?.init?.length ? this.profile.init : DEFAULT_INIT;
      for (const command of [...init, ...FORMAT_COMMANDS]) {
        await this.send(command, command === "ATZ" ? 4000 : this._timeout());
      }
      this.info = {
        name: this.device.name || "",
        version: clean(await this.send("ATI")),
        voltage: clean(await this.send("ATRV")),
      };
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ id: this.device.id, name: this.device.name || "" }));
      localStorage.setItem(TRANSPORT_KEY, "ble");
      this._emit("ready", `${this.info.name || "진단기"} 연결됨`);
    }

    async _reconnect() {
      if (this._reconnecting) return;
      this._reconnecting = true;
      try {
        while (!this._manual && this.state !== "ready") {
          this._emit("lost", "진단기를 찾는 중… 시동을 켜고 단말기를 꽂아 두세요.");
          try {
            await this._setup();
          } catch {
            await sleep(RECONNECT_MS);
          }
        }
      } finally {
        this._reconnecting = false;
      }
    }

    // 쓰기·알림 특성 조합마다 ATI를 보내 응답이 오는 조합을 쓴다. 프로필 UUID가 맞으면 그것부터.
    async _detect(server) {
      const services = await server.getPrimaryServices();
      const pairs = [];
      for (const service of services) {
        const chars = await service.getCharacteristics().catch(() => []);
        const writers = chars.filter((c) => c.properties.write || c.properties.writeWithoutResponse);
        const notifiers = chars.filter((c) => c.properties.notify || c.properties.indicate);
        for (const writer of writers) for (const notifier of notifiers) pairs.push({ service, writer, notifier });
      }
      const matches = (pair, p) => p && uuid(p.service) === pair.service.uuid
        && uuid(p.write) === pair.writer.uuid && uuid(p.notify) === pair.notifier.uuid;
      const preferred = this.profiles.find((p) => pairs.some((pair) => matches(pair, p)));
      pairs.sort((a, b) => Number(matches(b, preferred)) - Number(matches(a, preferred)));
      for (const pair of pairs) {
        const channel = await this._probe(pair);
        if (channel) {
          if (!this.profile && preferred && matches(pair, preferred)) this.profile = preferred;
          return channel;
        }
      }
      throw new Error("진단기 통신 채널을 찾지 못했습니다. ELM327 호환 BLE 진단기인지 확인하세요.");
    }

    async _probe({ writer, notifier }) {
      const channel = { writer, notifier, buffer: "", waiting: null };
      const onValue = (event) => {
        channel.buffer += new TextDecoder().decode(event.target.value);
        const end = channel.buffer.indexOf(">");
        if (channel.waiting && end >= 0) {
          const reply = channel.buffer.slice(0, end);
          channel.buffer = channel.buffer.slice(end + 1);
          channel.waiting(reply);
        }
      };
      try {
        await notifier.startNotifications();
        notifier.addEventListener("characteristicvaluechanged", onValue);
        const reply = await this._write(channel, "ATI", PROBE_MS);
        if (reply.trim()) {
          channel.detach = () => notifier.removeEventListener("characteristicvaluechanged", onValue);
          return channel;
        }
      } catch {
        // 다음 조합을 시험한다
      }
      notifier.removeEventListener("characteristicvaluechanged", onValue);
      await notifier.stopNotifications().catch(() => {});
      return null;
    }

    _write(channel, command, timeoutMs) {
      return new Promise((resolve, reject) => {
        const timer = setTimeout(() => {
          channel.waiting = null;
          resolve("");
        }, timeoutMs);
        channel.waiting = (reply) => {
          clearTimeout(timer);
          channel.waiting = null;
          resolve(reply);
        };
        const bytes = new TextEncoder().encode(`${command}\r`);
        const { writer } = channel;
        const write = writer.properties.writeWithoutResponse
          ? writer.writeValueWithoutResponse(bytes)
          : writer.writeValue(bytes);
        write.catch((error) => {
          clearTimeout(timer);
          channel.waiting = null;
          reject(error);
        });
      });
    }

    _timeout() {
      return this.profile?.timeout || 2000;
    }

    // 명령을 하나씩 보낸다. 연결이 없거나 쓰기에 실패하면 예외를 던진다.
    send(command, timeoutMs) {
      const run = async () => {
        if (!this._channel) throw new Error("진단기가 연결되어 있지 않습니다.");
        return this._write(this._channel, command, timeoutMs || this._timeout());
      };
      const result = this._queue.then(run, run);
      this._queue = result.catch(() => {});
      return result;
    }

    // 연결될 때까지 기다린다. stop()이 true를 돌려주면 그만둔다.
    async waitReady(stop) {
      while (!this.ready) {
        if (stop && stop()) return false;
        await sleep(300);
      }
      return true;
    }

    disconnect() {
      this._manual = true;
      this._channel?.detach?.();
      this._channel = null;
      if (this.device?.gatt?.connected) this.device.gatt.disconnect();
      this._emit("idle", "연결을 끊었습니다.");
    }
  }

  // 블루투스 클래식(SPP, RFCOMM)·USB 진단기. Web Serial로 포트를 열고 통신 속도를 차례로 시험한다.
  class SerialLink extends EventTarget {
    constructor() {
      super();
      this.port = null;
      this.state = "idle";
      this.info = {};
      this._buffer = "";
      this._waiting = null;
      this._reader = null;
      this._reading = null;
      this._queue = Promise.resolve();
      this._manual = false;
    }

    get supported() {
      return Boolean(navigator.serial);
    }

    get transport() {
      return "serial";
    }

    get ready() {
      return this.state === "ready";
    }

    _emit(state, message) {
      this.state = state;
      this.dispatchEvent(new CustomEvent("status", { detail: { state, message } }));
    }

    async find() {
      if (!this.supported) throw new Error("이 브라우저는 Web Serial을 지원하지 않습니다.");
      this._emit("searching", "진단기 포트를 고르세요(블루투스는 먼저 페어링)…");
      let port;
      try {
        port = await navigator.serial.requestPort({ allowedBluetoothServiceClassIds: [SPP_UUID] });
      } catch (error) {
        this._emit("idle", error.name === "NotFoundError" ? "진단기 선택을 취소했습니다." : `찾기 실패: ${error.message}`);
        throw error;
      }
      await this.open(port);
    }

    async autoConnect() {
      if (!this.supported || localStorage.getItem(TRANSPORT_KEY) !== "serial") return false;
      const ports = await navigator.serial.getPorts().catch(() => []);
      if (ports.length !== 1) return false;
      await this.open(ports[0]).catch(() => {});
      return true;
    }

    async open(port) {
      this._manual = false;
      this.port = port;
      port.addEventListener("disconnect", () => {
        this._stopReading();
        if (!this._manual) this._emit("idle", "진단기 연결이 끊겼습니다. 다시 연결하세요.");
      });
      for (const baudRate of SERIAL_BAUDS) {
        this._emit("connecting", `진단기에 연결하는 중(${baudRate}bps)…`);
        try {
          await port.open({ baudRate });
        } catch (error) {
          if (error.name !== "InvalidStateError") continue;
        }
        this._startReading();
        const reply = await this._write("ATI", PROBE_MS).catch(() => "");
        if (/ELM|STN|OBD|v\d/i.test(reply)) {
          this.info.baud = baudRate;
          await this._init();
          return;
        }
        await this._close();
      }
      this._emit("idle", "진단기가 응답하지 않습니다. ELM327 호환 진단기인지, 페어링·전원을 확인하세요.");
      throw new Error("진단기 응답 없음");
    }

    async _init() {
      for (const command of [...DEFAULT_INIT, ...FORMAT_COMMANDS]) {
        await this.send(command, command === "ATZ" ? 4000 : 2000);
      }
      const info = this.port.getInfo ? this.port.getInfo() : {};
      this.info = {
        ...this.info,
        name: info.bluetoothServiceClassId ? "블루투스 SPP 진단기" : "USB 진단기",
        version: clean(await this.send("ATI")),
        voltage: clean(await this.send("ATRV")),
      };
      localStorage.setItem(TRANSPORT_KEY, "serial");
      this._emit("ready", `${this.info.name} 연결됨`);
    }

    _startReading() {
      const decoder = new TextDecoder();
      this._readActive = true;
      this._reading = (async () => {
        while (this._readActive && this.port?.readable) {
          this._reader = this.port.readable.getReader();
          try {
            for (;;) {
              const { value, done } = await this._reader.read();
              if (done) break;
              this._onText(decoder.decode(value, { stream: true }));
            }
          } catch {
            break;
          } finally {
            this._reader.releaseLock();
            this._reader = null;
          }
        }
      })();
    }

    _onText(text) {
      this._buffer += text;
      const end = this._buffer.indexOf(">");
      if (this._waiting && end >= 0) {
        const reply = this._buffer.slice(0, end);
        this._buffer = this._buffer.slice(end + 1);
        this._waiting(reply);
      }
    }

    _stopReading() {
      this._readActive = false;
      this._reader?.cancel().catch(() => {});
    }

    async _close() {
      this._stopReading();
      await this._reading?.catch(() => {});
      await this.port?.close().catch(() => {});
    }

    async _write(command, timeoutMs) {
      if (!this.port?.writable) throw new Error("진단기가 연결되어 있지 않습니다.");
      this._buffer = "";
      const reply = new Promise((resolve) => {
        const timer = setTimeout(() => {
          this._waiting = null;
          resolve("");
        }, timeoutMs);
        this._waiting = (text) => {
          clearTimeout(timer);
          this._waiting = null;
          resolve(text);
        };
      });
      const writer = this.port.writable.getWriter();
      try {
        await writer.write(new TextEncoder().encode(`${command}\r`));
      } finally {
        writer.releaseLock();
      }
      return reply;
    }

    send(command, timeoutMs) {
      const run = () => this._write(command, timeoutMs || 2000);
      const result = this._queue.then(run, run);
      this._queue = result.catch(() => {});
      return result;
    }

    async waitReady(stop) {
      while (!this.ready) {
        if ((stop && stop()) || this.state === "idle") return false;
        await sleep(300);
      }
      return true;
    }

    disconnect() {
      this._manual = true;
      this._close();
      this._emit("idle", "연결을 끊었습니다.");
    }
  }

  // 화면에는 연결 하나만 보인다. 어느 방식으로 붙었든 같은 send·ready·status를 쓴다.
  class Connection extends EventTarget {
    constructor(profiles) {
      super();
      this.ble = new Link(profiles);
      this.serial = new SerialLink();
      this.active = this.ble;
      [this.ble, this.serial].forEach((link) => link.addEventListener("status", ({ detail }) => {
        if (link === this.active) this.dispatchEvent(new CustomEvent("status", { detail }));
      }));
    }

    get supported() {
      return this.ble.supported || this.serial.supported;
    }

    get transport() {
      return this.active.transport;
    }

    get state() {
      return this.active.state;
    }

    get ready() {
      return this.active.ready;
    }

    get info() {
      return this.active.info;
    }

    get lastDeviceName() {
      return this.ble.lastDeviceName;
    }

    set profile(value) {
      this.ble.profile = value;
    }

    _use(link) {
      if (this.active !== link && this.active.state !== "idle") this.active.disconnect();
      this.active = link;
    }

    find(options) {
      this._use(this.ble);
      return this.ble.find(options);
    }

    findSerial() {
      this._use(this.serial);
      return this.serial.find();
    }

    async autoConnect() {
      if (localStorage.getItem(TRANSPORT_KEY) === "serial") {
        this._use(this.serial);
        return this.serial.autoConnect();
      }
      return this.ble.autoConnect();
    }

    send(command, timeoutMs) {
      return this.active.send(command, timeoutMs);
    }

    waitReady(stop) {
      return this.active.waitReady(stop);
    }

    disconnect() {
      this.active.disconnect();
    }
  }

  // 요청 목록을 rounds번 보내 '# WECAR-ELM 1' 기록 줄을 만든다. 끊기면 다시 연결된 뒤 같은 요청부터 잇는다.
  async function capture(link, requests, { vehicle, rounds = 1, onLog = () => {}, onRound = () => {}, stop = () => false }) {
    const started = performance.now();
    const stamp = () => (performance.now() - started).toFixed(1);
    const lines = ["# WECAR-ELM 1", `# vehicle: ${vehicle}`, `# device: ${link.info.name || "-"}`,
      `# started: ${new Date().toISOString()}`, "# source: web"];
    let header = null;
    for (let round = 1; round <= rounds && !stop(); round += 1) {
      onRound(round, rounds);
      for (let index = 0, tries = 0; index < requests.length && !stop(); index += 1) {
        const req = requests[index];
        let reply;
        try {
          if (!link.ready) {
            if (!(await link.waitReady(stop))) break;
            header = null;
          }
          if (req.header !== header) {
            await link.send(`ATSH${req.header}`);
            header = req.header;
          }
          reply = await link.send(req.command);
          if (!link.ready) throw new Error("lost");
          tries = 0;
        } catch {
          header = null;
          tries += 1;
          if (tries < 3) index -= 1;
          else tries = 0;
          continue;
        }
        const payload = req.command.match(/.{2}/g);
        lines.push(`${stamp()} TX ${req.header} ${[payload.length.toString(16).padStart(2, "0").toUpperCase(), ...payload].join(" ")}`);
        let frames = 0;
        reply.split(/[\r\n]+/).forEach((raw) => {
          const match = FRAME.exec(raw.trim().toUpperCase());
          if (!match) return;
          lines.push(`${stamp()} RX ${match[1]} ${match[2].trim()}`);
          frames += 1;
        });
        onLog(`${req.header} ${req.command} → ${frames ? `${frames}개 프레임` : clean(reply) || "응답 없음"}`);
      }
    }
    return lines;
  }

  function readConfig() {
    const node = document.getElementById("obd-config");
    return node ? JSON.parse(node.textContent) : null;
  }

  // _obd_panel.html의 버튼·상태 표시를 연결하고, 허락받은 진단기가 있으면 바로 연결을 시도한다.
  function bindPanel(root, config) {
    const link = new Connection(config.profiles);
    const q = (selector) => root.querySelector(selector);
    const status = q("[data-obd-status]");
    const info = q("[data-obd-info]");
    const findBtn = q("[data-obd-find]");
    const serialBtn = q("[data-obd-find-serial]");
    const allBtn = q("[data-obd-find-all]");
    const offBtn = q("[data-obd-disconnect]");
    const select = q("[data-obd-profile]");
    const labels = { ble: "블루투스(BLE)", serial: "블루투스 클래식·USB(시리얼)" };
    if (!link.supported) {
      q("[data-obd-unsupported]").hidden = false;
      findBtn.disabled = true;
      allBtn.disabled = true;
      if (serialBtn) serialBtn.disabled = true;
      return link;
    }
    if (!link.ble.supported) {
      findBtn.disabled = true;
      allBtn.disabled = true;
    }
    if (serialBtn && !link.serial.supported) {
      serialBtn.disabled = true;
      serialBtn.title = "이 브라우저는 Web Serial을 지원하지 않습니다.";
    }
    if (link.lastDeviceName) {
      status.textContent = `최근 연결한 진단기: ${link.lastDeviceName}. 시동을 켜고 '진단기 연결'을 누르세요.`;
    }
    select.addEventListener("change", () => {
      link.profile = config.profiles.find((p) => String(p.id) === select.value) || null;
    });
    link.addEventListener("status", ({ detail }) => {
      status.textContent = detail.message;
      const busy = detail.state === "searching" || detail.state === "connecting";
      const locked = busy || detail.state === "ready";
      findBtn.disabled = locked || !link.ble.supported;
      allBtn.disabled = findBtn.disabled;
      if (serialBtn) serialBtn.disabled = locked || !link.serial.supported;
      offBtn.disabled = detail.state === "idle";
      info.hidden = detail.state !== "ready";
      if (detail.state === "ready") {
        q("[data-obd-name]").textContent = link.info.name || "-";
        const transport = q("[data-obd-transport]");
        if (transport) transport.textContent = labels[link.transport] || link.transport;
        q("[data-obd-version]").textContent = link.info.version || "-";
        q("[data-obd-voltage]").textContent = link.info.voltage || "-";
      }
    });
    findBtn.addEventListener("click", () => link.find().catch(() => {}));
    serialBtn?.addEventListener("click", () => link.findSerial().catch(() => {}));
    allBtn.addEventListener("click", () => link.find({ all: true }).catch(() => {}));
    offBtn.addEventListener("click", () => link.disconnect());
    link.autoConnect().catch(() => {});
    return link;
  }

  window.WecarObd = { capture, readConfig, bindPanel };
})();
