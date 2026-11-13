"""improve powertrain classification

Revision ID: c075a656c25f
Revises: 202f1f3d61e5
Create Date: 2026-11-13 22:40:00.000000

개선된 파워트레인 분류:
- 모델명, 서브모델, file_path를 모두 증거로 활용
- 명시적 BEV 모델 리스트 (Tesla, Bolt-EV, IONIQ 5/6, EV3/6/9, Leaf, Taycan, i3/i4/iX, eC4, C-Zero, i-MiEV, Smart #1, Atto 3, ID.3/4, Polestar...)
- PHEV 토큰 (phev, 4xe, plug-in, e-hybrid, 플러그인)
- HEV 토큰 (hybrid, hev, 하이브리드)
- ECU/장비 벤더는 'not_vehicle'로 분류 (_ECU_장비_프로토콜, _공통_프로토콜)
- 애매한 케이스는 unknown 유지 (추측 금지)

Allowed powertrain values: BEV, PHEV, HEV, ICE, not_vehicle, unknown
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c075a656c25f'
down_revision = '202f1f3d61e5'
branch_labels = None
depends_on = None


def upgrade():
    # Re-classify powertrain using model, submodel, AND file_path as evidence
    op.execute(r"""
        UPDATE vehicle_definitions vd
        SET powertrain = CASE
            -- Equipment vendors and generic protocols = not_vehicle
            WHEN EXISTS (
                SELECT 1 FROM definition_sources ds
                WHERE ds.id = vd.source_id
                AND (ds.file_path ~* '_ECU_장비_프로토콜/'
                     OR ds.file_path ~* '_공통_프로토콜/'
                     OR ds.file_path ~* '/OBD2/'
                     OR vd.maker ~* '^(BOSCH|DELPHI|MARELLI|AIM|STACK|LIFE)$')
            ) THEN 'not_vehicle'
            
            -- Pure BEV: explicit model names and file path evidence
            -- Tesla models
            WHEN vd.model ~* '(Model.*[3SXY]|Tesla|Roadster)' 
                 OR EXISTS (
                     SELECT 1 FROM definition_sources ds
                     WHERE ds.id = vd.source_id 
                     AND ds.file_path ~* 'Tesla/'
                 ) THEN 'BEV'
            
            -- Hyundai/Kia BEV models
            WHEN vd.model ~* '(IONIQ.*[56]|IONIQ 5|IONIQ 6|EV3|EV6|EV9|Ray EV|Niro EV|Kona.*[Ee]lectric|GV60|GV70.*[Ee]lectrified|Casper.*[Ee]lectric)'
                 OR vd.submodel ~* '(IONIQ.*[56]|EV[3679]|Ray EV|Niro EV)'
                 OR EXISTS (
                     SELECT 1 FROM definition_sources ds
                     WHERE ds.id = vd.source_id 
                     AND ds.file_path ~* '(IONIQ.*5|IONIQ.*6|EV[3679]|Ray.*EV|Niro.*EV|Kona.*Electric|GV60)'
                 ) THEN 'BEV'
            
            -- Chevrolet Bolt
            WHEN vd.model ~* 'Bolt(-| )?EV'
                 OR EXISTS (
                     SELECT 1 FROM definition_sources ds
                     WHERE ds.id = vd.source_id 
                     AND ds.file_path ~* 'Bolt(-| )?EV'
                 ) THEN 'BEV'
            
            -- Nissan Leaf
            WHEN vd.model ~* '^Leaf$'
                 OR EXISTS (
                     SELECT 1 FROM definition_sources ds
                     WHERE ds.id = vd.source_id 
                     AND ds.file_path ~* '/Leaf/'
                 ) THEN 'BEV'
            
            -- Audi e-tron
            WHEN vd.model ~* 'e-tron'
                 OR EXISTS (
                     SELECT 1 FROM definition_sources ds
                     WHERE ds.id = vd.source_id 
                     AND ds.file_path ~* 'e-tron'
                 ) THEN 'BEV'
            
            -- Porsche Taycan
            WHEN vd.model ~* 'Taycan'
                 OR EXISTS (
                     SELECT 1 FROM definition_sources ds
                     WHERE ds.id = vd.source_id 
                     AND ds.file_path ~* 'Taycan'
                 ) THEN 'BEV'
            
            -- BMW i-series
            WHEN vd.model ~* '^i[34X]$'
                 OR vd.model ~* '^iX[13]?$'
                 OR EXISTS (
                     SELECT 1 FROM definition_sources ds
                     WHERE ds.id = vd.source_id 
                     AND ds.file_path ~* '/(i[34X]|iX)/'
                 ) THEN 'BEV'
            
            -- Citroën eC4, C-Zero
            WHEN vd.model ~* '(eC4|C-Zero)'
                 OR EXISTS (
                     SELECT 1 FROM definition_sources ds
                     WHERE ds.id = vd.source_id 
                     AND ds.file_path ~* '(eC4|C-Zero)'
                 ) THEN 'BEV'
            
            -- Mitsubishi i-MiEV
            WHEN vd.model ~* 'i-?MiEV'
                 OR EXISTS (
                     SELECT 1 FROM definition_sources ds
                     WHERE ds.id = vd.source_id 
                     AND ds.file_path ~* 'i-?MiEV'
                 ) THEN 'BEV'
            
            -- Smart #1
            WHEN vd.model ~* 'Smart.*#1'
                 OR vd.maker ~* 'Smart.*#1'
                 OR EXISTS (
                     SELECT 1 FROM definition_sources ds
                     WHERE ds.id = vd.source_id 
                     AND ds.file_path ~* 'Smart.*#1'
                 ) THEN 'BEV'
            
            -- BYD Atto 3
            WHEN vd.model ~* 'Atto 3'
                 OR EXISTS (
                     SELECT 1 FROM definition_sources ds
                     WHERE ds.id = vd.source_id 
                     AND ds.file_path ~* 'Atto.*3'
                 ) THEN 'BEV'
            
            -- VW ID series
            WHEN vd.model ~* 'ID\.[34567]'
                 OR EXISTS (
                     SELECT 1 FROM definition_sources ds
                     WHERE ds.id = vd.source_id 
                     AND ds.file_path ~* 'ID\.[34567]'
                 ) THEN 'BEV'
            
            -- Polestar
            WHEN vd.maker ~* '^Polestar'
                 OR vd.model ~* '^Polestar'
                 OR EXISTS (
                     SELECT 1 FROM definition_sources ds
                     WHERE ds.id = vd.source_id 
                     AND ds.file_path ~* 'Polestar'
                 ) THEN 'BEV'
            
            -- Generic EV markers in model/file path (but not "EV6" which is already caught)
            WHEN (vd.model ~* '(^EV[^0-9]|Electric$|\sEV$)'
                  OR vd.submodel ~* 'Electric')
                 AND NOT vd.model ~* '(EV6|EV3|EV9)'  -- already covered above
                 OR EXISTS (
                     SELECT 1 FROM definition_sources ds
                     WHERE ds.id = vd.source_id 
                     AND ds.file_path ~* '(-|_| )Electric/'
                 ) THEN 'BEV'
            
            -- PHEV: explicit tokens in model, submodel, or file_path
            WHEN vd.model ~* '(PHEV|4xe|[Pp]lug.*[Ii]n|e-?[Hh]ybrid|플러그인)'
                 OR vd.submodel ~* '(PHEV|4xe|[Pp]lug.*[Ii]n|플러그인)'
                 OR EXISTS (
                     SELECT 1 FROM definition_sources ds
                     WHERE ds.id = vd.source_id 
                     AND ds.file_path ~* '(phev|4xe|plug.*in|e-hybrid)'
                 ) THEN 'PHEV'
            
            -- BYD Tang PHEV from file path
            WHEN EXISTS (
                SELECT 1 FROM definition_sources ds
                WHERE ds.id = vd.source_id 
                AND ds.file_path ~* 'tang.*phev'
            ) THEN 'PHEV'
            
            -- HEV: known hybrid models and hybrid tokens (but not plug-in hybrid, which is PHEV)
            -- Known HEV models
            WHEN vd.model ~* '(Prius|Camry.*Hybrid|Accord.*Hybrid|Ioniq.*Hybrid)'
                 AND NOT vd.model ~* '(PHEV|[Pp]lug|플러그인)'
                 THEN 'HEV'
            -- Generic hybrid patterns
            WHEN (vd.model ~* '([Hh]ybrid|HEV|하이브리드)'
                  OR vd.submodel ~* '([Hh]ybrid|HEV|하이브리드)')
                 AND NOT (vd.model ~* '(PHEV|[Pp]lug|플러그인)'
                          OR vd.submodel ~* '(PHEV|[Pp]lug|플러그인)')
                 OR (EXISTS (
                     SELECT 1 FROM definition_sources ds
                     WHERE ds.id = vd.source_id 
                     AND ds.file_path ~* 'hybrid'
                     AND NOT ds.file_path ~* '(phev|plug)'
                 )) THEN 'HEV'
            
            -- Keep ambiguous cases as unknown (e.g. "Tucson" without clear evidence)
            -- Do NOT infer ICE from brand alone
            ELSE vd.powertrain
        END
        WHERE vd.powertrain = 'unknown' OR vd.powertrain IS NULL
    """)


def downgrade():
    # Revert all classifications back to unknown
    op.execute("""
        UPDATE vehicle_definitions
        SET powertrain = 'unknown'
        WHERE powertrain IN ('not_vehicle')
    """)
    
    # Keep BEV/PHEV/HEV classifications as they might be from other sources
    # Only revert the not_vehicle classification
