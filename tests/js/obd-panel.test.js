// node --test tests/js
const test = require("node:test");
const assert = require("node:assert/strict");
const { obdPanelState } = require("../../app/static/js/components/obd-link.js");

test("기억한 진단기가 없으면 '진단기 연결하기' 안내를 띄운다", () => {
  const st = obdPanelState({ remembered: 0, ble: true, serial: true, secure: true });
  assert.equal(st.firstTime, true);
  assert.equal(st.findDisabled, false);
  assert.equal(st.reason, "");
  assert.match(st.firstMessage, /이전에 연결한 진단기가 없습니다. 진단기 연결하기를 눌러 검색하세요/);
});

test("한 번 연결한 진단기가 있으면 자동 감지만 한다", () => {
  assert.equal(obdPanelState({ remembered: 1, ble: true, secure: true }).firstTime, false);
});

test("HTTPS가 아니면 버튼을 끄고 이유를 보여준다", () => {
  const st = obdPanelState({ remembered: 0, ble: false, serial: false, secure: false });
  assert.equal(st.findDisabled, true);
  assert.equal(st.firstTime, false);
  assert.match(st.reason, /HTTPS/);
});

test("BLE가 없으면 이유를 보여주고 시리얼은 안내한다", () => {
  const st = obdPanelState({ remembered: 0, ble: false, serial: true, secure: true });
  assert.equal(st.findDisabled, true);
  assert.match(st.reason, /블루투스 클래식·USB/);
  assert.match(obdPanelState({ ble: false, serial: false }).reason, /지원하지 않습니다/);
});
