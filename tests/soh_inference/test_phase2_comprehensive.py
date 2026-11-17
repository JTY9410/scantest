"""Comprehensive tests for Phase 2 (v2.2.23): SOH Inference."""

import pytest
from datetime import datetime

from app.extensions import db
from app.modules.soh_inference.models import (
    SOHInferenceModel, SOHInference, InferenceModelAudit, InferenceModelStatus
)
from app.modules.soh_inference.engine import SOHInferenceEngine
from app.modules.scans.models import Scan
from app.modules.scans.battery_capacity import BatteryReferenceCapacity


class TestInferenceEngine:
    """Test SOH inference engine."""
    
    def test_feature_extraction(self, app, make_user):
        """Test feature extraction from scan data."""
        user_id = make_user('admin', type='admin')
        
        # Create battery reference for nominal capacity
        with app.app_context():
            ref = BatteryReferenceCapacity(
                maker='현대',
                model='아이오닉5',
                gross_capacity_kwh=72.6,
                verification_level='official'
            )
            db.session.add(ref)
            db.session.commit()
            
            scan_data = {
                'battery': {
                    'current_capacity_kwh': 65.5,
                    'soc': 80.0,
                    'pack_voltage': 700.0,
                    'max_cell_v': 4.15,
                    'min_cell_v': 4.10,
                    'max_temp': 25,
                    'min_temp': 22,
                    'lifetime_charge_kwh': 50000,
                    'lifetime_discharge_kwh': 48000
                },
                'vehicle': {
                    'maker': '현대',
                    'model': '아이오닉5',
                    'year': 2022,
                    'odometer_km': 50000
                }
            }
            
            features = SOHInferenceEngine._extract_features(
                scan_data['battery'],
                scan_data['vehicle'],
                scan_data
            )
            
            assert features is not None
            assert 'capacity_ratio' in features
            assert abs(features['capacity_ratio'] - (65.5 / 72.6)) < 0.01
            assert features['soc'] == 80.0
            assert features['max_cell_v'] == 4.15
            assert features['min_cell_v'] == 4.10
            assert abs(features['cell_voltage_deviation'] - 0.05) < 0.001
            assert features['max_temp'] == 25
            assert features['temp_deviation'] == 3
            assert features['lifetime_charge_kwh'] == 50000
            assert features['lifetime_throughput_kwh'] == 98000
            assert 'throughput_cycles' in features
            assert features['odometer_km'] == 50000
            assert 'vehicle_age_years' in features
    
    def test_scope_resolution_model_specific(self, app, make_user):
        """Test scope resolution: model-specific model preferred."""
        user_id = make_user('admin', type='admin')
        
        with app.app_context():
            # Create model-specific model
            model_specific = SOHInferenceModel(
                version='v1.0-ioniq5',
                status=InferenceModelStatus.APPROVED.value,
                scope_maker='현대',
                scope_model='아이오닉5',
                model_type='linear',
                model_config={'intercept': 100.0},
                model_weights={'intercept': 100.0, 'coefficients': {}},
                feature_names=['capacity_ratio'],
                approved_at=datetime.utcnow()
            )
            
            # Create manufacturer-level model (should be ignored when model-specific exists)
            manufacturer = SOHInferenceModel(
                version='v1.0-hyundai',
                status=InferenceModelStatus.APPROVED.value,
                scope_maker='현대',
                scope_model=None,
                model_type='linear',
                model_config={'intercept': 95.0},
                model_weights={'intercept': 95.0, 'coefficients': {}},
                feature_names=['capacity_ratio'],
                approved_at=datetime.utcnow()
            )
            
            db.session.add_all([model_specific, manufacturer])
            db.session.commit()
            
            model, chain = SOHInferenceEngine._find_best_model('현대', '아이오닉5')
            
            assert model is not None
            assert model.version == 'v1.0-ioniq5'
            assert chain == ['model_specific']
    
    def test_scope_resolution_manufacturer_fallback(self, app, make_user):
        """Test scope resolution: manufacturer fallback when no model-specific."""
        user_id = make_user('admin', type='admin')
        
        with app.app_context():
            # Only manufacturer-level model
            manufacturer = SOHInferenceModel(
                version='v1.0-hyundai',
                status=InferenceModelStatus.APPROVED.value,
                scope_maker='현대',
                scope_model=None,
                model_type='linear',
                model_config={'intercept': 95.0},
                model_weights={'intercept': 95.0, 'coefficients': {}},
                feature_names=['capacity_ratio'],
                approved_at=datetime.utcnow()
            )
            
            db.session.add(manufacturer)
            db.session.commit()
            
            model, chain = SOHInferenceEngine._find_best_model('현대', '아이오닉6')
            
            assert model is not None
            assert model.version == 'v1.0-hyundai'
            assert chain == ['manufacturer']
    
    def test_scope_resolution_global_fallback(self, app, make_user):
        """Test scope resolution: global fallback (미산정)."""
        user_id = make_user('admin', type='admin')
        
        with app.app_context():
            # Only global model
            global_model = SOHInferenceModel(
                version='v1.0-global',
                status=InferenceModelStatus.APPROVED.value,
                scope_maker=None,
                scope_model=None,
                model_type='linear',
                model_config={'intercept': 90.0},
                model_weights={'intercept': 90.0, 'coefficients': {}},
                feature_names=['capacity_ratio'],
                approved_at=datetime.utcnow()
            )
            
            db.session.add(global_model)
            db.session.commit()
            
            model, chain = SOHInferenceEngine._find_best_model('테슬라', 'Model 3')
            
            assert model is not None
            assert model.version == 'v1.0-global'
            assert chain == ['미산정']
    
    def test_linear_inference(self, app, make_user):
        """Test linear model inference."""
        user_id = make_user('admin', type='admin')
        
        with app.app_context():
            ref = BatteryReferenceCapacity(
                maker='현대',
                model='아이오닉5',
                gross_capacity_kwh=72.6,
                verification_level='official'
            )
            db.session.add(ref)
            
            model = SOHInferenceModel(
                version='v1.0-linear',
                status=InferenceModelStatus.APPROVED.value,
                scope_maker=None,
                scope_model=None,
                model_type='linear',
                model_config={'features': ['capacity_ratio']},
                model_weights={
                    'intercept': 10.0,
                    'coefficients': {'capacity_ratio': 90.0}
                },
                feature_names=['capacity_ratio'],
                approved_at=datetime.utcnow()
            )
            db.session.add(model)
            db.session.commit()
            
            scan_data = {
                'battery': {'current_capacity_kwh': 65.5},
                'vehicle': {'maker': '현대', 'model': '아이오닉5', 'year': 2022}
            }
            
            result = SOHInferenceEngine.infer_soh(scan_data, save=False)
            
            assert result is not None
            # SOH = 10 + 90 * (65.5/72.6) = 10 + 90 * 0.902 = 10 + 81.18 = 91.18
            assert 90.0 < result.estimated_soh < 92.0
            assert result.method == 'linear_model'
            assert result.confidence > 0.0
            assert 'capacity_ratio' in result.input_features
    
    def test_polynomial_inference(self, app, make_user):
        """Test polynomial model inference."""
        user_id = make_user('admin', type='admin')
        
        with app.app_context():
            ref = BatteryReferenceCapacity(
                maker='현대',
                model='코나EV',
                gross_capacity_kwh=64.0,
                verification_level='official'
            )
            db.session.add(ref)
            
            model = SOHInferenceModel(
                version='v1.0-poly',
                status=InferenceModelStatus.APPROVED.value,
                scope_maker='현대',
                scope_model='코나EV',
                model_type='polynomial',
                model_config={'degree': 2},
                model_weights={'a': 5.0, 'b': 80.0, 'c': 10.0},
                feature_names=['capacity_ratio'],
                approved_at=datetime.utcnow()
            )
            db.session.add(model)
            db.session.commit()
            
            scan_data = {
                'battery': {'current_capacity_kwh': 57.6},
                'vehicle': {'maker': '현대', 'model': '코나EV', 'year': 2021}
            }
            
            result = SOHInferenceEngine.infer_soh(scan_data, maker='현대', model='코나EV', save=False)
            
            assert result is not None
            # capacity_ratio = 57.6 / 64.0 = 0.9
            # SOH = 5 + 80*0.9 + 10*(0.9^2) = 5 + 72 + 8.1 = 85.1
            assert 84.0 < result.estimated_soh < 86.0
            assert result.method == 'polynomial_model'
            assert result.confidence > 0.0


class TestApprovalWorkflow:
    """Test model approval workflow."""
    
    def test_approve_model_creates_audit_log(self, app, admin_client):
        """Test approving a model creates audit log."""
        with app.app_context():
            model = SOHInferenceModel(
                version='v1.0-test',
                status=InferenceModelStatus.PENDING_APPROVAL.value,
                model_type='linear',
                model_config={'intercept': 100.0},
                model_weights={'intercept': 100.0, 'coefficients': {}},
                feature_names=['capacity_ratio']
            )
            db.session.add(model)
            db.session.commit()
            model_id = model.id
        
        # Approve model
        response = admin_client.post(
            f'/admin/soh/inference/models/{model_id}/approve',
            json={'notes': 'Validation passed, approved for production'}
        )
        
        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert data['status'] == InferenceModelStatus.APPROVED.value
        
        # Verify audit log created
        with app.app_context():
            model = db.session.get(SOHInferenceModel, model_id)
            assert model.status == InferenceModelStatus.APPROVED.value
            assert model.approved_at is not None
            assert model.approval_notes == 'Validation passed, approved for production'
            
            audits = db.session.query(InferenceModelAudit).filter_by(model_id=model_id).all()
            assert len(audits) == 1
            assert audits[0].action == 'approve'
            assert audits[0].previous_status == InferenceModelStatus.PENDING_APPROVAL.value
            assert audits[0].new_status == InferenceModelStatus.APPROVED.value
            assert audits[0].reason == 'Validation passed, approved for production'
    
    def test_approve_requires_notes(self, app, admin_client):
        """Test approval requires notes."""
        with app.app_context():
            model = SOHInferenceModel(
                version='v1.0-test',
                status=InferenceModelStatus.PENDING_APPROVAL.value,
                model_type='linear',
                model_config={},
                feature_names=[]
            )
            db.session.add(model)
            db.session.commit()
            model_id = model.id
        
        # Try to approve without notes
        response = admin_client.post(
            f'/admin/soh/inference/models/{model_id}/approve',
            json={}
        )
        
        assert response.status_code == 400
        assert 'notes required' in response.get_json()['error'].lower()
    
    def test_reject_model_deletes_with_audit(self, app, admin_client):
        """Test rejecting a model deletes it but keeps audit log."""
        with app.app_context():
            model = SOHInferenceModel(
                version='v1.0-bad',
                status=InferenceModelStatus.DRAFT.value,
                model_type='linear',
                model_config={},
                feature_names=[]
            )
            db.session.add(model)
            db.session.commit()
            model_id = model.id
        
        # Reject model
        response = admin_client.post(
            f'/admin/soh/inference/models/{model_id}/reject',
            json={'reason': 'Validation metrics too poor, retrain required'}
        )
        
        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert data['action'] == 'rejected_and_deleted'
        
        # Verify model deleted
        with app.app_context():
            model = db.session.get(SOHInferenceModel, model_id)
            assert model is None
            
            # But audit log exists
            audits = db.session.query(InferenceModelAudit).filter_by(model_id=model_id).all()
            assert len(audits) == 1
            assert audits[0].action == 'reject'
            assert audits[0].reason == 'Validation metrics too poor, retrain required'
    
    def test_reject_requires_reason(self, app, admin_client):
        """Test rejection requires reason."""
        with app.app_context():
            model = SOHInferenceModel(
                version='v1.0-test',
                status=InferenceModelStatus.DRAFT.value,
                model_type='linear',
                model_config={},
                feature_names=[]
            )
            db.session.add(model)
            db.session.commit()
            model_id = model.id
        
        response = admin_client.post(
            f'/admin/soh/inference/models/{model_id}/reject',
            json={}
        )
        
        assert response.status_code == 400
        assert 'reason required' in response.get_json()['error'].lower()
    
    def test_retire_approved_model(self, app, admin_client):
        """Test retiring an approved model."""
        with app.app_context():
            model = SOHInferenceModel(
                version='v1.0-old',
                status=InferenceModelStatus.APPROVED.value,
                model_type='linear',
                model_config={},
                feature_names=[],
                approved_at=datetime.utcnow()
            )
            db.session.add(model)
            db.session.commit()
            model_id = model.id
        
        response = admin_client.post(
            f'/admin/soh/inference/models/{model_id}/retire',
            json={'reason': 'Newer model v2.0 available with better metrics'}
        )
        
        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert data['status'] == InferenceModelStatus.RETIRED.value
        
        with app.app_context():
            model = db.session.get(SOHInferenceModel, model_id)
            assert model.status == InferenceModelStatus.RETIRED.value
            assert model.retired_at is not None
            assert model.retirement_reason == 'Newer model v2.0 available with better metrics'
            
            audits = db.session.query(InferenceModelAudit).filter_by(model_id=model_id).all()
            assert len(audits) == 1
            assert audits[0].action == 'retire'
    
    def test_retire_requires_reason(self, app, admin_client):
        """Test retirement requires reason."""
        with app.app_context():
            model = SOHInferenceModel(
                version='v1.0-test',
                status=InferenceModelStatus.APPROVED.value,
                model_type='linear',
                model_config={},
                feature_names=[],
                approved_at=datetime.utcnow()
            )
            db.session.add(model)
            db.session.commit()
            model_id = model.id
        
        response = admin_client.post(
            f'/admin/soh/inference/models/{model_id}/retire',
            json={}
        )
        
        assert response.status_code == 400
        assert 'reason required' in response.get_json()['error'].lower()
    
    def test_non_admin_blocked(self, app, client, make_user):
        """Test non-admin users blocked from approval actions."""
        make_user('viewer', type='tester', password='test123')
        
        with app.app_context():
            model = SOHInferenceModel(
                version='v1.0-test',
                status=InferenceModelStatus.PENDING_APPROVAL.value,
                model_type='linear',
                model_config={},
                feature_names=[]
            )
            db.session.add(model)
            db.session.commit()
            model_id = model.id
        
        from tests.conftest import admin_login
        admin_login(client, tid='viewer', password='test123')
        
        response = client.post(
            f'/admin/soh/inference/models/{model_id}/approve',
            json={'notes': 'Should not work'}
        )
        
        assert response.status_code in (403, 404)  # Either forbidden or not found


class TestInferenceSaving:
    """Test inference result saving."""
    
    def test_inference_saved_to_database(self, app, make_user):
        """Test inference result saved to database."""
        user_id = make_user('admin', type='admin')
        
        with app.app_context():
            ref = BatteryReferenceCapacity(
                maker='현대',
                model='아이오닉5',
                gross_capacity_kwh=72.6,
                verification_level='official'
            )
            db.session.add(ref)
            
            model = SOHInferenceModel(
                version='v1.0-save-test',
                status=InferenceModelStatus.APPROVED.value,
                model_type='linear',
                model_config={},
                model_weights={'intercept': 50.0, 'coefficients': {'capacity_ratio': 50.0}},
                feature_names=['capacity_ratio'],
                approved_at=datetime.utcnow()
            )
            db.session.add(model)
            
            scan = Scan(
                type='ev',
                device_uid='test-device',
                device_type='app',
                tester_id=user_id,
                car_maker='현대',
                car_model='아이오닉5',
                car_no='88가8888',
                car_vin='ZZZ12345678901234'
            )
            db.session.add(scan)
            db.session.commit()
            
            scan_id = scan.id
            
            scan_data = {
                'battery': {'current_capacity_kwh': 65.5},
                'vehicle': {'maker': '현대', 'model': '아이오닉5', 'year': 2022}
            }
            
            result = SOHInferenceEngine.infer_soh(scan_data, scan_id=scan_id, save=True)
            
            assert result is not None
            
            # Verify saved in database
            inferences = db.session.query(SOHInference).filter_by(scan_id=scan_id).all()
            assert len(inferences) == 1
            assert inferences[0].estimated_soh == result.estimated_soh
            assert inferences[0].confidence_score == result.confidence
            assert inferences[0].inference_method == result.method
            assert 'capacity_ratio' in inferences[0].input_features


class TestRuntimeBehavior:
    """Test runtime behavior of inference."""
    
    def test_only_approved_models_used(self, app, make_user):
        """Test only approved models used for inference."""
        user_id = make_user('admin', type='admin')
        
        with app.app_context():
            # Create draft model (should not be used)
            draft = SOHInferenceModel(
                version='v1.0-draft',
                status=InferenceModelStatus.DRAFT.value,
                model_type='linear',
                model_config={},
                model_weights={'intercept': 100.0, 'coefficients': {}},
                feature_names=['capacity_ratio']
            )
            
            # Create retired model (should not be used)
            retired = SOHInferenceModel(
                version='v1.0-retired',
                status=InferenceModelStatus.RETIRED.value,
                model_type='linear',
                model_config={},
                model_weights={'intercept': 100.0, 'coefficients': {}},
                feature_names=['capacity_ratio'],
                approved_at=datetime.utcnow(),
                retired_at=datetime.utcnow()
            )
            
            db.session.add_all([draft, retired])
            db.session.commit()
            
            # Try to infer - should fail because no approved models
            scan_data = {
                'battery': {'current_capacity_kwh': 65.5},
                'vehicle': {'maker': '현대', 'model': '아이오닉5', 'year': 2022}
            }
            
            result = SOHInferenceEngine.infer_soh(scan_data, save=False)
            
            assert result is None  # No approved models available
