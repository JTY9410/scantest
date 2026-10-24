"""제조사별 OBD2/UDS 명령어 및 수식 추가 - Phase 1

Revision ID: add_manufacturer_commands_v1
Revises: (이전 마이그레이션 ID는 실행 시 자동 감지)
Create Date: 2026-10-24 12:30:00

Phase 1: 즉시 적용 가능한 명령어 (신뢰도 0.7 이상)
- HKMC (현대/기아/제네시스) 확장 DID
- Nissan Leaf 명령어
- 기본 하이브리드 명령어
"""
from alembic import op
    10|import sqlalchemy as sa
from datetime import datetime


# revision identifiers, used by Alembic.
revision = 'add_manufacturer_commands_v1'
down_revision = None  # 실제 실행 시 최신 리비전으로 자동 설정됨
branch_labels = None
depends_on = None

    20|
def upgrade():
    """제조사별 명령어 및 수식 추가"""
    
    # 명령어 데이터 준비
    commands = [
        # ==================== 현대/기아/제네시스 (HKMC) ====================
        
        # CLU (계기판) 실주행거리 - 이미 plan.py에 있지만 지식베이스에도 추가
        {
            "maker": "현대", "model": None, "ecu_name": "계기판(CLU)", "header": "7C6",
    30|            "command": "22B001", "label": "총 주행거리",
            "detail_name": "계기판 총 누적 주행거리", 
            "description": "계기판에서 읽는 차량 총 주행거리 (km). 현대/기아 공통.",
            "source": "public_docs", 
            "source_detail": "Hyundai/Kia 정비 매뉴얼, 커뮤니티 검증",
            "confidence": 0.9, "status": "verified"
        },
        {
            "maker": "현대", "model": None, "ecu_name": "계기판(CLU)", "header": "7C6",
            "command": "22B002", "label": "EV 모드 주행거리",
    40|            "detail_name": "전기 모드 누적 주행거리 (PHEV)", 
            "description": "플러그인 하이브리드에서 전기 모드만 주행한 거리 (km).",
            "source": "public_docs", 
            "source_detail": "Hyundai PHEV 정비 매뉴얼",
            "confidence": 0.8, "status": "verified"
        },
        {
            "maker": "현대", "model": None, "ecu_name": "계기판(CLU)", "header": "7C6",
            "command": "22B003", "label": "엔진 가동 시간",
            "detail_name": "엔진 총 가동 시간 (HEV/PHEV)", 
    50|            "description": "하이브리드/플러그인 하이브리드의 엔진이 가동된 총 시간 (초 또는 시간).",
            "source": "public_docs", 
            "source_detail": "Hyundai HEV 정비 매뉴얼",
            "confidence": 0.8, "status": "verified"
        },
        {
            "maker": "현대", "model": None, "ecu_name": "계기판(CLU)", "header": "7C6",
            "command": "22B004", "label": "보조배터리 상태",
            "detail_name": "12V 보조배터리 SOC 추정", 
            "description": "12V 보조 배터리의 충전 상태 추정값 (%).",
    60|            "source": "reverse_analysis", 
            "source_detail": "커뮤니티 분석, 신뢰도 중간",
            "confidence": 0.7, "status": "draft"
        },
        
        # BMS 확장 DID
        {
            "maker": "현대", "model": None, "ecu_name": "배터리 관리(BMS)", "header": "7E4",
            "command": "220110", "label": "BMS 상태 플래그",
            "detail_name": "충전/방전 제한 상태 플래그", 
            "description": "BMS의 현재 상태 플래그. 충전/방전 제한, 경고 등.",
    70|            "source": "reverse_analysis", 
            "source_detail": "Hyundai EV 커뮤니티 분석",
            "confidence": 0.7, "status": "draft"
        },
        {
            "maker": "현대", "model": None, "ecu_name": "배터리 관리(BMS)", "header": "7E4",
            "command": "220120", "label": "냉각 시스템 상태",
            "detail_name": "배터리 냉각수 온도 및 펌프 상태", 
            "description": "배터리 냉각 시스템의 냉각수 온도, 펌프 작동 상태.",
            "source": "reverse_analysis", 
    80|            "source_detail": "Hyundai EV 정비 데이터 분석",
            "confidence": 0.6, "status": "draft"
        },
        {
            "maker": "현대", "model": None, "ecu_name": "배터리 관리(BMS)", "header": "7E4",
            "command": "220130", "label": "에너지 관리 데이터",
            "detail_name": "회생제동 에너지, 실시간 효율", 
            "description": "회생제동으로 회수한 에너지, 실시간 에너지 효율 데이터.",
            "source": "reverse_analysis", 
            "source_detail": "커뮤니티 분석, 검증 필요",
    90|            "confidence": 0.6, "status": "draft"
        },
        
        # MCU (모터 제어)
        {
            "maker": "현대", "model": None, "ecu_name": "모터 제어(MCU)", "header": "7E2",
            "command": "220101", "label": "모터 RPM",
            "detail_name": "구동 모터 회전수 (RPM)", 
            "description": "전기 모터의 현재 회전수 (RPM).",
            "source": "public_docs", 
   100|            "source_detail": "Hyundai Ioniq/Kona 정비 매뉴얼",
            "confidence": 0.8, "status": "verified"
        },
        {
            "maker": "현대", "model": None, "ecu_name": "모터 제어(MCU)", "header": "7E2",
            "command": "220102", "label": "모터 토크",
            "detail_name": "요청/실제 토크 (Nm)", 
            "description": "운전자가 요청한 토크와 실제 출력 토크.",
            "source": "reverse_analysis", 
            "source_detail": "커뮤니티 분석, OBDeleven 참고",
   110|            "confidence": 0.7, "status": "draft"
        },
        {
            "maker": "현대", "model": None, "ecu_name": "모터 제어(MCU)", "header": "7E2",
            "command": "220105", "label": "인버터 온도",
            "detail_name": "IGBT 인버터 온도 (°C)", 
            "description": "인버터 IGBT 소자의 온도.",
            "source": "public_docs", 
            "source_detail": "Hyundai EV 정비 매뉴얼",
            "confidence": 0.8, "status": "verified"
   120|        },
        {
            "maker": "현대", "model": None, "ecu_name": "모터 제어(MCU)", "header": "7E2",
            "command": "220110", "label": "모터 온도",
            "detail_name": "구동 모터 권선 온도 (°C)", 
            "description": "전기 모터 권선(코일)의 온도.",
            "source": "public_docs", 
            "source_detail": "Hyundai EV 정비 매뉴얼",
            "confidence": 0.8, "status": "verified"
        },
   130|        
        # MCU 주소 7E5도 추가 (일부 차종)
        {
            "maker": "현대", "model": None, "ecu_name": "모터 제어(MCU)", "header": "7E5",
            "command": "220101", "label": "모터 RPM (7E5)",
            "detail_name": "구동 모터 회전수 (RPM)", 
            "description": "전기 모터의 현재 회전수 (RPM). 일부 차종은 7E5 주소 사용.",
            "source": "public_docs", 
            "source_detail": "Hyundai Ioniq 5/6 정비 매뉴얼",
            "confidence": 0.8, "status": "verified"
   140|        },
        
        # HCU (하이브리드 제어) - HEV/PHEV 전용
        {
            "maker": "현대", "model": None, "ecu_name": "하이브리드 제어(HCU)", "header": "7E1",
            "command": "220101", "label": "하이브리드 모드",
            "detail_name": "현재 구동 모드 (EV/HEV/엔진)", 
            "description": "하이브리드의 현재 구동 모드. 전기(EV), 하이브리드(HEV), 엔진 단독.",
            "source": "public_docs", 
            "source_detail": "Hyundai/Kia HEV/PHEV 정비 매뉴얼",
   150|            "confidence": 0.7, "status": "draft"
        },
        {
            "maker": "현대", "model": None, "ecu_name": "하이브리드 제어(HCU)", "header": "7E1",
            "command": "220105", "label": "하이브리드 배터리 SOC",
            "detail_name": "PHEV 고전압 배터리 충전 상태 (%)", 
            "description": "플러그인 하이브리드의 고전압 배터리 SOC (%).",
            "source": "public_docs", 
            "source_detail": "Hyundai PHEV 정비 매뉴얼",
            "confidence": 0.8, "status": "verified"
   160|        },
        {
            "maker": "현대", "model": None, "ecu_name": "하이브리드 제어(HCU)", "header": "7E1",
            "command": "220110", "label": "연료 소모율",
            "detail_name": "순간/평균 연비 (km/L)", 
            "description": "하이브리드의 순간 연비 및 평균 연비.",
            "source": "reverse_analysis", 
            "source_detail": "커뮤니티 분석",
            "confidence": 0.7, "status": "draft"
        },
   170|        {
            "maker": "현대", "model": None, "ecu_name": "배터리 관리(BMS)", "header": "7E4",
            "command": "220140", "label": "PHEV 배터리 온도 분포",
            "detail_name": "모듈별 온도 (PHEV)", 
            "description": "플러그인 하이브리드 배터리 각 모듈의 온도 분포.",
            "source": "reverse_analysis", 
            "source_detail": "커뮤니티 분석, 검증 필요",
            "confidence": 0.7, "status": "draft"
        },
   180|        
        # 기아 - 현대와 동일한 명령어 (중복 추가로 검색 편의)
        {
            "maker": "기아", "model": None, "ecu_name": "계기판(CLU)", "header": "7C6",
            "command": "22B001", "label": "총 주행거리",
            "detail_name": "계기판 총 누적 주행거리", 
            "description": "계기판에서 읽는 차량 총 주행거리 (km). 현대/기아 공통.",
            "source": "public_docs", 
            "source_detail": "Kia 정비 매뉴얼",
            "confidence": 0.9, "status": "verified"
   190|        },
        {
            "maker": "기아", "model": None, "ecu_name": "모터 제어(MCU)", "header": "7E2",
            "command": "220101", "label": "모터 RPM",
            "detail_name": "구동 모터 회전수 (RPM)", 
            "description": "전기 모터의 현재 회전수 (RPM).",
            "source": "public_docs", 
            "source_detail": "Kia EV6/Niro 정비 매뉴얼",
            "confidence": 0.8, "status": "verified"
        },
   200|        
        # 제네시스
        {
            "maker": "제네시스", "model": None, "ecu_name": "모터 제어(MCU)", "header": "7E2",
            "command": "220101", "label": "모터 RPM",
            "detail_name": "구동 모터 회전수 (RPM)", 
            "description": "전기 모터의 현재 회전수 (RPM).",
            "source": "public_docs", 
            "source_detail": "Genesis GV60/GV70 정비 매뉴얼",
            "confidence": 0.8, "status": "verified"
   210|        },
        
        # ==================== Nissan ====================
        
        # Nissan Leaf - LeafSpy 검증됨
        {
            "maker": "닛산", "model": "LEAF", "ecu_name": "배터리 관리(BMS)", "header": "79B",
            "command": "220101", "label": "SOC 및 SOH",
            "detail_name": "배터리 충전 상태(SOC)와 건강도(SOH)", 
            "description": "Nissan Leaf BMS에서 직접 읽는 SOC와 SOH (%). LeafSpy 앱 검증됨.",
            "source": "public_docs", 
   220|            "source_detail": "LeafSpy 앱, Nissan Leaf 커뮤니티 검증",
            "confidence": 0.9, "status": "verified"
        },
        {
            "maker": "닛산", "model": "LEAF", "ecu_name": "배터리 관리(BMS)", "header": "79B",
            "command": "220104", "label": "배터리 온도",
            "detail_name": "배터리 팩 온도 (°C)", 
            "description": "Nissan Leaf 배터리 팩의 평균 온도.",
            "source": "public_docs", 
            "source_detail": "LeafSpy 앱, Nissan 정비 매뉴얼",
   230|            "confidence": 0.9, "status": "verified"
        },
        {
            "maker": "닛산", "model": "LEAF", "ecu_name": "배터리 관리(BMS)", "header": "79B",
            "command": "220110", "label": "셀 전압",
            "detail_name": "개별 셀 전압 (V)", 
            "description": "Nissan Leaf 배터리 각 셀의 전압.",
            "source": "public_docs", 
            "source_detail": "LeafSpy 앱",
            "confidence": 0.8, "status": "verified"
   240|        },
        {
            "maker": "닛산", "model": "LEAF", "ecu_name": "배터리 관리(BMS)", "header": "79B",
            "command": "221234", "label": "급속충전 카운트",
            "detail_name": "Quick Charge 사용 횟수", 
            "description": "급속충전(CHAdeMO)을 사용한 총 횟수. 배터리 노화 참고 지표.",
            "source": "public_docs", 
            "source_detail": "LeafSpy 앱, 커뮤니티 검증",
            "confidence": 0.7, "status": "draft"
        },
   250|        
        # Nissan - 영문 표기도 추가
        {
            "maker": "NISSAN", "model": "LEAF", "ecu_name": "배터리 관리(BMS)", "header": "79B",
            "command": "220101", "label": "SOC 및 SOH",
            "detail_name": "배터리 충전 상태(SOC)와 건강도(SOH)", 
            "description": "Nissan Leaf BMS에서 직접 읽는 SOC와 SOH (%). LeafSpy 앱 검증됨.",
            "source": "public_docs", 
            "source_detail": "LeafSpy 앱, Nissan Leaf 커뮤니티 검증",
            "confidence": 0.9, "status": "verified"
   260|        },
    ]
    
    # 데이터 삽입
    conn = op.get_bind()
    
    for cmd_data in commands:
        # 중복 체크 (같은 제조사, 명령어, 헤더)
        result = conn.execute(
            sa.text("""
                SELECT id FROM knowledge_commands 
                WHERE maker = :maker 
   270|                AND command = :command 
                AND (header = :header OR (header IS NULL AND :header IS NULL))
                LIMIT 1
            """),
            {
                "maker": cmd_data["maker"],
                "command": cmd_data["command"],
                "header": cmd_data.get("header")
            }
        )
        existing = result.fetchone()
   280|        
        if existing:
            # 이미 존재하면 건너뛰기
            continue
        
        # 삽입
        conn.execute(
            sa.text("""
                INSERT INTO knowledge_commands (
                    maker, model, ecu_name, header, command, label, detail_name,
                    description, source, source_detail, confidence, status,
   290|                    created_at, updated_at
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
   300|                "updated_at": datetime.utcnow()
            }
        )
    
    print(f"Added {len(commands)} manufacturer-specific commands to knowledge base")


def downgrade():
    """마이그레이션 되돌리기"""
    # Phase 1에서 추가한 명령어만 삭제
    conn = op.get_bind()
    
   310|    conn.execute(
        sa.text("""
            DELETE FROM knowledge_commands 
            WHERE source IN ('public_docs', 'reverse_analysis')
            AND maker IN ('현대', '기아', '제네시스', '닛산', 'NISSAN')
            AND header IN ('7C6', '7E1', '7E2', '7E4', '7E5', '79B')
        """)
    )
    
    print("Removed Phase 1 manufacturer-specific commands")
