// 진단기 명령 체계(드라이버). 연결 방식(BLE·시리얼)이 받은 글자를 넘겨 받고, 스캔 계획의 논리 요청
// {header, command}를 그 진단기의 명령으로 바꿔 보낸다. 응답은 언제나 ELM327 ATH1·ATS1 프레임 줄
// ('7E8 06 41 00 ..')로 돌려줘 obd-plan.js 평가와 서버 해석을 그대로 쓴다.
// - ELM327: AT 명령, '>' 프롬프트
// - STN(OBDLink 등): ELM327 호환 + STPX로 주소·데이터를 한 번에 보낸다
// - slcan(Lawicel 방식 원시 CAN 어댑터: CANable, ESP32·nRF BLE-CAN 등): ISO-TP를 직접 처리한다
// 기본 세션에서 읽기만 한다. 진단 세션(10)·보안 접근(27)·쓰기(2E)·루틴(31)은 계획에 없고 여기서도 만들지 않는다.
((root, factory) => {
  const node = typeof module === "object" && module.exports;
  const api = factory(node ? require("./obd-plan.js") : root.WecarObdPlan);
  if (node) module.exports = api;
  else root.WecarObdDriver = api;
})(typeof self !== "undefined" ? self : globalThis, (P) => {
  "use strict";

  const LATE_MS = 1000;
  const PENDING_RETRIES = 2;
  const PENDING_TIMEOUT_MS = 5000;
  const BUSY_DELAY_MS = 200;
  const DEFAULT_INIT = ["ATZ", "ATE0", "ATL0"];
  // ATH1·ATS1: 응답 주소와 공백을 붙여 받는다. ATCAF1: ISO-TP 형식. ATAT1: ECU 응답 속도에 맞춰 대기 시간 조절.
  const FORMAT_COMMANDS = ["ATH1", "ATS1", "ATCAF1", "ATAT1"];
  const DIALECTS = { elm327: "ELM327", stn: "STN(OBDLink)", slcan: "slcan(원시 CAN)" };

  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const hex = (n, width = 2) => n.toString(16).toUpperCase().padStart(width, "0");
  const bytesOf = (text) => (text.match(/../g) || []).map((b) => parseInt(b, 16));

  function clean(reply) {
    return (reply || "").replace(/SEARCHING\.\.\./g, "").replace(/>/g, "").trim();
  }

  // 받은 글자를 모아 두고, 조건이 맞으면 기다리던 쪽에 넘긴다. 연결이 끊기면 기다리던 명령을 바로 실패시킨다.
  class Port {
    constructor(write) {
      this.write = write;
      this.buffer = "";
      this.waiter = null;
      this.error = null;
    }

    feed(text) {
      this.buffer += text;
      this.waiter?.check();
    }

    fail(error) {
      this.error = error;
      this.waiter?.reject(error);
    }

    // test(buffer)가 undefined가 아닌 값을 돌려주면 그 값으로 끝난다. 시간이 지나면 undefined.
    wait(test, timeoutMs) {
      return new Promise((resolve, reject) => {
        if (this.error) {
          reject(this.error);
          return;
        }
        const finish = (fn, value) => {
          clearTimeout(timer);
          this.waiter = null;
          fn(value);
        };
        const timer = setTimeout(() => finish(resolve, undefined), timeoutMs);
        this.waiter = {
          check: () => {
            const value = test(this.buffer);
            if (value !== undefined) finish(resolve, value);
          },
          reject: (error) => finish(reject, error),
        };
        this.waiter.check();
      });
    }
  }

  // 단말기 오류·응답 대기(NRC 78)·사용 중(NRC 21)이면 한 번씩 복구해 다시 보낸다(obd-plan.js의 recovery 판정).
  async function withRecovery(driver, send, command, timeoutMs) {
    let reply = await send(command, timeoutMs);
    const action = P.recovery(reply, driver.bus, command);
    if (action === "stopped") {
      reply = await send(command, timeoutMs);
    } else if (action === "buffer" && driver.caps.bufferRecovery) {
      await driver.send("ATS0");
      reply = await send(command, timeoutMs);
      await driver.send("ATS1");
    } else if (action === "bus" && driver.caps.protocolClose) {
      await driver.send("ATPC");
      reply = await send(command, timeoutMs);
    } else if (action === "pending") {
      await driver.send("ATSTFF");
      try {
        for (let i = 0; i < PENDING_RETRIES && P.recovery(reply, driver.bus, command) === "pending"; i += 1) {
          reply = await send(command, Math.max(timeoutMs || 0, PENDING_TIMEOUT_MS));
        }
      } finally {
        await driver.send("ATST32");
      }
    } else if (action === "busy") {
      await sleep(BUSY_DELAY_MS);
      reply = await send(command, timeoutMs);
    }
    return reply;
  }

  class ElmDriver {
    constructor(write) {
      this.port = new Port(write);
      this.dialect = "elm327";
      this.caps = { kline: true, voltage: true, bufferRecovery: true, protocolClose: true };
      this.bus = null;
      this.header = null;
      this.desync = false;
    }

    feed(text) {
      this.port.feed(text);
    }

    fail(error) {
      this.port.fail(error);
    }

    // 시간이 지난 명령의 응답('>')이 늦게 오면 다음 명령 응답으로 읽힌다. 다음 명령 전에 기다렸다 버린다.
    async send(command, timeoutMs = 2000) {
      if (this.desync) {
        await this.port.wait((b) => (b.includes(">") ? true : undefined), LATE_MS);
        this.desync = false;
      }
      this.port.buffer = "";
      await this.port.write(`${command}\r`);
      const reply = await this.port.wait((b) => {
        const end = b.indexOf(">");
        return end >= 0 ? b.slice(0, end) : undefined;
      }, timeoutMs);
      if (reply === undefined) {
        this.desync = true;
        return "";
      }
      this.port.buffer = this.port.buffer.slice(reply.length + 1);
      return reply;
    }

    // 프로필 초기화 명령이 있으면 그것을 쓰고, 프로필이 정한 형식(예: ATS0)은 덮어쓰지 않는다.
    async init({ init = [], protocol = "ATSP0", timeoutMs = 2000 } = {}) {
      const base = init.length ? init : [...DEFAULT_INIT, protocol];
      const own = new Set(base.map((c) => c.slice(0, -1)));
      let answered = false;
      for (const command of [...base, ...FORMAT_COMMANDS.filter((c) => !own.has(c.slice(0, -1)))]) {
        const reply = await this.send(command, command === "ATZ" ? 4000 : timeoutMs);
        if (/OK|ELM|STN/i.test(reply)) answered = true;
      }
      if (!answered) throw new Error("진단기가 초기화 명령에 답하지 않습니다.");
      this.header = null;
    }

    async info() {
      const chip = clean(await this.send("STDI"));
      return {
        version: clean(await this.send("ATI")),
        chip: chip && chip !== "?" ? chip : "",
        voltage: clean(await this.send("ATRV")),
      };
    }

    supports() {
      return true;
    }

    reset() {
      this.header = null;
    }

    async target(header) {
      if (header === this.header) return;
      for (const command of P.headerCommands(header, this.bus)) await this.send(command);
      this.header = header;
    }

    // 계획 단계 하나. header가 없으면 기능(브로드캐스트) 주소로 보낸다.
    async request({ header = null, command, timeoutMs }) {
      if (/^(AT|ST)/.test(command)) {
        const reply = await this.send(command, timeoutMs);
        if (command === "ATDPN") this.bus = P.busOf(reply) || this.bus;
        return reply;
      }
      const want = header || (this.header ? P.BROADCAST[this.bus] || "7DF" : null);
      if (want) await this.target(want);
      return withRecovery(this, (c, t) => this.send(c, t), command, timeoutMs);
    }

    async close() {}
  }

  // STN 칩은 버퍼가 커서 BUFFER FULL 복구가 필요 없다. 주소 지정 요청은 STPX(h: 주소, d: 데이터, t: 대기 ms)로
  // 한 번에 보내 ATSH·ATCP 왕복을 줄인다. 오래된 펌웨어가 STPX를 모르면('?') ELM 방식으로 돌아간다.
  class StnDriver extends ElmDriver {
    constructor(write) {
      super(write);
      this.dialect = "stn";
      this.caps = { ...this.caps, bufferRecovery: false };
      this.stpx = true;
      this.filter = null;
    }

    async _filter(header) {
      const want = header ? P.headerCommands(header, this.bus).find((c) => c.startsWith("ATCRA")) || "ATCRA" : "ATCRA";
      if (want === this.filter) return;
      await this.send(want);
      this.filter = want;
    }

    reset() {
      super.reset();
      this.filter = null;
    }

    async request(step) {
      const { header = null, command, timeoutMs } = step;
      if (!this.stpx || /^(AT|ST)/.test(command)) return super.request(step);
      if (!header) {
        await this._filter(null);
        return withRecovery(this, (c, t) => this.send(c, t), command, timeoutMs);
      }
      await this._filter(header);
      const send = (c, t) => this.send(`STPX h:${header}, d:${c}, t:${t || 2000}`, (t || 2000) + 500);
      const reply = await withRecovery(this, send, command, timeoutMs);
      if (clean(reply) !== "?") return reply;
      this.stpx = false;
      this.filter = null;
      return super.request(step);
    }
  }

  // --- slcan(Lawicel) ---
  const SLCAN_SPEED = { 125000: "S4", 250000: "S5", 500000: "S6", 1000000: "S8" };
  // 찾은 CAN 속도·주소 길이 → ELM327 통신 방식 번호(ATDPN). 6·7: 500k 11/29비트, 8·9: 250k 11/29비트.
  const PROTOCOL_CODE = { "500000:can11": "6", "500000:can29": "7", "250000:can11": "8", "250000:can29": "9" };
  const BUS_ORDER = [[500000, "can11"], [500000, "can29"], [250000, "can11"], [250000, "can29"]];

  // 't7E8806410098...'·'T18DAF1108...' → {id, data}. 뒤에 붙은 타임스탬프는 버린다.
  function parseSlcan(line) {
    const match = /^(t([0-9A-F]{3})|T([0-9A-F]{8}))([0-8])([0-9A-F]*)$/i.exec(line);
    if (!match) return null;
    const length = Number(match[4]);
    const data = match[5];
    if (data.length < length * 2) return null;
    return { id: (match[2] || match[3]).toUpperCase(), data: bytesOf(data.slice(0, length * 2)) };
  }

  function slcanFrame(id, data) {
    return `${id.length === 8 ? "T" : "t"}${id}${data.length}${data.map((b) => hex(b)).join("")}`;
  }

  // 요청 바이트 → CAN 프레임(8바이트, 0 채움). 7바이트까지 단일 프레임, 넘으면 첫 프레임 + 연속 프레임.
  function segment(payload) {
    const pad = (frame) => [...frame, ...Array(8 - frame.length).fill(0)];
    if (payload.length <= 7) return [pad([payload.length, ...payload])];
    const frames = [pad([0x10 | (payload.length >> 8), payload.length & 0xff, ...payload.slice(0, 6)])];
    for (let i = 6, seq = 1; i < payload.length; i += 7, seq += 1) {
      frames.push(pad([0x20 | (seq & 0x0f), ...payload.slice(i, i + 7)]));
    }
    return frames;
  }

  // 이 요청에 대한 응답 주소인가. 기능 주소면 범위, 물리 주소면 짝 주소 하나.
  function answers(header, id) {
    if (header === "7DF") return /^7E[89A-F]$/.test(id);
    if (header === "18DB33F1") return id.startsWith("18DAF1");
    if (header.length === 8) return id === `18DAF1${header.slice(4, 6)}`;
    return id === hex(parseInt(header, 16) + 8, 3);
  }

  // 응답 주소 → 흐름 제어를 보낼 요청 주소
  function requestIdFor(source) {
    if (source.length === 8) return `18DA${source.slice(6, 8)}${source.slice(4, 6)}`;
    return hex(parseInt(source, 16) - 8, 3);
  }

  const toLine = (frame) => [frame.id, ...frame.data.map((b) => hex(b))].join(" ");

  class SlcanDriver {
    constructor(write) {
      this.write = write;
      this.dialect = "slcan";
      this.caps = { kline: false, voltage: false, bufferRecovery: false, protocolClose: false };
      this.bus = null;
      this.bitrate = null;
      this.open = false;
      this.buffer = "";
      this.ack = null;
      this.collector = null;
      this.error = null;
    }

    feed(text) {
      this.buffer += text;
      for (;;) {
        const end = this.buffer.search(/[\r\x07]/);
        if (end < 0) break;
        const token = this.buffer.slice(0, end).trim();
        const nack = this.buffer[end] === "\x07";
        this.buffer = this.buffer.slice(end + 1);
        const frame = nack ? null : parseSlcan(token);
        if (frame) this.collector?.(frame);
        else if (this.ack) this.ack(nack ? null : token);
      }
    }

    fail(error) {
      this.error = error;
      this.ack?.(null, error);
    }

    // 어댑터 명령 하나. 응답 글자(빈 문자열 포함)를 돌려주고, 거부(BEL)·시간 초과면 null.
    cmd(text, timeoutMs = 1000) {
      if (this.error) return Promise.reject(this.error);
      return new Promise((resolve, reject) => {
        const timer = setTimeout(() => done(null), timeoutMs);
        const done = (token, error) => {
          clearTimeout(timer);
          this.ack = null;
          if (error) reject(error);
          else resolve(token);
        };
        this.ack = done;
        this.write(`${text}\r`).catch((error) => done(null, error));
      });
    }

    async init({ bitrate } = {}) {
      await this.cmd("C");
      this.version = (await this.cmd("V")) || "";
      if (!/^V/i.test(this.version)) throw new Error("slcan 어댑터가 버전 명령(V)에 답하지 않습니다.");
      await this.cmd("Z0");
      this.preferred = SLCAN_SPEED[bitrate] ? Number(bitrate) : null;
      this.bus = null;
      this.open = false;
    }

    async info() {
      return { version: this.version || "", chip: "slcan", voltage: "" };
    }

    // 원시 CAN 어댑터에는 전압·통신 방식 찾기가 없다. ATDPN은 찾은 CAN 속도로 답한다.
    supports(command) {
      return !/^(AT|ST)/.test(command) || command === "ATDPN";
    }

    reset() {
      this.open = false;
      this.bus = null;
    }

    async _openAt(bitrate) {
      if (this.open && this.bitrate === bitrate) return true;
      if (this.open) await this.cmd("C");
      if ((await this.cmd(SLCAN_SPEED[bitrate])) === null) return false;
      if ((await this.cmd("O")) === null) return false;
      this.bitrate = bitrate;
      this.open = true;
      return true;
    }

    // 처음 OBD 요청 때 CAN 속도·주소 길이를 0100 기능 주소 요청으로 찾는다(시동이 켜져 있어야 함).
    async _findBus() {
      const order = this.preferred
        ? BUS_ORDER.filter(([rate]) => rate === this.preferred)
        : BUS_ORDER;
      for (const [rate, bus] of order) {
        if (!(await this._openAt(rate))) continue;
        const reply = await this.collect(P.BROADCAST[bus], [0x01, 0x00], 1000);
        if (reply !== "NO DATA") {
          this.bus = bus;
          return true;
        }
      }
      return false;
    }

    // 요청을 보내고 응답 프레임을 모은다. 여러 프레임 응답이면 흐름 제어를 보내고, NRC 78이면 최종 응답까지 기다린다.
    async collect(header, payload, timeoutMs = 2000) {
      const lines = [];
      const open = new Map();
      const pending = new Set();
      let messages = 0;
      let last = Date.now();
      let deadline = last + timeoutMs;
      let flow = null;
      const broadcast = header === "7DF" || header === "18DB33F1";
      this.collector = (frame) => {
        if (!answers(header, frame.id)) return;
        last = Date.now();
        lines.push(toLine(frame));
        const [pci, ...rest] = frame.data;
        const kind = pci >> 4;
        if (kind === 3) {
          if (flow) flow(frame.data);
          return;
        }
        if (kind === 1) {
          open.set(frame.id, { length: ((pci & 0x0f) << 8) | rest[0], received: 6 });
          this.write(`${slcanFrame(requestIdFor(frame.id), [0x30, 0, 0, 0, 0, 0, 0, 0])}\r`).catch(() => {});
          return;
        }
        if (kind === 2 && open.has(frame.id)) {
          const state = open.get(frame.id);
          state.received += 7;
          if (state.received >= state.length) {
            open.delete(frame.id);
            messages += 1;
          }
          return;
        }
        if (kind !== 0) return;
        const message = rest.slice(0, pci & 0x0f);
        messages += 1;
        if (message[0] === 0x7f && message[2] === 0x78) {
          pending.add(frame.id);
          deadline = Math.max(deadline, Date.now() + PENDING_TIMEOUT_MS);
        } else {
          pending.delete(frame.id);
        }
      };
      try {
        const frames = segment(payload);
        if (frames.length > 1) {
          const fc = new Promise((resolve) => { flow = resolve; });
          await this.write(`${slcanFrame(header, frames[0])}\r`);
          const control = await Promise.race([fc, sleep(1000).then(() => null)]);
          flow = null;
          if (!control || control[0] !== 0x30) return "NO DATA";
          const gap = control[2] <= 0x7f ? control[2] : 1;
          for (const frame of frames.slice(1)) {
            await sleep(gap);
            await this.write(`${slcanFrame(header, frame)}\r`);
          }
        } else {
          await this.write(`${slcanFrame(header, frames[0])}\r`);
        }
        const quiet = broadcast ? 150 : 50;
        while (Date.now() < deadline) {
          if (this.error) throw this.error;
          await sleep(10);
          if (messages && !open.size && !pending.size && Date.now() - last >= quiet) break;
        }
      } finally {
        this.collector = null;
      }
      return lines.length ? lines.join("\r") : "NO DATA";
    }

    async request({ header = null, command, timeoutMs }) {
      if (command === "ATDPN") return this.bus ? `A${PROTOCOL_CODE[`${this.bitrate}:${this.bus}`]}` : "";
      if (!this.supports(command)) return "?";
      if (!this.bus && !(await this._findBus())) return "NO DATA";
      const target = header || P.BROADCAST[this.bus];
      const send = async () => this.collect(target, bytesOf(command), timeoutMs || 2000);
      let reply = await send();
      if (P.recovery(reply, this.bus, command) === "busy") {
        await sleep(BUSY_DELAY_MS);
        reply = await send();
      }
      return reply;
    }

    async close() {
      if (this.open) await this.cmd("C").catch(() => null);
      this.open = false;
    }
  }

  const DRIVERS = { elm327: ElmDriver, stn: StnDriver, slcan: SlcanDriver };

  function create(dialect, write) {
    return new (DRIVERS[dialect] || ElmDriver)(write);
  }

  // 어떤 명령 체계인지 묻는다: ATI에 ELM·STN이 답하면 STDI로 STN을 가리고, 아니면 slcan 버전(V)을 묻는다.
  async function identify(write, attach) {
    const port = new Port(write);
    const detach = attach((text) => port.feed(text));
    const ask = async (command, test, timeoutMs) => {
      port.buffer = "";
      await write(`${command}\r`);
      return (await port.wait(test, timeoutMs)) ?? port.buffer;
    };
    const prompt = (b) => (b.includes(">") ? b : undefined);
    try {
      const ati = await ask("ATI", prompt, 2000);
      if (/ELM|STN|OBD|>/i.test(ati)) {
        const chip = clean(await ask("STDI", prompt, 1500));
        return chip && chip !== "?" && !/ELM/i.test(chip) ? "stn" : "elm327";
      }
      await sleep(200);
      const version = await ask("V", (b) => (/V[0-9A-F]{4}\r/i.test(b) ? b : undefined), 1000);
      return /V[0-9A-F]{4}/i.test(version) ? "slcan" : null;
    } finally {
      detach();
    }
  }

  return {
    DIALECTS, FORMAT_COMMANDS, PENDING_TIMEOUT_MS, clean, Port, ElmDriver, StnDriver, SlcanDriver, create, identify,
    parseSlcan, slcanFrame, segment, answers, requestIdFor,
  };
});
