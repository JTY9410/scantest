// OBD2 진단기 연결. 연결 방식(BLE: Web Bluetooth, 블루투스 클래식 SPP·USB: Web Serial)이 글자를 주고받고,
// 명령 체계는 드라이버(obd-driver.js: ELM327·STN·slcan)가 맡는다. 한 번 연결한 진단기는 이 브라우저에 최근 5대까지
// 기억하고(기억 지우기 가능) 서버 계정에도 남긴다. 끊기면 다시 붙는다.
// 화면 스크립트(obd-ble.js, obd-dashboard.js, obd-scan.js)는 window.WecarObd.bindPanel()이 돌려준 연결을 쓴다.
// 필요한 스크립트: obd-plan.js, obd-driver.js
(() => {
  "use strict";

  const D = window.WecarObdDriver;
  const P = window.WecarObdPlan;

  const NAME_PREFIXES = [
    "bwsi", "BWSI", "Bwsi",  // 위스캔 전용 BLE(예: bwsia846749d8a76)
    "OBD", "ELM", "Vlink", "vLinker", "VLINK", "V-LINK", "IOS-Vlink", "Android-Vlink", "VEEPEAK", "Veepeak",
    "FMM003", "KONNWEI", "Viecar", "Carista", "iCar", "Vgate", "KIWI", "Kiwi", "LELink", "BlueDriver",
    "Bluetooth OBD", "V-Checker", "Autophix", "THINKCAR", "Topdon", "Foxwell", "WiCAN", "CANable", "SLCAN",
  ];
  // BLE UART 서비스: 일반 클론(fff0·ffe0·18f0), Nordic UART(nRF·ESP32 BLE-CAN 포함), Microchip(vLinker·OBDLink CX), 기타
  const KNOWN_SERVICES = [
    0xfff0, 0xffe0, 0x18f0, 0xae30, 0xbeef, "6e400001-b5a3-f393-e0a9-e50e24dcca9e",
    "e7810a71-73ae-499d-8c15-faa9aef0c3f2", "49535343-fe7d-4ae5-8fa9-9fafd205e455",
  ];
  // 통신 채널을 찾을 때 건드리지 않는 표준 서비스(장치 정보·배터리·펌웨어 업데이트)
  const SKIP_SERVICES = [0x1800, 0x1801, 0x180a, 0x180f, 0xfe59, "00001530-1212-efde-1523-785feabcd123"];
  const SPP_UUID = "00001101-0000-1000-8000-00805f9b34fb";
  const SERIAL_BAUDS = [38400, 9600, 115200, 500000];
  const BLE_CHUNK = 20;
  const PROBE_MS = 3000;
  const RECONNECT_MS = 5000;
  const CONNECT_TRIES = 3;
  const DEVICES_KEY = "wecar.obd.devices";
  const OLD_KEYS = { device: "wecar.obd.lastDevice", transport: "wecar.obd.transport", protocols: "wecar.obd.protocols" };
  const MAX_DEVICES = 5;
  const TRANSPORT_LABELS = { ble: "블루투스(BLE)", serial: "블루투스 클래식·USB(시리얼)" };

  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const hex = (n) => n.toString(16).toUpperCase().padStart(2, "0");

  function uuid(value) {
    if (typeof value === "number") return BluetoothUUID.canonicalUUID(value);
    const text = (value || "").trim().toLowerCase();
    return /^[0-9a-f]{4}$/.test(text) ? BluetoothUUID.canonicalUUID(parseInt(text, 16)) : text;
  }

  // --- 기억한 진단기(이 브라우저) ---
  const Memory = {
    _read() {
      try {
        return JSON.parse(localStorage.getItem(DEVICES_KEY) || "[]");
      } catch {
        return [];
      }
    },
    _write(list) {
      try {
        localStorage.setItem(DEVICES_KEY, JSON.stringify(list));
      } catch {
        // 저장하지 못해도 연결은 쓴다. 다음 연결 때 다시 고른다.
      }
    },
    // 예전 키(마지막 BLE 기기 하나, 시리얼 통신 방식 한 칸)를 목록으로 옮긴다.
    migrate() {
      try {
        if (localStorage.getItem(DEVICES_KEY) !== null) return;
        const last = JSON.parse(localStorage.getItem(OLD_KEYS.device) || "null");
        const protocols = JSON.parse(localStorage.getItem(OLD_KEYS.protocols) || "{}");
        const serialLast = localStorage.getItem(OLD_KEYS.transport) === "serial";
        const list = [];
        if (last?.id) {
          list.push({ key: `ble:${last.id}`, transport: "ble", id: last.id, name: last.name || "",
            protocol: protocols[last.id] || null, lastUsedAt: serialLast ? 1 : 2 });
        }
        if (serialLast) {
          list.push({ key: "serial:", transport: "serial", name: "시리얼 진단기", protocol: protocols.serial || null,
            lastUsedAt: 2 });
        }
        this._write(list);
        Object.values(OLD_KEYS).forEach((key) => localStorage.removeItem(key));
      } catch {
        // 옮기지 못하면 새로 고른다
      }
    },
    list() {
      return this._read().sort((a, b) => (b.lastUsedAt || 0) - (a.lastUsedAt || 0));
    },
    find(key) {
      return this._read().find((item) => item.key === key) || null;
    },
    save(entry) {
      const list = [entry, ...this._read().filter((item) => item.key !== entry.key)]
        .sort((a, b) => (b.lastUsedAt || 0) - (a.lastUsedAt || 0))
        .slice(0, MAX_DEVICES);
      this._write(list);
      return entry;
    },
    remove(key) {
      this._write(this._read().filter((item) => item.key !== key));
    },
  };

  function serialKey(port) {
    const info = port.getInfo ? port.getInfo() : {};
    if (info.usbVendorId) return `serial:${info.usbVendorId}:${info.usbProductId || ""}`;
    return `serial:bt:${info.bluetoothServiceClassId || ""}`;
  }

  // --- 연결 방식: 글자를 주고받기만 한다 ---
  class BleTransport {
    constructor() {
      this.kind = "ble";
      this.device = null;
      this.channel = null;
      this.onText = () => {};
      this.onLost = () => {};
      this._onDisconnect = () => {
        this._release();
        this.onLost(this);
      };
    }

    get supported() {
      return Boolean(navigator.bluetooth);
    }

    keyOf(device) {
      return `ble:${device.id}`;
    }

    nameOf(device) {
      return device.name || "BLE 진단기";
    }

    async choose({ all, services, prefixes }) {
      const options = all
        ? { acceptAllDevices: true, optionalServices: services }
        : { filters: [...prefixes.map((namePrefix) => ({ namePrefix })), ...services.map((s) => ({ services: [s] }))],
            optionalServices: services };
      return navigator.bluetooth.requestDevice(options);
    }

    // 다른 기기로 바꾸면 이전 기기의 끊김 처리기를 떼어 새 기기의 채널을 건드리지 않게 한다.
    async connect(device, hint = {}) {
      if (this.device && this.device !== device) await this.close();
      this.device = device;
      device.removeEventListener("gattserverdisconnected", this._onDisconnect);
      device.addEventListener("gattserverdisconnected", this._onDisconnect);
      this._release();
      const server = await device.gatt.connect();
      this.channel = await this._detect(server, hint);
      this.channel.live = true;
    }

    // 쓰기·알림 특성 조합마다 ATI를 보내 무엇이든 답하는 조합을 쓴다(slcan은 BEL로 답한다).
    // 고른 프로필·기억한 UUID, 알려진 UART 서비스 순서로 시험하고 표준 서비스는 건드리지 않는다.
    async _detect(server, hint) {
      const skip = new Set(SKIP_SERVICES.map(uuid));
      const known = KNOWN_SERVICES.map(uuid);
      const rank = (service) => {
        if (hint.service && uuid(hint.service) === service.uuid) return 0;
        const index = known.indexOf(service.uuid);
        return index >= 0 ? 1 + index : 100;
      };
      const services = (await server.getPrimaryServices()).filter((s) => !skip.has(s.uuid))
        .sort((a, b) => rank(a) - rank(b));
      for (const service of services) {
        const chars = await service.getCharacteristics().catch(() => []);
        const writers = chars.filter((c) => c.properties.write || c.properties.writeWithoutResponse);
        const notifiers = chars.filter((c) => c.properties.notify || c.properties.indicate);
        const pairs = writers.flatMap((writer) => notifiers.map((notifier) => ({ writer, notifier })));
        const preferred = (pair) => Number(hint.write && uuid(hint.write) === pair.writer.uuid)
          + Number(hint.notify && uuid(hint.notify) === pair.notifier.uuid);
        pairs.sort((a, b) => preferred(b) - preferred(a));
        for (const pair of pairs) {
          const channel = await this._probe(service, pair);
          if (channel) return channel;
        }
      }
      throw new Error("진단기 통신 채널을 찾지 못했습니다. OBD2 진단기(ELM327·STN·slcan)인지 확인하세요.");
    }

    async _probe(service, { writer, notifier }) {
      const decoder = new TextDecoder();
      const channel = { service, writer, notifier, live: false, probe: "" };
      channel.onValue = (event) => {
        const text = decoder.decode(event.target.value, { stream: true });
        if (channel.live) this.onText(text);
        else channel.probe += text;
      };
      try {
        await notifier.startNotifications();
        notifier.addEventListener("characteristicvaluechanged", channel.onValue);
        await this._send(writer, "ATI\r");
        for (let waited = 0; waited < PROBE_MS && !channel.probe; waited += 100) await sleep(100);
        if (channel.probe) {
          // ATI 응답의 나머지가 다 오기를 기다렸다 버린다
          for (let waited = 0; waited < 1000 && !/[>\x07]/.test(channel.probe); waited += 100) await sleep(100);
          return channel;
        }
      } catch {
        // 다음 조합을 시험한다
      }
      notifier.removeEventListener("characteristicvaluechanged", channel.onValue);
      await notifier.stopNotifications().catch(() => {});
      return null;
    }

    // MTU를 모를 때도 넘치지 않게 20바이트씩 나눠 쓴다(STPX·slcan 명령은 20바이트를 넘는다).
    async _send(writer, text) {
      const bytes = new TextEncoder().encode(text);
      for (let i = 0; i < bytes.length; i += BLE_CHUNK) {
        const chunk = bytes.slice(i, i + BLE_CHUNK);
        if (writer.properties.writeWithoutResponse) await writer.writeValueWithoutResponse(chunk);
        else await writer.writeValue(chunk);
      }
    }

    write(text) {
      if (!this.channel) return Promise.reject(new Error("진단기가 연결되어 있지 않습니다."));
      return this._send(this.channel.writer, text);
    }

    _release() {
      const channel = this.channel;
      this.channel = null;
      if (!channel) return;
      channel.notifier.removeEventListener("characteristicvaluechanged", channel.onValue);
      channel.notifier.stopNotifications().catch(() => {});
    }

    hint() {
      const c = this.channel;
      return c ? { service: c.service.uuid, write: c.writer.uuid, notify: c.notifier.uuid } : {};
    }

    async close() {
      const device = this.device;
      if (!device) return;
      device.removeEventListener("gattserverdisconnected", this._onDisconnect);
      this._release();
      if (device.gatt?.connected) device.gatt.disconnect();
    }
  }

  // 블루투스 클래식(SPP, RFCOMM)·USB 진단기. 통신 속도를 차례로 시험한다(USB CDC slcan은 속도와 상관없이 답한다).
  class SerialTransport {
    constructor() {
      this.kind = "serial";
      this.port = null;
      this.baud = null;
      this.onText = () => {};
      this.onLost = () => {};
      this._reader = null;
      this._reading = null;
      this._readActive = false;
      this._probe = null;
      this._onDisconnect = () => {
        this._stopReading();
        this.onLost(this);
      };
    }

    get supported() {
      return Boolean(navigator.serial);
    }

    keyOf(port) {
      return serialKey(port);
    }

    nameOf(port) {
      const info = port.getInfo ? port.getInfo() : {};
      return info.usbVendorId ? "USB 진단기" : "블루투스 SPP 진단기";
    }

    choose() {
      return navigator.serial.requestPort({ allowedBluetoothServiceClassIds: [SPP_UUID] });
    }

    async connect(port, hint = {}) {
      if (this.port && this.port !== port) await this.close();
      this.port = port;
      port.removeEventListener("disconnect", this._onDisconnect);
      port.addEventListener("disconnect", this._onDisconnect);
      const bauds = hint.baud ? [hint.baud, ...SERIAL_BAUDS.filter((b) => b !== hint.baud)] : SERIAL_BAUDS;
      for (const baudRate of bauds) {
        try {
          await port.open({ baudRate });
        } catch (error) {
          if (error.name !== "InvalidStateError") continue;
          // 이미 열려 있으면 닫고 이 속도로 다시 연다
          await this._close();
          try {
            await port.open({ baudRate });
          } catch {
            continue;
          }
        }
        this._startReading();
        if (await this._answers()) {
          this.baud = baudRate;
          return;
        }
        await this._close();
      }
      throw new Error("진단기가 응답하지 않습니다. 페어링·전원과 진단기 종류(ELM327·STN·slcan)를 확인하세요.");
    }

    async _answers() {
      const ask = async (text, test) => {
        this._probe = "";
        await this.write(text);
        for (let waited = 0; waited < 1500; waited += 100) {
          await sleep(100);
          if (test.test(this._probe)) return true;
        }
        return false;
      };
      try {
        return (await ask("ATI\r", /ELM|STN|OBD|v\d|\x07/i)) || (await ask("V\r", /V[0-9A-F]{4}/i));
      } catch {
        return false;
      } finally {
        await sleep(300);
        this._probe = null;
      }
    }

    // 프레이밍·패리티·버퍼 넘침 같은 오류는 회복된다. readable이 남아 있으면 다시 읽는다.
    _startReading() {
      const decoder = new TextDecoder();
      this._readActive = true;
      this._reading = (async () => {
        while (this._readActive && this.port?.readable) {
          const reader = this.port.readable.getReader();
          this._reader = reader;
          try {
            for (;;) {
              const { value, done } = await reader.read();
              if (done) break;
              const text = decoder.decode(value, { stream: true });
              if (this._probe !== null) this._probe += text;
              else this.onText(text);
            }
          } catch {
            await sleep(50);
          } finally {
            reader.releaseLock();
            this._reader = null;
          }
        }
      })();
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

    async write(text) {
      if (!this.port?.writable) throw new Error("진단기가 연결되어 있지 않습니다.");
      const writer = this.port.writable.getWriter();
      try {
        await writer.write(new TextEncoder().encode(text));
      } finally {
        writer.releaseLock();
      }
    }

    hint() {
      return { baud: this.baud };
    }

    async close() {
      if (!this.port) return;
      this.port.removeEventListener("disconnect", this._onDisconnect);
      await this._close();
    }
  }

  // 화면에는 연결 하나만 보인다. 어느 방식·명령 체계로 붙었든 같은 request·ready·status를 쓴다.
  class Connection extends EventTarget {
    constructor(config = {}) {
      super();
      this.profiles = config.profiles || [];
      this.known = config.devices || [];
      this.devicesUrl = config.devicesUrl || null;
      this.csrfToken = config.csrfToken || "";
      this.profile = null;
      this.ble = new BleTransport();
      this.serial = new SerialTransport();
      this.active = null;
      this.driver = null;
      this.entry = null;
      this.state = "idle";
      this.message = "";
      this.info = {};
      this.owner = null;
      this._queue = Promise.resolve();
      this._session = 0;
      for (const transport of [this.ble, this.serial]) {
        transport.onText = (text) => {
          if (transport === this.active) this.driver?.feed(text);
        };
        transport.onLost = (t) => this._lost(t);
      }
      Memory.migrate();
    }

    get supported() {
      return this.ble.supported || this.serial.supported;
    }

    get transport() {
      return this.active?.kind || "ble";
    }

    get dialect() {
      return this.driver?.dialect || null;
    }

    get ready() {
      return this.state === "ready";
    }

    get busy() {
      return Boolean(this.owner);
    }

    devices() {
      return Memory.list();
    }

    _emit(state, message = this.message) {
      this.state = state;
      this.message = message;
      this.dispatchEvent(new CustomEvent("status", { detail: { state, message } }));
    }

    // 진단기를 한 작업(스캔·빠른 점검·수집)만 쓰게 한다. 다른 작업이 쓰는 중이면 false.
    lock(owner) {
      if (this.owner && this.owner !== owner) return false;
      this.owner = owner;
      this._emit(this.state);
      return true;
    }

    unlock(owner) {
      if (this.owner !== owner) return;
      this.owner = null;
      this._emit(this.state);
    }

    _profileFor(name) {
      return this.profile || this.profiles.find((p) => p.namePrefix && name.startsWith(p.namePrefix)) || null;
    }

    // 이 브라우저에 기억이 없으면 서버 계정에 남은 같은 이름·방식의 진단기 설정으로 미리 채운다.
    _hintFor(transport, key, name) {
      const local = Memory.find(key);
      if (local) return local;
      const server = this.known.find((d) => d.transport === transport.kind && d.name === name);
      return server ? { dialect: server.dialect, protocol: server.protocol, service: server.serviceUuid,
        write: server.writeUuid, notify: server.notifyUuid, baud: server.settings?.baud,
        bitrate: server.settings?.bitrate, serverId: null } : {};
    }

    _check(session) {
      if (session !== this._session) throw new Error("연결을 취소했습니다.");
    }

    async _setup(transport, target, session) {
      const key = transport.keyOf(target);
      const name = transport.nameOf(target);
      const known = this._hintFor(transport, key, name);
      const profile = transport.kind === "ble" ? this._profileFor(name) : null;
      await transport.connect(target, {
        service: profile?.service || known.service, write: profile?.write || known.write,
        notify: profile?.notify || known.notify, baud: known.baud,
      });
      this._check(session);
      const attach = (listener) => {
        const previous = transport.onText;
        transport.onText = listener;
        return () => { transport.onText = previous; };
      };
      const dialect = profile?.dialect || known.dialect || await D.identify((text) => transport.write(text), attach);
      this._check(session);
      if (!dialect) throw new Error("진단기 명령 체계를 알아내지 못했습니다. ELM327·STN·slcan 진단기인지 확인하세요.");
      this.driver?.fail(new Error("진단기를 바꿨습니다."));
      const driver = D.create(dialect, (text) => transport.write(text));
      this.driver = driver;
      await driver.init({
        init: profile?.init || [], timeoutMs: profile?.timeout || 2000,
        protocol: known.protocol ? `ATSPA${known.protocol}` : "ATSP0", bitrate: profile?.canBitrate || known.bitrate,
      });
      this._check(session);
      const info = await driver.info();
      this._check(session);
      this.info = { name, ...info, dialect, transport: transport.kind, baud: transport.baud || null };
      this.entry = Memory.save({
        ...known, key, transport: transport.kind, id: target.id || null, name, dialect,
        chip: info.chip, version: info.version, ...transport.hint(), lastUsedAt: Date.now(),
      });
      this._emit("ready", `${name} 연결됨 (${D.DIALECTS[dialect]})`);
      this._sync(this.entry);
      this.dispatchEvent(new CustomEvent("devices"));
    }

    async _connect(transport, target) {
      await this._release();
      const session = ++this._session;
      this.active = transport;
      this._emit("connecting", `${transport.nameOf(target)}에 연결하는 중…`);
      let lastError;
      for (let attempt = 1; attempt <= CONNECT_TRIES; attempt += 1) {
        try {
          await this._setup(transport, target, session);
          return;
        } catch (error) {
          lastError = error;
          if (session !== this._session) return;
          if (attempt < CONNECT_TRIES) await sleep(1000);
        }
      }
      if (session !== this._session) return;
      this._emit("idle", `연결 실패: ${lastError.message}`);
      throw lastError;
    }

    // BLE는 끊기면 '연결 끊기'를 누르기 전까지 다시 붙는다.
    async _reconnect(transport, target) {
      const session = ++this._session;
      this.active = transport;
      while (session === this._session && this.state !== "ready") {
        this._emit("lost", "진단기를 찾는 중… 시동을 켜고 단말기를 꽂아 두세요.");
        try {
          await this._setup(transport, target, session);
        } catch {
          if (session === this._session) await sleep(RECONNECT_MS);
        }
      }
    }

    _lost(transport) {
      if (transport !== this.active) return;
      this.driver?.fail(new Error("진단기 연결이 끊겼습니다."));
      this.driver = null;
      if (transport.kind === "ble" && transport.device) {
        this._emit("lost", "진단기 연결이 끊겼습니다. 다시 연결하는 중…");
        this._reconnect(transport, transport.device);
      } else {
        this._session += 1;
        this._emit("idle", "진단기 연결이 끊겼습니다. 다시 연결하세요.");
      }
    }

    async _release() {
      this._session += 1;
      const driver = this.driver;
      this.driver = null;
      driver?.fail(new Error("연결을 끊었습니다."));
      await this.active?.close();
    }

    async find({ all = false } = {}) {
      if (!this.ble.supported) throw new Error("이 브라우저는 Web Bluetooth를 지원하지 않습니다.");
      const services = [...new Set([...this.profiles.map((p) => p.service).filter(Boolean), ...KNOWN_SERVICES]
        .map(uuid))];
      const prefixes = [...new Set([...NAME_PREFIXES, ...this.profiles.map((p) => p.namePrefix).filter(Boolean)])];
      const before = this.state;
      this._emit("searching", "진단기를 고르세요…");
      let device;
      try {
        device = await this.ble.choose({ all, services, prefixes });
      } catch (error) {
        this._emit(this.driver ? before : "idle",
          error.name === "NotFoundError" ? "진단기 선택을 취소했습니다." : `찾기 실패: ${error.message}`);
        throw error;
      }
      await this._connect(this.ble, device);
    }

    async findSerial() {
      if (!this.serial.supported) throw new Error("이 브라우저는 Web Serial을 지원하지 않습니다.");
      const before = this.state;
      this._emit("searching", "진단기 포트를 고르세요(블루투스는 먼저 페어링)…");
      let port;
      try {
        port = await this.serial.choose();
      } catch (error) {
        this._emit(this.driver ? before : "idle",
          error.name === "NotFoundError" ? "진단기 선택을 취소했습니다." : `찾기 실패: ${error.message}`);
        throw error;
      }
      await this._connect(this.serial, port);
    }

    // 기억한 진단기를 최근에 쓴 순서로, 이 사이트가 허락받은 기기 중에서 찾아 버튼 없이 연결한다.
    async autoConnect() {
      const bleDevices = this.ble.supported && navigator.bluetooth.getDevices
        ? await navigator.bluetooth.getDevices().catch(() => []) : [];
      const ports = this.serial.supported ? await navigator.serial.getPorts().catch(() => []) : [];
      for (const entry of Memory.list()) {
        if (entry.transport === "ble") {
          const device = bleDevices.find((d) => d.id === entry.id);
          if (device) {
            this._reconnect(this.ble, device);
            return true;
          }
        } else if (entry.transport === "serial") {
          const port = ports.find((p) => serialKey(p) === entry.key)
            || (entry.key === "serial:" && ports.length === 1 ? ports[0] : null);
          if (port) {
            await this._connect(this.serial, port).catch(() => {});
            return true;
          }
        }
      }
      return false;
    }

    async disconnect() {
      await this._release();
      this._emit("idle", "연결을 끊었습니다.");
    }

    // 기억 지우기: 연결 중이면 끊고, 브라우저 허락(BLE)과 서버 기록도 지운다.
    async forget(key) {
      const entry = Memory.find(key);
      if (!entry) return;
      if (this.entry?.key === key) {
        await this.disconnect();
        this.entry = null;
      }
      if (entry.transport === "ble" && navigator.bluetooth?.getDevices) {
        const devices = await navigator.bluetooth.getDevices().catch(() => []);
        await devices.find((d) => d.id === entry.id)?.forget?.().catch(() => {});
      }
      Memory.remove(key);
      if (entry.serverId && this.devicesUrl) {
        fetch(`${this.devicesUrl}/${entry.serverId}`, {
          method: "DELETE", credentials: "same-origin", headers: { "X-CSRFToken": this.csrfToken },
        }).catch(() => {});
      }
      this.dispatchEvent(new CustomEvent("devices"));
    }

    // 서버 계정에 남긴다(다른 기기·관리자 화면에서 확인, 처음 보는 기기의 설정 미리 채우기).
    async _sync(entry) {
      if (!this.devicesUrl) return;
      try {
        const response = await fetch(this.devicesUrl, {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json", "X-CSRFToken": this.csrfToken },
          body: JSON.stringify({
            transport: entry.transport, name: entry.name, dialect: entry.dialect, chip: entry.chip || "",
            version: entry.version || "", serviceUuid: entry.service || null, writeUuid: entry.write || null,
            notifyUuid: entry.notify || null, protocol: entry.protocol || null,
            settings: { baud: entry.baud || null, bitrate: entry.bitrate || null },
          }),
        });
        if (!response.ok) return;
        const data = await response.json();
        if (data.id && Memory.find(entry.key)) Memory.save({ ...Memory.find(entry.key), serverId: data.id });
      } catch {
        // 서버에 남기지 못해도 이 브라우저 기억으로 쓴다
      }
    }

    _enqueue(task) {
      const run = () => task();
      const result = this._queue.then(run, run);
      this._queue = result.catch(() => {});
      return result;
    }

    // 계획 단계 하나({header, command, timeoutMs})를 드라이버로 보낸다. 응답은 ELM 프레임 줄 형식.
    request(step) {
      return this._enqueue(() => {
        if (!this.driver || !this.ready) throw new Error("진단기가 연결되어 있지 않습니다.");
        return this.driver.request(step);
      });
    }

    send(command, timeoutMs) {
      return this.request({ command, timeoutMs });
    }

    supports(command) {
      return this.driver ? this.driver.supports(command) : true;
    }

    // 연결될 때까지 기다린다. stop()이 true이거나 연결을 끊으면(idle) 그만둔다.
    async waitReady(stop) {
      while (!this.ready) {
        if ((stop && stop()) || this.state === "idle") return false;
        await sleep(300);
      }
      return true;
    }

    // ATDPN으로 찾은 통신 방식(과 원시 CAN 속도)을 이 진단기에 기억해 다음 연결 때 먼저 시도한다.
    rememberProtocol(reply) {
      const token = (reply || "").toUpperCase().split(/[\s>]+/).reverse().find((t) => /^A?[1-9A-C]$/.test(t));
      const entry = this.entry && Memory.find(this.entry.key);
      if (!token || !entry) return;
      const protocol = token.slice(-1);
      const bitrate = this.driver?.bitrate || entry.bitrate;
      if (protocol === entry.protocol && bitrate === entry.bitrate) return;
      this.entry = Memory.save({ ...entry, protocol, bitrate });
      this._sync(this.entry);
    }
  }

  // 요청 목록을 rounds번 보내 '# WECAR-ELM 1' 기록 줄을 만든다. 끊기면 다시 연결된 뒤 같은 요청부터 잇는다.
  async function capture(link, requests, { vehicle, rounds = 1, onLog = () => {}, onRound = () => {}, stop = () => false }) {
    if (!link.lock("capture")) throw new Error("다른 작업(스캔)이 진단기를 쓰는 중입니다. 끝난 뒤 다시 누르세요.");
    try {
      const started = performance.now();
      const stamp = () => (performance.now() - started).toFixed(1);
      const lines = ["# WECAR-ELM 1", `# vehicle: ${vehicle}`, `# device: ${link.info.name || "-"}`,
        `# dialect: ${link.dialect || "-"}`, `# started: ${new Date().toISOString()}`, "# source: web"];
      for (let round = 1; round <= rounds && !stop(); round += 1) {
        onRound(round, rounds);
        for (let index = 0, tries = 0; index < requests.length && !stop(); index += 1) {
          const req = requests[index];
          let reply;
          try {
            if (!link.ready && !(await link.waitReady(stop))) break;
            reply = await link.request({ header: req.header, command: req.command });
            if (!link.ready) throw new Error("lost");
            tries = 0;
          } catch {
            tries += 1;
            if (tries < 3) index -= 1;
            else tries = 0;
            continue;
          }
          const payload = req.command.match(/.{2}/g);
          lines.push(`${stamp()} TX ${req.header} ${[hex(payload.length), ...payload].join(" ")}`);
          const found = P.frames(reply, req.header.length === 8 ? "can29" : "can11").filter((f) => f.can);
          found.forEach((f) => lines.push(`${stamp()} RX ${f.source} ${f.data.map(hex).join(" ")}`));
          onLog(`${req.header} ${req.command} → ${found.length ? `${found.length}개 프레임` : D.clean(reply) || "응답 없음"}`);
        }
      }
      return lines;
    } finally {
      link.unlock("capture");
    }
  }

  function readConfig() {
    const node = document.getElementById("obd-config");
    return node ? JSON.parse(node.textContent) : null;
  }

  function relative(ms) {
    const minutes = Math.round((Date.now() - ms) / 60000);
    if (minutes < 1) return "방금";
    if (minutes < 60) return `${minutes}분 전`;
    const hours = Math.round(minutes / 60);
    return hours < 48 ? `${hours}시간 전` : `${Math.round(hours / 24)}일 전`;
  }

  // _obd_panel.html의 버튼·상태 표시를 연결하고, 기억한 진단기가 있으면 바로 연결을 시도한다.
  function bindPanel(root, config) {
    const csrf = root.querySelector("[data-obd-csrf]")?.value || "";
    const link = new Connection({ ...config, csrfToken: csrf });
    const q = (selector) => root.querySelector(selector);
    const status = q("[data-obd-status]");
    const info = q("[data-obd-info]");
    const findBtn = q("[data-obd-find]");
    const serialBtn = q("[data-obd-find-serial]");
    const allBtn = q("[data-obd-find-all]");
    const offBtn = q("[data-obd-disconnect]");
    const select = q("[data-obd-profile]");
    const memory = q("[data-obd-devices]");
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

    function renderDevices() {
      if (!memory) return;
      const list = link.devices();
      memory.hidden = !list.length;
      memory.querySelector("ul").replaceChildren(...list.map((entry) => {
        const item = document.createElement("li");
        item.className = "flex flex-wrap items-center justify-between gap-2";
        const label = document.createElement("span");
        const dialect = entry.dialect ? ` · ${D.DIALECTS[entry.dialect] || entry.dialect}` : "";
        label.textContent = `${entry.name || "이름 없음"} (${TRANSPORT_LABELS[entry.transport] || entry.transport}${dialect}`
          + `${entry.lastUsedAt > 2 ? ` · ${relative(entry.lastUsedAt)}` : ""})`;
        const forget = document.createElement("button");
        forget.type = "button";
        forget.className = "btn btn-ghost";
        forget.textContent = "기억 지우기";
        forget.addEventListener("click", () => link.forget(entry.key));
        item.append(label, forget);
        return item;
      }));
    }

    const recent = link.devices()[0];
    if (recent) status.textContent = `최근 연결한 진단기: ${recent.name}. 시동을 켜고 '진단기 연결'을 누르세요.`;
    renderDevices();
    link.addEventListener("devices", renderDevices);
    select.addEventListener("change", () => {
      link.profile = config.profiles.find((p) => String(p.id) === select.value) || null;
      if (link.ready) status.textContent = "고른 진단기 종류는 다음 연결부터 적용됩니다.";
    });
    link.addEventListener("status", ({ detail }) => {
      status.textContent = detail.message;
      const busy = detail.state === "searching" || detail.state === "connecting";
      const locked = busy || detail.state === "ready" || link.busy;
      findBtn.disabled = locked || !link.ble.supported;
      allBtn.disabled = findBtn.disabled;
      if (serialBtn) serialBtn.disabled = locked || !link.serial.supported;
      offBtn.disabled = detail.state === "idle" || link.busy;
      info.hidden = detail.state !== "ready";
      if (detail.state === "ready") {
        q("[data-obd-name]").textContent = link.info.name || "-";
        const transport = q("[data-obd-transport]");
        if (transport) transport.textContent = TRANSPORT_LABELS[link.transport] || link.transport;
        const dialect = q("[data-obd-dialect]");
        if (dialect) dialect.textContent = D.DIALECTS[link.dialect] || "-";
        q("[data-obd-version]").textContent = link.info.version || "-";
        q("[data-obd-voltage]").textContent = link.info.voltage || (link.driver?.caps.voltage ? "-" : "측정 안 함");
      }
    });
    findBtn.addEventListener("click", () => link.find().catch(() => {}));
    serialBtn?.addEventListener("click", () => link.findSerial().catch(() => {}));
    allBtn.addEventListener("click", () => link.find({ all: true }).catch(() => {}));
    offBtn.addEventListener("click", () => link.disconnect());
    link.autoConnect().catch(() => {});
    return link;
  }

  window.WecarObd = { capture, readConfig, bindPanel, Memory };
})();
