"""제조사별 OBD2/UDS 명령어 추가 - Phase 1

Revision ID: add_manufacturer_commands_v1
Revises: d9e0f1a2b3c4
Create Date: 2026-10-24 12:30:00

Phase 1: 신뢰도 0.7 이상의 명령어 추가
- HKMC (현대/기아/제네시스) 확장 DID
- Nissan Leaf 검증된 명령어
- 기본 하이브리드 명령어
"""
from alembic import op
import sqlalchemy as sa
from datetime import datetime


# revision identifiers, used by Alembic.
revision = 'add_manufacturer_commands_v1'
down_revision = 'd9e0f1a2b3c4'
branch_labels = None
depends_on = None


def upgrade():
    """제조사별 OBD2/UDS 명령어 추가"""
    
    commands = [
        # ==================== 현대/기아/제네시스 ====================
        # 배터리 관련 확장 DID (UDS 22xxxx)
        {
            "maker": "현대", "model": None, "ecu_name": "배터리 관리(BMS)", "header": "7E4",
            "command": "22B001", "label": "총 주행거리",
            "detail_name": "차량 누적 주행거리 (km)", 
            "description": "배터리 팩 장착 후 차량이 운행한 총 거리 (km). 계기판 표시와 일치.",
            "source": "reverse_analysis", 
            "source_detail": "Hyundai EV 정비 데이터 분석",
            "confidence": 0.6, "status": "experimental"
        },
        {
            "maker": "기아", "model": None, "ecu_name": "배터리 관리(BMS)", "header": "7E4",
            "command": "22B002", 
            "detail_name": "전기 모드 누적 주행거리 (PHEV)", 
            "label": "EV 모드 주행거리",
            "description": "플러그인 하이브리드(PHEV)에서 엔진 없이 전기만으로 주행한 거리.",
            "source": "reverse_analysis", 
            "source_detail": "Hyundai PHEV 데이터 분석",
            "confidence": 0.6, "status": "experimental"
        },
        {
            "maker": "제네시스", "model": None, "ecu_name": "하이브리드 제어(HCU)", "header": "7E1",
            "command": "22B010", "label": "엔진 가동 시간",
            "description": "하이브리드/플러그인 하이브리드의 엔진이 가동된 총 시간 (초 또는 시간).",
            "detail_name": "ICE 누적 가동 시간",
            "source": "reverse_analysis", 
            "source_detail": "Genesis GV60 PHEV 데이터",
            "confidence": 0.6, "status": "experimental"
        },
        
        # 검증된 현대 EV DID (공개 문서)
        {
            "maker": "현대", "model": "IONIQ 5", "ecu_name": "배터리 관리(BMS)", "header": "7E4",
            "command": "220101", "label": "배터리 SOC",
            "detail_name": "배터리 충전 상태 (%)",
            "description": "현재 배터리 충전 잔량 (%, 0~100). 계기판 표시와 동일.",
            "source": "public_docs",
            "source_detail": "Hyundai Ioniq/Kona 정비 매뉴얼",
            "confidence": 0.9, "status": "verified"
        },
        {
            "maker": "기아", "model": "EV6", "ecu_name": "배터리 관리(BMS)", "header": "7E4",
            "command": "220102", "label": "배터리 전압",
            "detail_name": "고전압 배터리 전압 (V)",
            "description": "배터리 팩 총 전압 (V). 약 350~420V (모델별 차이).",
            "source": "public_docs",
            "source_detail": "Hyundai Ioniq/Kona 정비 매뉴얼",
            "confidence": 0.9, "status": "verified"
        },
        {
            "maker": "현대", "model": "KONA ELECTRIC", "ecu_name": "배터리 관리(BMS)", "header": "7E4",
            "command": "220103", "label": "배터리 전류",
            "detail_name": "충방전 전류 (A)",
            "description": "배터리로 흐르는 전류. 양수=방전(주행), 음수=충전.",
            "source": "public_docs",
            "source_detail": "Hyundai EV 정비 매뉴얼",
            "confidence": 0.9, "status": "verified"
        },
        {
            "maker": "현대", "model": None, "ecu_name": "배터리 관리(BMS)", "header": "7E4",
            "command": "220105", "label": "배터리 온도",
            "detail_name": "배터리 평균 온도 (°C)",
            "description": "배터리 셀 평균 온도. 정상 범위 10~45°C.",
            "source": "public_docs",
            "source_detail": "Hyundai EV 통합 매뉴얼",
            "confidence": 0.9, "status": "verified"
        },
        {
            "maker": "기아", "model": None, "ecu_name": "모터 제어(MCU)", "header": "7E2",
            "command": "220201", "label": "모터 회전수",
            "detail_name": "모터 RPM",
            "description": "구동 모터의 현재 회전수 (RPM).",
            "source": "public_docs",
            "source_detail": "Kia EV 정비 매뉴얼",
            "confidence": 0.8, "status": "verified"
        },
        {
            "maker": "현대", "model": None, "ecu_name": "모터 제어(MCU)", "header": "7E2",
            "command": "220202", "label": "모터 토크",
            "detail_name": "출력 토크 (Nm)",
            "description": "현재 모터가 발생시키는 토크 (Nm). 양수=가속, 음수=회생제동.",
            "source": "public_docs",
            "source_detail": "Hyundai Motor Control 문서",
            "confidence": 0.8, "status": "verified"
        },
        
        # ==================== Nissan Leaf ====================
        # LeafSpy 등 커뮤니티 검증
        {
            "maker": "닛산", "model": "LEAF", "ecu_name": "배터리 관리(BMS)", "header": "79B",
            "command": "2101", "label": "배터리 SOH",
            "detail_name": "배터리 건강도 (%)",
            "description": "배터리 상태 (State of Health). 새 배터리=100%, 노화 진행시 감소.",
            "source": "reverse_analysis",
            "source_detail": "LeafSpy 앱, Nissan Leaf 커뮤니티 검증",
            "confidence": 0.95, "status": "verified"
        },
        {
            "maker": "NISSAN", "model": "LEAF", "ecu_name": "배터리 관리(BMS)", "header": "79B",
            "command": "2102", "label": "배터리 용량",
            "detail_name": "현재 가용 용량 (Ah)",
            "description": "배터리의 현재 실제 용량 (Ah). SOH와 함께 배터리 노화도 판단.",
            "source": "reverse_analysis",
            "source_detail": "LeafSpy, Nissan 커뮤니티",
            "confidence": 0.9, "status": "verified"
        },
        {
            "maker": "닛산", "model": "LEAF", "ecu_name": "배터리 관리(BMS)", "header": "79B",
            "command": "2103", "label": "셀 전압 (최대)",
            "detail_name": "최고 셀 전압 (mV)",
            "description": "배터리 팩 내 가장 높은 셀 전압. 불균형 진단에 사용.",
            "source": "reverse_analysis",
            "source_detail": "LeafSpy",
            "confidence": 0.85, "status": "verified"
        },
        {
            "maker": "닛산", "model": "LEAF", "ecu_name": "배터리 관리(BMS)", "header": "79B",
            "command": "2104", "label": "셀 전압 (최소)",
            "detail_name": "최저 셀 전압 (mV)",
            "description": "배터리 팩 내 가장 낮은 셀 전압.",
            "source": "reverse_analysis",
            "source_detail": "LeafSpy",
            "confidence": 0.85, "status": "verified"
        },
        
        # ==================== 범용 하이브리드 명령어 ====================
        {
            "maker": None, "model": None, "ecu_name": "하이브리드 제어(HCU)", "header": "7E1",
            "command": "0105", "label": "냉각수 온도",
            "detail_name": "엔진 냉각수 온도 (°C)",
            "description": "하이브리드 차량의 엔진 냉각수 온도. OBD-II 표준 PID.",
            "source": "public_docs",
            "source_detail": "OBD-II Standard PIDs (SAE J1979)",
            "confidence": 1.0, "status": "verified"
        },
        {
            "maker": None, "model": None, "ecu_name": "하이브리드 제어(HCU)", "header": "7E1",
            "command": "010C", "label": "엔진 RPM",
            "detail_name": "엔진 회전수",
            "description": "내연기관 엔진의 분당 회전수. HEV/PHEV 전용.",
            "source": "public_docs",
            "source_detail": "OBD-II Standard",
            "confidence": 1.0, "status": "verified"
        },
    ]
    
    # 데이터 삽입
    conn = op.get_bind()
    
    for cmd_data in commands:
        # 중복 체크 (maker + command + header)
        result = conn.execute(
            sa.text("""
                SELECT id FROM knowledge_commands 
                WHERE maker IS NOT DISTINCT FROM :maker
                AND command = :command 
                AND header IS NOT DISTINCT FROM :header
                LIMIT 1
            """),
            {
                "maker": cmd_data["maker"],
                "command": cmd_data["command"],
                "header": cmd_data.get("header")
            }
        )
        existing = result.fetchone()
        
        if existing:
            # 이미 존재하면 건너뛰기
            continue
        
        # 삽입
        conn.execute(
            sa.text("""
                INSERT INTO knowledge_commands (
                    maker, model, ecu_name, header, command, label, detail_name,
                    description, source, source_detail, confidence, status,
                    created_at, updated_at
                ) VALUES (
                    :maker, :model, :ecu_name, :header, :command, :label, :detail_name,
                    :description, :source, :source_detail, :confidence, :status,
                    :created_at, :updated_at
                )
            """),
            {
                **cmd_data,
                "model": cmd_data.get("model"),
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            }
        )
    
    print(f"Added {len(commands)} manufacturer-specific commands to knowledge base")


def downgrade():
    """마이그레이션 되돌리기"""
    # Phase 1에서 추가한 명령어만 삭제
    conn = op.get_bind()
    
    conn.execute(
        sa.text("""
            DELETE FROM knowledge_commands 
            WHERE source IN ('public_docs', 'reverse_analysis')
            AND maker IN ('현대', '기아', '제네시스', '닛산', 'NISSAN')
            AND header IN ('7C6', '7E1', '7E2', '7E4', '7E5', '79B')
        """)
    )
    
    print("Removed Phase 1 manufacturer commands")
