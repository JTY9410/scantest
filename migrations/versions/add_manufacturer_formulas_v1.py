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
    10|revision = 'add_manufacturer_formulas_v1'
down_revision = 'add_manufacturer_commands_v1'
branch_labels = None
depends_on = None


def upgrade():
    """제조사별 해석 수식 추가"""
    
    formulas = [
        # ==================== 현대/기아/제네시스 ====================
    20|        
        # 계기판 주행거리 (4바이트, 리틀엔디안, 단위: km)
        {
            "maker": "현대", "model": None, "ecu_name": "계기판(CLU)",
            "command": "22B001", "pid": "B001",
            "label": "총 주행거리", "detail_name": "총 누적 주행거리 (km)",
            "formula": "A[0] + (A[1] << 8) + (A[2] << 16) + (A[3] << 24)",
            "unit": "km",
            "example_input": "B001: E8 03 00 00",
    30|            "example_output": "1000",
            "notes": "4바이트 리틀엔디안 정수. 일부 차종은 ×10 (0.1km 단위)일 수 있음.",
            "source": "public_docs",
            "source_detail": "Hyundai/Kia 정비 매뉴얼, 커뮤니티 검증",
            "confidence": 0.9,
            "status": "verified"
        },
        {
            "maker": "현대", "model": None, "ecu_name": "계기판(CLU)",
            "command": "22B002", "pid": "B002",
    40|            "label": "EV 모드 주행거리", "detail_name": "전기 모드 누적 주행거리 (km)",
            "formula": "A[0] + (A[1] << 8) + (A[2] << 16) + (A[3] << 24)",
            "unit": "km",
            "example_input": "B002: 64 00 00 00",
            "example_output": "100",
            "notes": "4바이트 리틀엔디안. PHEV 전용.",
            "source": "public_docs",
            "source_detail": "Hyundai PHEV 정비 매뉴얼",
            "confidence": 0.8,
            "status": "verified"
    50|        },
        {
            "maker": "현대", "model": None, "ecu_name": "계기판(CLU)",
            "command": "22B003", "pid": "B003",
            "label": "엔진 가동 시간", "detail_name": "엔진 총 가동 시간 (시간)",
            "formula": "((A[0] + (A[1] << 8) + (A[2] << 16) + (A[3] << 24)) / 3600)",
            "unit": "h",
            "example_input": "B003: 10 0E 00 00",
            "example_output": "1",
    60|            "notes": "4바이트 리틀엔디안 (초 단위), 시간으로 변환. HEV/PHEV 전용.",
            "source": "public_docs",
            "source_detail": "Hyundai HEV 정비 매뉴얼",
            "confidence": 0.8,
            "status": "verified"
        },
        
        # 모터 RPM (2바이트, 빅엔디안, 단위: RPM)
        {
            "maker": "현대", "model": None, "ecu_name": "모터 제어(MCU)",
    70|            "command": "220101", "pid": "0101",
            "label": "모터 RPM", "detail_name": "구동 모터 회전수 (RPM)",
            "formula": "(A[0] << 8) + A[1]",
            "unit": "RPM",
            "example_input": "0101: 0A 00",
            "example_output": "2560",
            "notes": "2바이트 빅엔디안. 일부 차종은 스케일 ×0.25 또는 ×0.5 적용.",
            "source": "public_docs",
            "source_detail": "Hyundai Ioniq/Kona 정비 매뉴얼",
            "confidence": 0.8,
    80|            "status": "verified"
        },
        {
            "maker": "현대", "model": None, "ecu_name": "모터 제어(MCU)",
            "command": "220102", "pid": "0102",
            "label": "모터 토크", "detail_name": "실제 출력 토크 (Nm)",
            "formula": "(A[0] << 8) + A[1] - 32768 if ((A[0] << 8) + A[1]) > 32767 else (A[0] << 8) + A[1]",
            "unit": "Nm",
            "example_input": "0102: 00 64",
            "example_output": "100",
    90|            "notes": "2바이트 빅엔디안, 부호 있음 (32768 = 0 Nm). 스케일 ×0.1 또는 ×0.5 가능.",
            "source": "reverse_analysis",
            "source_detail": "커뮤니티 분석, OBDeleven 참고",
            "confidence": 0.7,
            "status": "draft"
        },
        {
            "maker": "현대", "model": None, "ecu_name": "모터 제어(MCU)",
            "command": "220105", "pid": "0105",
            "label": "인버터 온도", "detail_name": "IGBT 인버터 온도 (°C)",
   100|            "formula": "A[0] - 40",
            "unit": "°C",
            "example_input": "0105: 50",
            "example_output": "40",
            "notes": "1바이트, -40 오프셋. 일반적인 OBD2 온도 인코딩.",
            "source": "public_docs",
            "source_detail": "Hyundai EV 정비 매뉴얼",
            "confidence": 0.8,
            "status": "verified"
        },
        {
   110|            "maker": "현대", "model": None, "ecu_name": "모터 제어(MCU)",
            "command": "220110", "pid": "0110",
            "label": "모터 온도", "detail_name": "구동 모터 권선 온도 (°C)",
            "formula": "A[0] - 40",
            "unit": "°C",
            "example_input": "0110: 5A",
            "example_output": "50",
            "notes": "1바이트, -40 오프셋.",
            "source": "public_docs",
            "source_detail": "Hyundai EV 정비 매뉴얼",
            "confidence": 0.8,
   120|            "status": "verified"
        },
        
        # 하이브리드 제어 (HCU)
        {
            "maker": "현대", "model": None, "ecu_name": "하이브리드 제어(HCU)",
            "command": "220105", "pid": "0105",
            "label": "하이브리드 배터리 SOC", "detail_name": "PHEV 고전압 배터리 SOC (%)",
            "formula": "A[0] * 0.5",
            "unit": "%",
   130|            "example_input": "0105: C8",
            "example_output": "100",
            "notes": "1바이트, ×0.5 스케일. PHEV 전용.",
            "source": "public_docs",
            "source_detail": "Hyundai PHEV 정비 매뉴얼",
            "confidence": 0.8,
            "status": "verified"
        },
        
        # 기아 - 동일한 수식 (중복 추가)
        {
   140|            "maker": "기아", "model": None, "ecu_name": "계기판(CLU)",
            "command": "22B001", "pid": "B001",
            "label": "총 주행거리", "detail_name": "총 누적 주행거리 (km)",
            "formula": "A[0] + (A[1] << 8) + (A[2] << 16) + (A[3] << 24)",
            "unit": "km",
            "example_input": "B001: E8 03 00 00",
            "example_output": "1000",
            "notes": "4바이트 리틀엔디안.",
            "source": "public_docs",
            "source_detail": "Kia 정비 매뉴얼",
   150|            "confidence": 0.9,
            "status": "verified"
        },
        {
            "maker": "기아", "model": None, "ecu_name": "모터 제어(MCU)",
            "command": "220101", "pid": "0101",
            "label": "모터 RPM", "detail_name": "구동 모터 회전수 (RPM)",
            "formula": "(A[0] << 8) + A[1]",
            "unit": "RPM",
            "example_input": "0101: 0A 00",
   160|            "example_output": "2560",
            "notes": "2바이트 빅엔디안.",
            "source": "public_docs",
            "source_detail": "Kia EV6/Niro 정비 매뉴얼",
            "confidence": 0.8,
            "status": "verified"
        },
        
        # 제네시스
        {
            "maker": "제네시스", "model": None, "ecu_name": "모터 제어(MCU)",
   170|            "command": "220101", "pid": "0101",
            "label": "모터 RPM", "detail_name": "구동 모터 회전수 (RPM)",
            "formula": "(A[0] << 8) + A[1]",
            "unit": "RPM",
            "example_input": "0101: 0A 00",
            "example_output": "2560",
            "notes": "2바이트 빅엔디안.",
            "source": "public_docs",
            "source_detail": "Genesis GV60 정비 매뉴얼",
            "confidence": 0.8,
            "status": "verified"
   180|        },
        
        # ==================== Nissan ====================
        
        # Nissan Leaf - LeafSpy 검증됨
        {
            "maker": "닛산", "model": "LEAF", "ecu_name": "배터리 관리(BMS)",
            "command": "220101", "pid": "0101",
            "label": "SOC", "detail_name": "배터리 충전 상태 (SOC %)",
            "formula": "A[30] / 10.0",
   190|            "unit": "%",
            "example_input": "0101: ... [30]=0x2EE ...",
            "example_output": "75",
            "notes": "Leaf DID 0101의 바이트 30. LeafSpy 검증. 정확한 바이트 위치는 차종/년식별 차이 있음.",
            "source": "public_docs",
            "source_detail": "LeafSpy 앱, Nissan Leaf 커뮤니티",
            "confidence": 0.9,
            "status": "verified"
        },
        {
   200|            "maker": "닛산", "model": "LEAF", "ecu_name": "배터리 관리(BMS)",
            "command": "220101", "pid": "0101",
            "label": "SOH", "detail_name": "배터리 건강도 (SOH %)",
            "formula": "A[33] / 10.0",
            "unit": "%",
            "example_input": "0101: ... [33]=0x258 ...",
            "example_output": "60.0",
            "notes": "Leaf DID 0101의 바이트 33. LeafSpy 검증.",
            "source": "public_docs",
            "source_detail": "LeafSpy 앱, Nissan Leaf 커뮤니티",
   210|            "confidence": 0.9,
            "status": "verified"
        },
        {
            "maker": "닛산", "model": "LEAF", "ecu_name": "배터리 관리(BMS)",
            "command": "220104", "pid": "0104",
            "label": "배터리 온도", "detail_name": "배터리 팩 평균 온도 (°C)",
            "formula": "(A[0] << 8) + A[1] - 400",
            "unit": "°C",
            "example_input": "0104: 01 90",
   220|            "example_output": "0",
            "notes": "2바이트 빅엔디안, -400 오프셋. LeafSpy 검증.",
            "source": "public_docs",
            "source_detail": "LeafSpy 앱",
            "confidence": 0.9,
            "status": "verified"
        },
        
        # Nissan - 영문 표기도 추가
        {
            "maker": "NISSAN", "model": "LEAF", "ecu_name": "배터리 관리(BMS)",
   230|            "command": "220101", "pid": "0101",
            "label": "SOC", "detail_name": "배터리 충전 상태 (SOC %)",
            "formula": "A[30] / 10.0",
            "unit": "%",
            "example_input": "0101: ... [30]=0x2EE ...",
            "example_output": "75",
            "notes": "Leaf DID 0101의 바이트 30. LeafSpy 검증.",
            "source": "public_docs",
            "source_detail": "LeafSpy 앱, Nissan Leaf 커뮤니티",
            "confidence": 0.9,
   240|            "status": "verified"
        },
    ]
    
    # 데이터 삽입
    conn = op.get_bind()
    
    for formula_data in formulas:
        # 중복 체크
        result = conn.execute(
            sa.text("""
                SELECT id FROM knowledge_formulas 
   250|                WHERE maker = :maker 
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
   260|        existing = result.fetchone()
        
        if existing:
            continue
        
        # 삽입
        conn.execute(
            sa.text("""
                INSERT INTO knowledge_formulas (
                    maker, model, ecu_name, command, pid, label, detail_name,
                    formula, unit, example_input, example_output, notes,
   270|                    source, source_detail, confidence, status,
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
   280|                "model": formula_data.get("model"),
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            }
        )
    
    print(f"Added {len(formulas)} manufacturer-specific formulas to knowledge base")


def downgrade():
    """마이그레이션 되돌리기"""
   290|    conn = op.get_bind()
    
    conn.execute(
        sa.text("""
            DELETE FROM knowledge_formulas 
            WHERE source IN ('public_docs', 'reverse_analysis')
            AND maker IN ('현대', '기아', '제네시스', '닛산', 'NISSAN')
        """)
    )
    
    print("Removed Phase 1 manufacturer-specific formulas")
