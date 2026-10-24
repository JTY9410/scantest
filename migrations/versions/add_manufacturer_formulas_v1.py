"""제조사별 해석 수식 추가 - Phase 1

Revision ID: add_manufacturer_formulas_v1
Revises: add_manufacturer_commands_v1
Create Date: 2026-10-24 12:35:00

제조사별 명령어의 응답을 해석하는 수식 추가
"""
from alembic import op
import sqlalchemy as sa
from datetime import datetime


# revision identifiers, used by Alembic.
revision = 'add_manufacturer_formulas_v1'
down_revision = 'add_manufacturer_commands_v1'
branch_labels = None
depends_on = None


def upgrade():
    """제조사별 해석 수식 추가"""
    
    formulas = [
        # ==================== 현대/기아/제네시스 ====================
        {
            "maker": "현대", "model": None, "ecu_name": "배터리 관리(BMS)",
            "command": "22B001", "pid": "B001",
            "label": "총 주행거리", "detail_name": "차량 누적 주행거리 (km)",
            "formula": "(A[0] << 24 | A[1] << 16 | A[2] << 8 | A[3]) / 10",
            "unit": "km",
            "example_input": "B001: 00 01 86 A0",
            "example_output": "10000",
            "notes": "4바이트 빅엔디안, 스케일 ×0.1 (미터 → km). 예: 0x000186A0 = 100000 → 10000 km",
            "source": "reverse_analysis",
            "source_detail": "Hyundai EV 데이터 분석",
            "confidence": 0.6,
            "status": "experimental"
        },
        {
            "maker": "기아", "model": None, "ecu_name": "배터리 관리(BMS)",
            "command": "22B002", "pid": "B002",
            "label": "EV 모드 주행거리", "detail_name": "전기 모드 누적 주행거리 (km)",
            "formula": "(A[0] << 24 | A[1] << 16 | A[2] << 8 | A[3]) / 10",
            "unit": "km",
            "example_input": "B002: 00 00 4E 20",
            "example_output": "2000",
            "notes": "4바이트 빅엔디안, 스케일 ×0.1. PHEV 전용.",
            "source": "reverse_analysis",
            "source_detail": "Kia PHEV 분석",
            "confidence": 0.6,
            "status": "experimental"
        },
        {
            "maker": "제네시스", "model": None, "ecu_name": "하이브리드 제어(HCU)",
            "command": "22B010", "pid": "B010",
            "label": "엔진 가동 시간", "detail_name": "ICE 누적 가동 시간 (시간)",
            "formula": "(A[0] << 24 | A[1] << 16 | A[2] << 8 | A[3]) / 3600",
            "unit": "hours",
            "example_input": "B010: 00 02 A3 00",
            "example_output": "3.0",
            "notes": "4바이트 리틀엔디안 (초 단위), 시간으로 변환. HEV/PHEV 전용.",
            "source": "reverse_analysis",
            "source_detail": "Genesis HEV 분석",
            "confidence": 0.6,
            "status": "experimental"
        },
        
        # 검증된 수식
        {
            "maker": "현대", "model": None, "ecu_name": "배터리 관리(BMS)",
            "command": "220101", "pid": "0101",
            "label": "배터리 SOC", "detail_name": "배터리 충전 상태 (%)",
            "formula": "A[0] / 2",
            "unit": "%",
            "example_input": "0101: C8",
            "example_output": "100",
            "notes": "1바이트, 스케일 ×0.5. 예: 0xC8 (200) → 100%",
            "source": "public_docs",
            "source_detail": "Hyundai 정비 매뉴얼",
            "confidence": 0.95,
            "status": "verified"
        },
        {
            "maker": "기아", "model": None, "ecu_name": "배터리 관리(BMS)",
            "command": "220102", "pid": "0102",
            "label": "배터리 전압", "detail_name": "고전압 배터리 전압 (V)",
            "formula": "(A[0] << 8 | A[1]) / 10",
            "unit": "V",
            "example_input": "0102: 0F A0",
            "example_output": "400.0",
            "notes": "2바이트 빅엔디안, 스케일 ×0.1. 예: 0x0FA0 (4000) → 400.0V",
            "source": "public_docs",
            "source_detail": "Kia EV 매뉴얼",
            "confidence": 0.95,
            "status": "verified"
        },
        {
            "maker": "현대", "model": None, "ecu_name": "배터리 관리(BMS)",
            "command": "220103", "pid": "0103",
            "label": "배터리 전류", "detail_name": "충방전 전류 (A)",
            "formula": "((A[0] << 8 | A[1]) - 32768) / 10",
            "unit": "A",
            "example_input": "0103: 85 00",
            "example_output": "5.6",
            "notes": "2바이트 빅엔디안, 부호 있음 (32768 = 0 A). 스케일 ×0.1. 양수=방전, 음수=충전.",
            "source": "public_docs",
            "source_detail": "Hyundai 매뉴얼",
            "confidence": 0.9,
            "status": "verified"
        },
        {
            "maker": "현대", "model": None, "ecu_name": "배터리 관리(BMS)",
            "command": "220105", "pid": "0105",
            "label": "배터리 온도", "detail_name": "배터리 평균 온도 (°C)",
            "formula": "A[0] - 40",
            "unit": "°C",
            "example_input": "0105: 41",
            "example_output": "25",
            "notes": "1바이트, 오프셋 -40. 예: 0x41 (65) → 25°C",
            "source": "public_docs",
            "source_detail": "Hyundai 통합 매뉴얼",
            "confidence": 0.95,
            "status": "verified"
        },
        {
            "maker": "기아", "model": None, "ecu_name": "모터 제어(MCU)",
            "command": "220201", "pid": "0201",
            "label": "모터 회전수", "detail_name": "모터 RPM",
            "formula": "(A[0] << 8 | A[1]) - 10000",
            "unit": "RPM",
            "example_input": "0201: 27 10",
            "example_output": "0",
            "notes": "2바이트 빅엔디안, 오프셋 -10000. 정지 시 0x2710 (10000).",
            "source": "public_docs",
            "source_detail": "Kia Motor Control 문서",
            "confidence": 0.85,
            "status": "verified"
        },
        {
            "maker": "현대", "model": None, "ecu_name": "모터 제어(MCU)",
            "command": "220202", "pid": "0202",
            "label": "모터 토크", "detail_name": "출력 토크 (Nm)",
            "formula": "((A[0] << 8 | A[1]) - 32768) * 0.5",
            "unit": "Nm",
            "example_input": "0202: 80 C8",
            "example_output": "10.0",
            "notes": "2바이트 빅엔디안, 부호 있음 (32768 = 0 Nm). 스케일 ×0.1 또는 ×0.5 가능.",
            "source": "public_docs",
            "source_detail": "Hyundai MCU 문서",
            "confidence": 0.8,
            "status": "verified"
        },
        
        # ==================== Nissan Leaf ====================
        {
            "maker": "닛산", "model": "LEAF", "ecu_name": "배터리 관리(BMS)",
            "command": "2101", "pid": "01",
            "label": "배터리 SOH", "detail_name": "배터리 건강도 (%)",
            "formula": "A[33] / 2",
            "unit": "%",
            "example_input": "01: ... [바이트33]=C8",
            "example_output": "100",
            "notes": "응답 바이트 인덱스 33, 스케일 ×0.5. LeafSpy 검증.",
            "source": "reverse_analysis",
            "source_detail": "LeafSpy, Nissan 커뮤니티",
            "confidence": 0.95,
            "status": "verified"
        },
        {
            "maker": "닛산", "model": "LEAF", "ecu_name": "배터리 관리(BMS)",
            "command": "2102", "pid": "02",
            "label": "배터리 용량", "detail_name": "현재 가용 용량 (Ah)",
            "formula": "(A[0] << 8 | A[1]) / 100",
            "unit": "Ah",
            "example_input": "02: 1A 0A",
            "example_output": "66.66",
            "notes": "2바이트 빅엔디안, 스케일 ×0.01.",
            "source": "reverse_analysis",
            "source_detail": "LeafSpy",
            "confidence": 0.9,
            "status": "verified"
        },
        {
            "maker": "NISSAN", "model": "LEAF", "ecu_name": "배터리 관리(BMS)",
            "command": "2103", "pid": "03",
            "label": "셀 전압 (최대)", "detail_name": "최고 셀 전압 (mV)",
            "formula": "(A[0] << 8 | A[1])",
            "unit": "mV",
            "example_input": "03: 0F D0",
            "example_output": "4048",
            "notes": "2바이트 빅엔디안 (밀리볼트).",
            "source": "reverse_analysis",
            "source_detail": "LeafSpy",
            "confidence": 0.85,
            "status": "verified"
        },
        {
            "maker": "닛산", "model": "LEAF", "ecu_name": "배터리 관리(BMS)",
            "command": "2104", "pid": "04",
            "label": "셀 전압 (최소)", "detail_name": "최저 셀 전압 (mV)",
            "formula": "(A[0] << 8 | A[1])",
            "unit": "mV",
            "example_input": "04: 0F C8",
            "example_output": "4040",
            "notes": "2바이트 빅엔디안.",
            "source": "reverse_analysis",
            "source_detail": "LeafSpy",
            "confidence": 0.85,
            "status": "verified"
        },
        
        # ==================== 범용 OBD-II ====================
        {
            "maker": None, "model": None, "ecu_name": "하이브리드 제어(HCU)",
            "command": "0105", "pid": "05",
            "label": "냉각수 온도", "detail_name": "엔진 냉각수 온도 (°C)",
            "formula": "A[0] - 40",
            "unit": "°C",
            "example_input": "05: 50",
            "example_output": "40",
            "notes": "OBD-II 표준 PID. 오프셋 -40.",
            "source": "public_docs",
            "source_detail": "SAE J1979",
            "confidence": 1.0,
            "status": "verified"
        },
        {
            "maker": None, "model": None, "ecu_name": "하이브리드 제어(HCU)",
            "command": "010C", "pid": "0C",
            "label": "엔진 RPM", "detail_name": "엔진 회전수",
            "formula": "((A[0] << 8 | A[1]) / 4)",
            "unit": "RPM",
            "example_input": "0C: 1A F8",
            "example_output": "1726",
            "notes": "OBD-II 표준. 2바이트, 스케일 ×0.25.",
            "source": "public_docs",
            "source_detail": "SAE J1979",
            "confidence": 1.0,
            "status": "verified"
        },
    ]
    
    # 데이터 삽입
    conn = op.get_bind()
    
    for formula_data in formulas:
        # 중복 체크
        result = conn.execute(
            sa.text("""
                SELECT id FROM knowledge_formulas 
                WHERE maker IS NOT DISTINCT FROM :maker 
                AND command = :command 
                AND label = :label
                LIMIT 1
            """),
            {
                "maker": formula_data["maker"],
                "command": formula_data["command"],
                "label": formula_data["label"]
            }
        )
        existing = result.fetchone()
        
        if existing:
            continue
        
        # 삽입
        conn.execute(
            sa.text("""
                INSERT INTO knowledge_formulas (
                    maker, model, ecu_name, command, pid, label, detail_name,
                    formula, unit, example_input, example_output, notes,
                    source, source_detail, confidence, status,
                    created_at, updated_at
                ) VALUES (
                    :maker, :model, :ecu_name, :command, :pid, :label, :detail_name,
                    :formula, :unit, :example_input, :example_output, :notes,
                    :source, :source_detail, :confidence, :status,
                    :created_at, :updated_at
                )
            """),
            {
                **formula_data,
                "model": formula_data.get("model"),
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            }
        )
    
    print(f"Added {len(formulas)} manufacturer-specific formulas to knowledge base")


def downgrade():
    """마이그레이션 되돌리기"""
    conn = op.get_bind()
    
    conn.execute(
        sa.text("""
            DELETE FROM knowledge_formulas 
            WHERE source IN ('public_docs', 'reverse_analysis')
            AND maker IN ('현대', '기아', '제네시스', '닛산', 'NISSAN')
        """)
    )
    
    print("Removed Phase 1 manufacturer formulas")
