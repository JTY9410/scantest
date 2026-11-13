"""add battery soh learning infrastructure

Revision ID: b475e62c9183
Revises: e24341200b29
Create Date: 2026-11-13 12:00:00.000000

배터리 사양, SOH 결과 추적, 학습 공식 테이블 추가
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'b475e62c9183'
down_revision = 'e24341200b29'
branch_labels = None
depends_on = None


def upgrade():
    # 1. battery_specs 테이블 생성
    op.create_table('battery_specs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('maker', sa.String(length=50), nullable=False),
        sa.Column('model', sa.String(length=200), nullable=False),
        sa.Column('trim_grade', sa.String(length=100), nullable=True),
        sa.Column('model_year', sa.Integer(), nullable=True),
        sa.Column('generation', sa.String(length=50), nullable=True),
        sa.Column('market', sa.String(length=50), nullable=True),
        sa.Column('gross_kwh', sa.Float(), nullable=True),
        sa.Column('usable_kwh', sa.Float(), nullable=True),
        sa.Column('nominal_voltage_v', sa.Float(), nullable=True),
        sa.Column('capacity_ah', sa.Float(), nullable=True),
        sa.Column('cell_chemistry', sa.String(length=20), nullable=True),
        sa.Column('cell_count', sa.Integer(), nullable=True),
        sa.Column('cell_config', sa.String(length=50), nullable=True),
        sa.Column('source_url', sa.Text(), nullable=False),
        sa.Column('source_note', sa.Text(), nullable=True),
        sa.Column('verified_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_battery_specs_maker_model', 'battery_specs', ['maker', 'model'])
    op.create_index('ix_battery_specs_year', 'battery_specs', ['model_year'])
    
    # 2. soh_results 테이블 생성
    op.create_table('soh_results',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('scan_id', sa.Integer(), nullable=False),
        sa.Column('soh_pct', sa.Float(), nullable=False),
        sa.Column('method', sa.String(length=50), nullable=False),
        sa.Column('confidence', sa.Float(), nullable=False),
        sa.Column('input_features', sa.JSON(), nullable=False),
        sa.Column('battery_spec_id', sa.Integer(), nullable=True),
        sa.Column('bms_soh_pct', sa.Float(), nullable=True),
        sa.Column('formula_version_id', sa.Integer(), nullable=True),
        sa.Column('error_pct', sa.Float(), nullable=True),
        sa.Column('calculation_details', sa.JSON(), nullable=True),
        sa.Column('computed_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['scan_id'], ['scans.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['battery_spec_id'], ['battery_specs.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_soh_results_scan', 'soh_results', ['scan_id'])
    op.create_index('ix_soh_results_method', 'soh_results', ['method'])
    op.create_index('ix_soh_results_bms_soh', 'soh_results', ['bms_soh_pct'])
    
    # 3. learned_formulas 테이블 생성
    op.create_table('learned_formulas',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('method', sa.String(length=50), nullable=False),
        sa.Column('version', sa.String(length=20), nullable=False),
        sa.Column('maker', sa.String(length=50), nullable=True),
        sa.Column('platform', sa.String(length=50), nullable=True),
        sa.Column('coefficients', sa.JSON(), nullable=False),
        sa.Column('sample_count', sa.Integer(), nullable=False),
        sa.Column('mae', sa.Float(), nullable=False),
        sa.Column('rmse', sa.Float(), nullable=True),
        sa.Column('r_squared', sa.Float(), nullable=True),
        sa.Column('validation_mae', sa.Float(), nullable=True),
        sa.Column('validation_sample_count', sa.Integer(), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('trained_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_learned_formulas_method_version', 'learned_formulas', ['method', 'version'])
    op.create_index('ix_learned_formulas_maker', 'learned_formulas', ['maker'])
    op.create_index('ix_learned_formulas_active', 'learned_formulas', ['is_active'])
    
    # 4. soh_results와 learned_formulas 간 FK 추가 (순환 참조 방지를 위해 뒤에 추가)
    op.create_foreign_key(
        'fk_soh_results_formula_version',
        'soh_results', 'learned_formulas',
        ['formula_version_id'], ['id'],
        ondelete='SET NULL'
    )
    
    # 5. 기존 테이블에 분류 컬럼 추가 (향후 확장용)
    # definition_sources: 이미 source_type이 있음
    # vehicle_definitions: 이미 maker, model, powertrain이 있음
    # diagnostic_commands: 이미 maker, model, ecu_address가 있음
    # 추가 분류 컬럼이 필요하면 여기 추가


def downgrade():
    # FK 삭제
    op.drop_constraint('fk_soh_results_formula_version', 'soh_results', type_='foreignkey')
    
    # learned_formulas 삭제
    op.drop_index('ix_learned_formulas_active', table_name='learned_formulas')
    op.drop_index('ix_learned_formulas_maker', table_name='learned_formulas')
    op.drop_index('ix_learned_formulas_method_version', table_name='learned_formulas')
    op.drop_table('learned_formulas')
    
    # soh_results 삭제
    op.drop_index('ix_soh_results_bms_soh', table_name='soh_results')
    op.drop_index('ix_soh_results_method', table_name='soh_results')
    op.drop_index('ix_soh_results_scan', table_name='soh_results')
    op.drop_table('soh_results')
    
    # battery_specs 삭제
    op.drop_index('ix_battery_specs_year', table_name='battery_specs')
    op.drop_index('ix_battery_specs_maker_model', table_name='battery_specs')
    op.drop_table('battery_specs')
