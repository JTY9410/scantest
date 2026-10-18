// 스캔 계획 실행 규칙(웹). 서버 plan.py의 when·expand를 평가하고, ELM327 응답에서 다음 단계에 필요한 값을 읽는다.
// 화면과 상관없는 순수 함수라 node --test로 시험한다(tests/js/obd-plan.test.js).
((root, factory) => {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.WecarObdPlan = api;
})(typeof self !== "undefined" ? self : globalThis, () => {
  "use strict";

  const BROADCAST = { can11: "7DF", can29: "18DB33F1" };
  const BUS = { 1: "serial", 2: "serial", 3: "serial", 4: "serial", 5: "serial", 6: "can11", 7: "can29",
    8: "can11", 9: "can29", A: "can29", B: "can11", C: "can11" };
  // CAN은 모드 01 요청 하나에 PID를 6개까지 묶을 수 있다(SAE J1979).
  const BATCH = 6;
  const SUPPORT_RANGE = /^(01|06|09)(00|20|40|60|80|A0|C0|E0)$/;
  const WHEN_SERVICE = { pid: "01", pid02: "02", info09: "09", mid: "06" };

  const hex = (n, width = 2) => n.toString(16).toUpperCase().padStart(width, "0");

  // ATS0(공백 없음) 줄을 ATS1 모양으로 바꾼다. 11비트 CAN은 길이가 홀수다.
  function spaced(line, bus) {
    if (!/^[0-9A-F]{6,}$/.test(line)) return line;
    let head = "";
    let body = line;
    if (line.length % 2) [head, body] = [line.slice(0, 3), line.slice(3)];
    else if (bus === "can29") [head, body] = [line.slice(0, 8), line.slice(8)];
    return [head, ...body.match(/../g)].filter(Boolean).join(" ");
  }

  // 응답 문자열 → 프레임 {source, data}. CAN 11비트 '7E8 ..', 29비트 '18DAF110 ..'·'18 DA F1 10 ..', K-Line 3바이트 헤더.
  function frames(reply, bus) {
    const result = [];
    for (const raw of (reply || "").split(/[\r\n>]+/)) {
      const line = spaced(raw.trim().toUpperCase(), bus);
      let match = /^([0-9A-F]{3}|[0-9A-F]{8})((?:\s[0-9A-F]{2})+)$/.exec(line);
      if (match) {
        result.push({ can: true, source: match[1], data: match[2].trim().split(/\s+/).map((b) => parseInt(b, 16)) });
        continue;
      }
      match = /^[0-9A-F]{2}(?:\s[0-9A-F]{2})+$/.exec(line);
      if (!match) continue;
      const data = line.split(/\s+/).map((b) => parseInt(b, 16));
      if (bus === "can29" && data.length > 4) {
        result.push({ can: true, source: data.slice(0, 4).map((b) => hex(b)).join(""), data: data.slice(4) });
      } else if (bus !== "can11" && data.length >= 5) {
        result.push({ can: false, source: hex(data[2]), data: data.slice(3, -1) });
      }
    }
    return result;
  }

  // ECU(응답 주소)별 메시지. CAN은 ISO-TP 단일·첫·연속 프레임을 합친다(흐름 제어 프레임은 버린다).
  function messages(reply, bus) {
    const out = new Map();
    const open = new Map();
    const push = (source, payload) => {
      if (!out.has(source)) out.set(source, []);
      out.get(source).push(payload);
    };
    for (const frame of frames(reply, bus)) {
      if (!frame.can) {
        if (frame.data.length) push(frame.source, frame.data);
        continue;
      }
      const [pci, ...rest] = frame.data;
      const kind = pci >> 4;
      if (kind === 0) {
        const length = pci & 0x0f;
        if (length && rest.length >= length) push(frame.source, rest.slice(0, length));
      } else if (kind === 1 && rest.length) {
        open.set(frame.source, { length: ((pci & 0x0f) << 8) | rest[0], data: rest.slice(1) });
      } else if (kind === 2 && open.has(frame.source)) {
        const message = open.get(frame.source);
        message.data.push(...rest);
        if (message.data.length >= message.length) {
          push(frame.source, message.data.slice(0, message.length));
          open.delete(frame.source);
        }
      }
    }
    return out;
  }

  const payloads = (reply, bus) => [...messages(reply, bus).values()].flat();

  // 지원 비트맵 '41 base A B C D'(모드 02는 '42 00 프레임 A B C D'). 여러 ECU가 답하면 합친다.
  function bitmap(reply, bus, service, base) {
    const found = new Set();
    const offset = service === 0x02 ? 3 : 2;
    for (const p of payloads(reply, bus)) {
      if (p[0] !== service + 0x40 || p[1] !== base || p.length < offset + 4) continue;
      p.slice(offset, offset + 4).forEach((value, k) => {
        for (let bit = 0; bit < 8; bit += 1) if (value & (0x80 >> bit)) found.add(base + k * 8 + bit + 1);
      });
    }
    return found;
  }

  // '41 01 A ..' A 하위 7비트 = 저장된 고장코드 수(ECU 합). 답이 없으면 null.
  function dtcCount(reply, bus) {
    let count = null;
    for (const p of payloads(reply, bus)) {
      if (p[0] === 0x41 && p[1] === 0x01 && p.length > 2) count = (count || 0) + (p[2] & 0x7f);
    }
    return count;
  }

  // '59 02 마스크 [DTC 3바이트 상태]..'에서 확정(상태 bit3) 고장코드 6자리.
  function confirmedDtcs(reply, bus) {
    const codes = [];
    for (const p of payloads(reply, bus)) {
      if (p[0] !== 0x59 || p[1] !== 0x02) continue;
      for (let i = 3; i + 3 < p.length; i += 4) {
        const code = p.slice(i, i + 3).map((b) => hex(b)).join("");
        if (p[i + 3] & 0x08 && code !== "000000" && !codes.includes(code)) codes.push(code);
      }
    }
    return codes;
  }

  function busOf(reply) {
    const tokens = (reply || "").toUpperCase().split(/[\s>]+/).reverse();
    const token = tokens.find((t) => /^A?[1-9A-C]$/.test(t));
    return token ? BUS[token.slice(-1)] : null;
  }

  // 단말기 오류별 복구(한 번): STOPPED는 다시 보내고, 버퍼·수신 오류는 공백을 빼고(ATS0), CAN·초기화 오류는
  // 프로토콜을 닫고(ATPC) 다시 보낸다. 응답 대기(NRC 78)만 오면 시간 제한을 늘려(ATST FF) 다시 보내고,
  // 사용 중(NRC 21)이면 잠시 뒤 다시 보낸다.
  function recovery(reply, bus, command) {
    const text = (reply || "").toUpperCase();
    if (/STOPPED/.test(text)) return "stopped";
    if (/BUFFER FULL|RX ERROR|DATA ERROR/.test(text)) return "buffer";
    if (/CAN ERROR|BUS INIT|BUS ERROR/.test(text)) return "bus";
    const service = parseInt(command.slice(0, 2), 16);
    const found = payloads(reply, bus);
    const nrc = (code) => found.some((p) => p[0] === 0x7f && p[1] === service && p[2] === code);
    const positive = found.some((p) => p[0] === service + 0x40);
    const final = positive || found.some((p) => p[0] === 0x7f && p[1] === service && p[2] !== 0x78);
    if (nrc(0x78) && !final) return "pending";
    return nrc(0x21) && !positive ? "busy" : null;
  }

  // 14 FF FF FF 응답에 긍정(54)이 있는지. 없으면(거부·무응답) 04 대체 지우기를 보낸다.
  function clearAnswered(reply, bus) {
    return payloads(reply, bus).some((p) => p[0] === 0x54);
  }

  function newContext() {
    return { bus: null, dead: new Set(), support: {}, dtcCount: null, dtcs: {}, speed: null, clearFailed: false };
  }

  // 이 차량에서 쓸 요청 주소. 29비트 CAN은 header29, 없으면 null(보내지 않음).
  function headerFor(step, ctx) {
    if (!step.header) return null;
    if (ctx.bus === "can29") return step.header29 || null;
    return step.header;
  }

  function skipReason(step, ctx) {
    if (step.bus === "can" && ctx.bus === "serial") return "K-Line·J1850 차량이라 CAN 전용 조회를 건너뛰었습니다.";
    if (step.header && ctx.bus === "can29" && !step.header29) {
      return "29비트 CAN 차량이라 11비트 주소 조회를 건너뛰었습니다.";
    }
    const header = headerFor(step, ctx);
    if (header && ctx.dead.has(header)) return `${header} 제어기가 응답하지 않아 건너뛰었습니다.`;
    const when = step.when || {};
    if (step.group === "clear" && ctx.speed) return `차가 움직이고 있어(차속 ${ctx.speed} km/h) 지우지 않았습니다.`;
    if (when.clear_fallback && !when.obd_dtcs && !ctx.clearFailed) {
      return "모든 제어기가 14 FF FF FF로 지워졌고 OBD 고장코드가 없어 04는 보내지 않았습니다.";
    }
    if (when.dtc && ctx.dtcCount === 0) return "저장된 고장코드가 없어 건너뛰었습니다.";
    for (const [key, service] of Object.entries(WHEN_SERVICE)) {
      if (when[key] === undefined) continue;
      const known = ctx.support[service] || (key === "pid02" ? ctx.support["01"] : null);
      if (known && !known.has(parseInt(when[key], 16))) return "차량이 지원하지 않는 항목입니다(지원 목록에 없음).";
    }
    return null;
  }

  // 단계 하나 → 실제로 보낼 요청 [{command, label}]. 빈 배열이면 skipReason 대신 이유를 돌려준다.
  function requests(step, ctx) {
    if (step.expand === "pids") {
      const known = ctx.support["01"];
      const pids = (step.pids || []).filter((p) => !known || known.has(parseInt(p, 16)));
      if (!pids.length) return { items: [], reason: "차량이 지원하지 않는 항목입니다(지원 PID 없음)." };
      const size = ctx.bus && ctx.bus.startsWith("can") ? BATCH : 1;
      const items = [];
      for (let i = 0; i < pids.length; i += size) {
        const chunk = pids.slice(i, i + size);
        items.push({ command: `01${chunk.join("")}`, label: `${step.label} (${chunk.join("·")})` });
      }
      return { items };
    }
    if (step.expand === "mids") {
      const mids = [...(ctx.support["06"] || [])].filter((m) => m % 0x20).sort((a, b) => a - b);
      if (!mids.length) return { items: [], reason: "차량이 지원하지 않는 항목입니다(지원 점검 항목 없음)." };
      return { items: mids.map((m) => ({ command: `06${hex(m)}`, label: `${step.label} MID ${hex(m)}` })) };
    }
    if (step.expand === "dtcs") {
      const codes = (ctx.dtcs[headerFor(step, ctx)] || []).slice(0, step.limit || 3);
      if (!codes.length) return { items: [], reason: "이 제어기에 확정 고장코드가 없어 건너뛰었습니다." };
      return { items: codes.map((c) => ({ command: `1904${c}FF`, label: `${step.label} ${c}` })) };
    }
    return { items: [{ command: step.command, label: step.label }] };
  }

  // 응답을 받은 뒤 다음 단계 판단에 쓸 값을 모은다.
  function observe(step, command, reply, ctx) {
    if (command === "14FFFFFF" && step.group === "clear" && !reply) ctx.clearFailed = true;
    if (!reply) return;
    if (command === "ATDPN") ctx.bus = busOf(reply);
    const range = SUPPORT_RANGE.exec(command);
    if (range) {
      const service = range[1];
      const found = bitmap(reply, ctx.bus, parseInt(service, 16), parseInt(range[2], 16));
      if (found.size) ctx.support[service] = new Set([...(ctx.support[service] || []), ...found]);
    }
    if (command === "020000") {
      const found = bitmap(reply, ctx.bus, 0x02, 0);
      if (found.size) ctx.support["02"] = found;
    }
    if (command === "0101") ctx.dtcCount = dtcCount(reply, ctx.bus);
    if (command === "010D" && step.group === "clear_check") {
      const p = payloads(reply, ctx.bus).find((x) => x[0] === 0x41 && x[1] === 0x0d && x.length > 2);
      ctx.speed = p ? p[2] : null;
    }
    const header = headerFor(step, ctx);
    if (command === "14FFFFFF" && step.group === "clear" && !clearAnswered(reply, ctx.bus)) ctx.clearFailed = true;
    if (command === "1902FF" && header) ctx.dtcs[header] = confirmedDtcs(reply, ctx.bus);
    if (step.probe && header && /NO DATA|CAN ERROR|UNABLE/i.test(reply)) ctx.dead.add(header);
  }

  // 응답 주소가 요청+8이 아닌 제어기(위카 앱 dev 순회 목록). 앱 obd_plan.dart에도 같은 표를 둔다.
  const REPLY_OVERRIDE = { "717": "71D" };

  // 요청 주소 설정 명령. 29비트는 우선순위(ATCP)와 나머지 3바이트(ATSH), 수신 필터는 응답 주소(ATCRA).
  function headerCommands(header, bus) {
    if (!header) return [];
    const broadcast = header === BROADCAST.can11 || header === BROADCAST.can29;
    if (header.length === 8) {
      const reply = header.startsWith("18DA") ? `18DA${header.slice(6)}${header.slice(4, 6)}` : null;
      return [`ATCP${header.slice(0, 2)}`, `ATSH${header.slice(2)}`, broadcast || !reply ? "ATCRA" : `ATCRA${reply}`];
    }
    const reply = REPLY_OVERRIDE[header] || hex(parseInt(header, 16) + 8, 3);
    return [`ATSH${header}`, broadcast || bus === "serial" ? "ATCRA" : `ATCRA${reply}`];
  }

  return { BROADCAST, BATCH, REPLY_OVERRIDE, clearAnswered, spaced, frames, messages, bitmap, dtcCount, confirmedDtcs, busOf, recovery, newContext,
    headerFor, skipReason, requests, observe, headerCommands };
});
