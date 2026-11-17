"""SOH Inference Engine - Infer SOH when BMS doesn't provide it directly."""

from typing import Optional, Dict, List, Any, Tuple
from datetime import datetime
import math

from app.extensions import db
from app.modules.soh_inference.models import (
    SOHInferenceModel, SOHInference, InferenceModelStatus
)
from app.modules.scans.battery_soh import find_matching_references


class InferenceResult:
    """SOH inference result."""
    
    def __init__(
        self,
        estimated_soh: float,
        confidence: float,
        method: str,
        model_version: str,
        input_features: Dict[str, Any],
        soh_range: Optional[Tuple[float, float]] = None,
        resolution_chain: Optional[List[str]] = None,
        calculation_details: Optional[Dict[str, Any]] = None
    ):
        self.estimated_soh = estimated_soh
        self.confidence = confidence
        self.method = method
        self.model_version = model_version
        self.input_features = input_features
        self.soh_range = soh_range
        self.resolution_chain = resolution_chain or []
        self.calculation_details = calculation_details or {}


class SOHInferenceEngine:
    """
    SOH Inference Engine.
    
    Infers SOH when BMS doesn't provide it directly using:
    - Current/nominal capacity vs catalog
    - SOC-voltage curve analysis
    - Pack/cell voltage statistics
    - Temperature patterns
    - Energy counters and odometer
    - Vehicle age
    
    Scope resolution: model-specific → manufacturer → global (미산정)
    """
    
    @staticmethod
    def infer_soh(
        scan_data: Dict[str, Any],
        maker: Optional[str] = None,
        model: Optional[str] = None,
        scan_id: Optional[int] = None,
        save: bool = True
    ) -> Optional[InferenceResult]:
        """
        Infer SOH from scan data.
        
        Args:
            scan_data: Scan analysis result (battery, vehicle, etc.)
            maker: Vehicle manufacturer
            model: Vehicle model
            scan_id: Scan ID for saving result
            save: Whether to save inference to database
        
        Returns:
            InferenceResult or None if inference not possible
        """
        battery = scan_data.get('battery', {})
        vehicle = scan_data.get('vehicle', {})
        
        # Extract maker/model from vehicle data if not provided
        if not maker:
            maker = vehicle.get('maker')
        if not model:
            model = vehicle.get('model')
        
        # Try scope resolution chain: model-specific → manufacturer → global
        inference_model, resolution_chain = SOHInferenceEngine._find_best_model(maker, model)
        
        if not inference_model:
            return None
        
        # Extract features
        features = SOHInferenceEngine._extract_features(battery, vehicle, scan_data)
        
        if not features:
            return None
        
        # Run inference based on model type
        result = SOHInferenceEngine._run_inference(inference_model, features)
        
        if not result:
            return None
        
        # Add resolution chain and model version
        result.resolution_chain = resolution_chain
        result.model_version = inference_model.version
        
        # Save to database if requested
        if save and scan_id:
            SOHInferenceEngine._save_inference(scan_id, inference_model.id, result)
        
        return result
    
    @staticmethod
    def _find_best_model(
        maker: Optional[str],
        model: Optional[str]
    ) -> Tuple[Optional[SOHInferenceModel], List[str]]:
        """
        Find best model using scope resolution.
        
        Resolution chain:
        1. Model-specific (maker + model)
        2. Manufacturer-level (maker only)
        3. Global (no scope)
        
        Returns:
            (model, resolution_chain) or (None, []) if none found
        """
        resolution_chain = []
        
        # Only consider approved models
        query_base = db.session.query(SOHInferenceModel).filter(
            SOHInferenceModel.status == InferenceModelStatus.APPROVED.value
        )
        
        # Try model-specific
        if maker and model:
            model_specific = query_base.filter(
                SOHInferenceModel.scope_maker == maker,
                SOHInferenceModel.scope_model == model
            ).order_by(SOHInferenceModel.approved_at.desc()).first()
            
            if model_specific:
                resolution_chain.append('model_specific')
                return model_specific, resolution_chain
        
        # Try manufacturer-level
        if maker:
            manufacturer_level = query_base.filter(
                SOHInferenceModel.scope_maker == maker,
                SOHInferenceModel.scope_model.is_(None)
            ).order_by(SOHInferenceModel.approved_at.desc()).first()
            
            if manufacturer_level:
                resolution_chain.append('manufacturer')
                return manufacturer_level, resolution_chain
        
        # Try global
        global_model = query_base.filter(
            SOHInferenceModel.scope_maker.is_(None),
            SOHInferenceModel.scope_model.is_(None)
        ).order_by(SOHInferenceModel.approved_at.desc()).first()
        
        if global_model:
            resolution_chain.append('미산정')  # Global fallback
            return global_model, resolution_chain
        
        return None, []
    
    @staticmethod
    def _extract_features(
        battery: Dict[str, Any],
        vehicle: Dict[str, Any],
        scan_data: Dict[str, Any]
    ) -> Optional[Dict[str, float]]:
        """Extract inference features from scan data."""
        features = {}
        
        # Capacity-based features
        current_ah = battery.get('current_capacity_ah')
        current_kwh = battery.get('current_capacity_kwh')
        
        # Try to get nominal capacity from catalog
        maker = vehicle.get('maker')
        model_name = vehicle.get('model')
        year = vehicle.get('year')
        vin = vehicle.get('vin')
        
        nominal_kwh = None
        if maker and model_name:
            refs = find_matching_references(maker, model_name, year, vin=vin)
            if refs:
                # Use first match (highest verification level)
                ref = refs[0]
                nominal_kwh = ref.gross_capacity_kwh or ref.net_capacity_kwh or ref.official_capacity_kwh
        
        if current_kwh and nominal_kwh:
            features['capacity_ratio'] = current_kwh / nominal_kwh
        
        # SOC and voltage features
        soc = battery.get('soc')
        if soc is not None:
            features['soc'] = float(soc)
        
        pack_voltage = battery.get('pack_voltage')
        if pack_voltage:
            features['pack_voltage'] = float(pack_voltage)
            if nominal_kwh and current_ah:
                nominal_voltage = (nominal_kwh * 1000) / current_ah
                features['voltage_ratio'] = pack_voltage / nominal_voltage
        
        # Cell voltage statistics
        max_cell_v = battery.get('max_cell_v')
        min_cell_v = battery.get('min_cell_v')
        if max_cell_v and min_cell_v:
            features['max_cell_v'] = float(max_cell_v)
            features['min_cell_v'] = float(min_cell_v)
            features['cell_voltage_deviation'] = float(max_cell_v - min_cell_v)
        
        # Temperature features
        max_temp = battery.get('max_temp')
        min_temp = battery.get('min_temp')
        if max_temp is not None:
            features['max_temp'] = float(max_temp)
        if min_temp is not None:
            features['min_temp'] = float(min_temp)
        if max_temp is not None and min_temp is not None:
            features['temp_deviation'] = float(max_temp - min_temp)
        
        # Energy counters
        charge_kwh = battery.get('lifetime_charge_kwh')
        discharge_kwh = battery.get('lifetime_discharge_kwh')
        if charge_kwh and discharge_kwh:
            features['lifetime_charge_kwh'] = float(charge_kwh)
            features['lifetime_discharge_kwh'] = float(discharge_kwh)
            features['lifetime_throughput_kwh'] = float(charge_kwh + discharge_kwh)
            if nominal_kwh:
                features['throughput_cycles'] = (charge_kwh + discharge_kwh) / (2 * nominal_kwh)
        
        # Odometer and age
        odometer = vehicle.get('odometer_km')
        if odometer:
            features['odometer_km'] = float(odometer)
        
        year_built = vehicle.get('year')
        if year_built:
            current_year = datetime.now().year
            features['vehicle_age_years'] = float(current_year - year_built)
        
        return features if features else None
    
    @staticmethod
    def _run_inference(
        model: SOHInferenceModel,
        features: Dict[str, float]
    ) -> Optional[InferenceResult]:
        """Run inference using the model."""
        model_type = model.model_type
        config = model.model_config
        weights = model.model_weights
        
        if model_type == 'linear':
            return SOHInferenceEngine._run_linear_inference(model, features, config, weights)
        elif model_type == 'polynomial':
            return SOHInferenceEngine._run_polynomial_inference(model, features, config, weights)
        else:
            # Unsupported model type
            return None
    
    @staticmethod
    def _run_linear_inference(
        model: SOHInferenceModel,
        features: Dict[str, float],
        config: Dict[str, Any],
        weights: Optional[Dict[str, Any]]
    ) -> Optional[InferenceResult]:
        """Run linear model inference: SOH = intercept + Σ(coef_i × feature_i)."""
        if not weights:
            return None
        
        intercept = weights.get('intercept', 0.0)
        coefficients = weights.get('coefficients', {})
        
        # Calculate SOH
        soh = intercept
        used_features = {}
        
        for feature_name in model.feature_names:
            if feature_name in features:
                coef = coefficients.get(feature_name, 0.0)
                soh += coef * features[feature_name]
                used_features[feature_name] = features[feature_name]
        
        if not used_features:
            return None
        
        # Clamp to realistic range
        soh = max(50.0, min(110.0, soh))
        
        # Calculate confidence based on feature coverage
        feature_coverage = len(used_features) / len(model.feature_names)
        confidence = feature_coverage * 0.9  # Max 0.9 for linear models
        
        # Calculate range (±5% for linear models)
        range_margin = 5.0
        soh_range = (max(0.0, soh - range_margin), min(100.0, soh + range_margin))
        
        return InferenceResult(
            estimated_soh=round(soh, 1),
            confidence=round(confidence, 2),
            method='linear_model',
            model_version=model.version,
            input_features=used_features,
            soh_range=soh_range,
            calculation_details={
                'intercept': intercept,
                'feature_contributions': {
                    k: round(coefficients.get(k, 0.0) * v, 2)
                    for k, v in used_features.items()
                }
            }
        )
    
    @staticmethod
    def _run_polynomial_inference(
        model: SOHInferenceModel,
        features: Dict[str, float],
        config: Dict[str, Any],
        weights: Optional[Dict[str, Any]]
    ) -> Optional[InferenceResult]:
        """Run polynomial model inference."""
        # Simplified polynomial: SOH = a + b×capacity_ratio + c×capacity_ratio²
        if not weights or 'capacity_ratio' not in features:
            return None
        
        capacity_ratio = features['capacity_ratio']
        
        a = weights.get('a', 0.0)
        b = weights.get('b', 0.0)
        c = weights.get('c', 0.0)
        
        soh = a + b * capacity_ratio + c * (capacity_ratio ** 2)
        
        # Clamp to realistic range
        soh = max(50.0, min(110.0, soh))
        
        confidence = 0.85 if abs(capacity_ratio - 1.0) < 0.3 else 0.70
        
        range_margin = 7.0
        soh_range = (max(0.0, soh - range_margin), min(100.0, soh + range_margin))
        
        return InferenceResult(
            estimated_soh=round(soh, 1),
            confidence=round(confidence, 2),
            method='polynomial_model',
            model_version=model.version,
            input_features={'capacity_ratio': capacity_ratio},
            soh_range=soh_range,
            calculation_details={
                'coefficients': {'a': a, 'b': b, 'c': c},
                'capacity_ratio': capacity_ratio
            }
        )
    
    @staticmethod
    def _save_inference(
        scan_id: int,
        model_id: int,
        result: InferenceResult
    ) -> SOHInference:
        """Save inference result to database."""
        inference = SOHInference(
            scan_id=scan_id,
            model_id=model_id,
            estimated_soh=result.estimated_soh,
            soh_range_min=result.soh_range[0] if result.soh_range else None,
            soh_range_max=result.soh_range[1] if result.soh_range else None,
            confidence_score=result.confidence,
            inference_method=result.method,
            input_features=result.input_features,
            calculation_details=result.calculation_details,
            resolution_chain=result.resolution_chain
        )
        
        db.session.add(inference)
        db.session.commit()
        
        return inference
