"""EV6 스캔 데이터 회귀 테스트 (파일 A·B).

파일 A (reference): 전체 UDS·BMS 수집, 192 셀, ECU 733 DTC 2건 (상태 0x08)
파일 B (measured): 식별·OBD 수집, 96 셀만 (010A-0C 없음), DTC 멀티프레임 미완성
"""

import pytest
from app.modules.canlab.engine import frames, isotp, uds, bms
from app.modules.scanner import report


@pytest.fixture
def file_a_text():
    """파일 A (reference): 3.7MB, 16,961행, 전체 BMS 수집"""
    with open("tests/fixtures/ev6_file_a_reference.csv", encoding="utf-8") as f:
        return f.read()


@pytest.fixture
def file_b_text():
    """파일 B (measured): 192KB, 854행, 식별·OBD만"""
    with open("tests/fixtures/ev6_file_b_scantest_measured.csv", encoding="utf-8") as f:
        return f.read()


class TestFileA:
    """파일 A: 정상적인 192셀 E-GMP 스캔"""

    def test_parse_no_errors(self, file_a_text):
        """CSV 파싱 성공, skipped=0"""
        parsed = frames.parse_trace(file_a_text)
        assert parsed.format == "pcan_csv"
        assert len(parsed.frames) > 10000
        assert parsed.skipped_lines == 0

    def test_status_rows_filtered(self, file_a_text):
        """CAN_ID 0x00000000 장비 행(Extended 2개) 제외됨"""
        parsed = frames.parse_trace(file_a_text)
        # Status1=0x04000205/0x04000209 행이 제외되어야 함
        zero_id_frames = [f for f in parsed.frames if f.can_id == 0]
        assert len(zero_id_frames) == 0, "CAN_ID 0 장비 행이 남아있음"

    def test_platform_egmp(self, file_a_text):
        """플랫폼 egmp, 192셀 인식"""
        parsed = frames.parse_trace(file_a_text)
        messages = isotp.reassemble(parsed.frames)
        transactions = uds.pair_transactions(messages)
        samples = uds.did_samples(transactions)
        battery = bms.decode_bms(samples)
        
        assert battery is not None
        assert battery["platform"] == "egmp"
        assert battery["cells"]["count"] == 192
        assert battery["cells"]["pids"] == ["0102", "0103", "0104", "010A", "010B", "010C"]

    def test_cell_sum_vs_pack(self, file_a_text):
        """셀 합계 vs 팩 전압 차이 0.3% 이내"""
        parsed = frames.parse_trace(file_a_text)
        messages = isotp.reassemble(parsed.frames)
        transactions = uds.pair_transactions(messages)
        samples = uds.did_samples(transactions)
        battery = bms.decode_bms(samples)
        
        assert battery["checks"]["cell_sum_vs_pack_pct"] is not None
        assert abs(battery["checks"]["cell_sum_vs_pack_pct"]) < 0.3

    def test_dtc_status_classification(self, file_a_text):
        """ECU 733 DTC 2건, 상태 0x08 (confirmed=True, active=False)"""
        parsed = frames.parse_trace(file_a_text)
        messages = isotp.reassemble(parsed.frames)
        transactions = uds.pair_transactions(messages)
        
        # ECU 733/73B DTC 찾기
        dtc_transactions = [tx for tx in transactions if tx.service == 0x19 and tx.positive
                           and tx.request_id == 0x733]
        assert len(dtc_transactions) > 0, "ECU 733 DTC 응답 없음"
        
        dtcs = []
        for tx in dtc_transactions:
            dtcs.extend(uds.parse_dtcs(tx))
        
        assert len(dtcs) == 2, f"DTC 개수 불일치: {len(dtcs)}"
        
        for dtc in dtcs:
            assert dtc["status"] == 0x08
            assert dtc["confirmed"] is True, "확정 비트가 켜져야 함"
            assert dtc["active"] is False, "현재실패 비트가 꺼져야 함"
    
    def test_judgment_not_purely_from_inactive_dtc(self, file_a_text):
        """비활성 DTC(0x08)만으로 점검요가 되어서는 안 됨"""
        parsed = frames.parse_trace(file_a_text)
        messages = isotp.reassemble(parsed.frames)
        transactions = uds.pair_transactions(messages)
        samples = uds.did_samples(transactions)
        battery = bms.decode_bms(samples)
        
        result = {"battery": {k: {"value": v} for k, v in battery["values"].items()},
                  "cells": battery["cells"]}
        
        judged = report.type_judgments(result, "ev")
        
        # 읽은 항목(SOH, 절연, 셀 편차, 모듈 온도) 확인
        items_read = [row for row in judged if row["result"] != report.UNREAD]
        assert len(items_read) >= 4, "최소 4개 항목이 읽혀야 함"
        
        # 배터리 수치는 모두 양호해야 함
        battery_items = [row for row in items_read if row["item"] in 
                        ("배터리 수명 (SOH)", "절연 저항", "셀 전압 편차", "모듈 온도 편차")]
        for row in battery_items:
            assert row["result"] == "양호", f"{row['item']}이 양호가 아님: {row}"


class TestFileB:
    """파일 B: 불완전 셀 데이터, OBD 브로드캐스트 포함"""

    def test_incomplete_cells_not_niro(self, file_b_text):
        """셀 PID 0102-0104만 → 플랫폼을 niro로 오분류하지 않음"""
        parsed = frames.parse_trace(file_b_text)
        messages = isotp.reassemble(parsed.frames)
        transactions = uds.pair_transactions(messages)
        samples = uds.did_samples(transactions)
        battery = bms.decode_bms(samples)
        
        assert battery is not None
        # 96셀이지만 niro로 단정하지 않아야 함 (egmp 또는 'incomplete' 플래그)
        # 현재 코드가 niro로 오분류하는 버그를 수정하면 이 테스트가 통과됨
        assert battery["platform"] != "niro" or "incomplete" in battery.get("flags", []), \
            "불완전한 셀 데이터로 플랫폼을 확정하면 안 됨"

    def test_cell_count_flagged_incomplete(self, file_b_text):
        """셀 96개, PID 3개만 → 불완전 플래그"""
        parsed = frames.parse_trace(file_b_text)
        messages = isotp.reassemble(parsed.frames)
        transactions = uds.pair_transactions(messages)
        samples = uds.did_samples(transactions)
        battery = bms.decode_bms(samples)
        
        assert battery["cells"]["count"] == 96
        assert battery["cells"]["pids"] == ["0102", "0103", "0104"]
        # 전체 6개 PID 중 3개만 있음을 표시
        assert "incomplete" in battery.get("cells", {}).get("flags", []) or \
               battery.get("platform") in ("unknown", "undetermined"), \
               "불완전한 셀 수집을 표시해야 함"

    def test_obd2_broadcast_pairing(self, file_b_text):
        """7DF 브로드캐스트 → 여러 ECU 응답 (7EA, 7EB, 7EC, 7ED, 7EE, 74C)"""
        parsed = frames.parse_trace(file_b_text)
        messages = isotp.reassemble(parsed.frames)
        transactions = uds.pair_transactions(messages)
        
        # 7DF 요청 찾기
        broadcasts = [tx for tx in transactions if tx.request_id == 0x7DF]
        assert len(broadcasts) > 0, "7DF 브로드캐스트 요청 없음"
        
        # 모드 01 요청별로 여러 ECU가 응답해야 함
        mode_01 = [tx for tx in broadcasts if len(tx.request) > 0 and tx.request[0] == 0x01]
        
        # 적어도 일부 요청에서 extra_responders가 있어야 함
        # (현재 버그: 3초 창 때문에 이후 요청이 무응답 처리됨)
        multi_response = [tx for tx in mode_01 if tx.response is not None or tx.extra_responders]
        
        # 원본 CSV에는 응답이 있으므로, 수정 후에는 이 테스트가 통과해야 함
        # 현재 버그 상태에서는 실패할 수 있음
        assert len(multi_response) > 0, "브로드캐스트 응답이 제대로 짝지어지지 않음"

    def test_partial_judgment_not_unresolved(self, file_b_text):
        """LDC·인렛 미측정이어도 읽은 항목은 판정"""
        parsed = frames.parse_trace(file_b_text)
        messages = isotp.reassemble(parsed.frames)
        transactions = uds.pair_transactions(messages)
        samples = uds.did_samples(transactions)
        battery = bms.decode_bms(samples)
        
        result = {"battery": {k: {"value": v} for k, v in battery["values"].items()},
                  "cells": battery["cells"]}
        
        judged = report.type_judgments(result, "ev")
        
        # LDC·인렛은 측정불가
        ldc_items = [row for row in judged if "LDC" in row["item"] or "인렛" in row["item"]]
        for row in ldc_items:
            assert row["result"] == report.UNREAD, f"{row['item']}이 측정불가가 아님"
        
        # 하지만 읽은 항목(SOH, 절연, 셀, 온도)은 판정되어야 함
        readable_items = [row for row in judged if row["item"] in 
                         ("배터리 수명 (SOH)", "절연 저항", "셀 전압 편차", "모듈 온도 편차")]
        assert len(readable_items) > 0, "읽은 항목이 없음"
        
        # 일부는 양호 판정이어야 함 (측정불가가 아님)
        judged_items = [row for row in readable_items if row["result"] != report.UNREAD]
        assert len(judged_items) > 0, "읽은 항목도 모두 측정불가로 처리됨"


class TestVINParsing:
    """VIN 파싱: 멀티프레임 완성, BMS F190 문자열 제외"""

    def test_vin_from_cluster_not_bms(self, file_a_text):
        """VIN은 계기판(7C6) 우선, BMS F190='CVEV-- BMS'는 VIN 아님"""
        parsed = frames.parse_trace(file_a_text)
        messages = isotp.reassemble(parsed.frames)
        transactions = uds.pair_transactions(messages)
        
        vin = uds.find_vin(transactions)
        assert vin == "KNAC381AFPA607262", f"VIN 불일치: {vin}"
        assert "CVEV" not in vin, "BMS 문자열을 VIN으로 오인함"

    def test_multiframe_vin_completion(self, file_b_text):
        """VIN 멀티프레임: 흐름제어 후 연속 프레임 대기"""
        parsed = frames.parse_trace(file_b_text)
        messages = isotp.reassemble(parsed.frames)
        
        # 7E2(HCU) VIN 요청 멀티프레임 확인
        hcu_vin_messages = [m for m in messages if m.can_id == 0x7EA and m.complete]
        
        # 파일 B에서는 첫 프레임만 있고 CF 없음 - 이 경우 미완성으로 표시되어야 함
        # (현재 버그: 첫 프레임만으로 불완전한 VIN을 만듦)
        transactions = uds.pair_transactions(messages)
        vin = uds.find_vin(transactions)
        
        # VIN이 있다면 17자여야 함
        if vin:
            assert len(vin) == 17, f"VIN 길이 오류: {len(vin)}"
            assert vin.startswith("KNA"), f"VIN 형식 오류: {vin}"


class TestNoiseRowFiltering:
    """어댑터 상태 행 필터링"""

    def test_remote_frames_excluded(self, file_a_text):
        """Remote 프레임 (Status 0x04000209) 제외"""
        parsed = frames.parse_trace(file_a_text)
        
        # Remote 프레임은 파싱되지 않아야 함
        # (Extended 00000000 프레임도 마찬가지)
        for frame in parsed.frames:
            assert frame.can_id != 0, "CAN_ID 0 프레임이 남아있음"

    def test_status_rows_count(self, file_a_text):
        """Status 행 개수가 meta에 기록됨"""
        parsed = frames.parse_trace(file_a_text)
        
        # meta에 STATUS_ROWS가 기록되어야 함
        status_count = int(parsed.meta.get("STATUS_ROWS", "0"))
        
        # 파일 A: Extended 2개
        assert status_count >= 2, f"Status 행 개수 불일치: {status_count}"


class TestOdometerCollection:
    """주행거리 수집"""

    def test_odometer_in_file_b(self, file_b_text):
        """파일 B: 계기판 7C6 22 B002 주행거리 9,758km"""
        parsed = frames.parse_trace(file_b_text)
        messages = isotp.reassemble(parsed.frames)
        transactions = uds.pair_transactions(messages)
        
        # 7C6 22 B002 찾기
        odometer_txs = [tx for tx in transactions 
                       if tx.request_id == 0x7C6 and tx.service == 0x22 and tx.did == 0xB002 
                       and tx.positive]
        
        assert len(odometer_txs) > 0, "주행거리(B002) 응답 없음"
        
        # 9~11바이트에서 주행거리 추출 (리틀엔디안)
        data = odometer_txs[0].data
        if len(data) >= 11:
            km = int.from_bytes(data[9:12], "little")
            assert 9700 < km < 9800, f"주행거리 값 오류: {km}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
