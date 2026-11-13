"""Test vehicle powertrain classifier with real data formats."""
import pytest
from app.modules.definitions.vehicle_classifier import (
    normalize_text,
    extract_tokens,
    is_not_vehicle,
    classify_vehicle_powertrain,
)


def test_normalize_text():
    """Test text normalization handles real formats."""
    # Underscores
    assert normalize_text('Hyundai_ Ioniq5') == 'hyundai ioniq5'
    
    # Colons
    assert normalize_text('Brand: Model') == 'brand model'
    
    # Mixed
    assert normalize_text('Hyundai_ Ioniq5_Ioniq6 72kWh') == 'hyundai ioniq5 ioniq6 72kwh'
    
    # Dashes
    assert normalize_text('e-Golf') == 'e golf'
    
    # Multiple spaces/underscores
    assert normalize_text('Some__Text  With   Spaces') == 'some text with spaces'


def test_extract_tokens():
    """Test token extraction."""
    tokens = extract_tokens('hyundai ioniq5 ioniq6 72kwh')
    assert 'hyundai' in tokens
    assert 'ioniq5' in tokens
    assert '72kwh' in tokens
    
    # Korean
    tokens_kr = extract_tokens('hyundai 공용 protocol')
    assert '공용' in tokens_kr


def test_is_not_vehicle():
    """Test not_vehicle detection for ECU vendors and protocols."""
    # ECU vendor makers
    assert is_not_vehicle('MARELLI', None, None) == True
    assert is_not_vehicle('BOSCH', None, None) == True
    assert is_not_vehicle('TEVES', None, None) == True
    assert is_not_vehicle('Dallara', None, None) == True
    
    # ECU vendor in model
    assert is_not_vehicle(None, 'MARELLI ECU', None) == True
    
    # File path patterns
    assert is_not_vehicle(None, None, '01_DBC/_ECU_장비_프로토콜/MARELLI/file.dbc') == True
    assert is_not_vehicle(None, None, '01_DBC/_공통_프로토콜/OBD2/obd2.dbc') == True
    assert is_not_vehicle(None, None, '04_Torque_PID/OBD2/something.csv') == True
    
    # Shared/common protocol folders (공용 pattern) → not_vehicle
    assert is_not_vehicle('Hyundai_Kia_Genesis_공용', None, None) == True
    assert is_not_vehicle('Volkswagen_Group_공용', None, None) == True
    assert is_not_vehicle('GM_공용', None, None) == True
    
    # Regular vehicles
    assert is_not_vehicle('Hyundai', 'Ioniq 5', '02_OBDb/Hyundai/IONIQ 5/default.json') == False


def test_classify_real_formats():
    """Test classification with exact real data formats from production."""
    # Real format 1: WiCAN with underscores and spaces
    pt, src, conf = classify_vehicle_powertrain(
        maker='Hyundai_ Ioniq5_Ioniq6 72kWh',
        model='Hyundai: Ioniq5/Ioniq6 72kWh',
        submodel=None,
        file_path='03_WiCAN_PID/Hyundai/Hyundai_ Ioniq5_Ioniq6 72kWh/profile.json'
    )
    assert pt == 'BEV', f"Expected BEV for Ioniq5, got {pt}"
    assert 'model_name' in src or 'BEV' in src
    assert conf > 0.8
    
    # Real format 2: VW e-Golf
    pt2, src2, conf2 = classify_vehicle_powertrain(
        maker='Volkswagen',
        model='e-Golf',
        submodel=None,
        file_path='02_OBDb_진단정의/VW/e-Golf/default.json'
    )
    assert pt2 == 'BEV', f"Expected BEV for e-Golf, got {pt2}"
    assert 'model_name' in src2 or 'BEV' in src2
    
    # Real format 3: Renault ZOE with maker '-'
    pt3, src3, conf3 = classify_vehicle_powertrain(
        maker='-',
        model='ZOE_Ph2',
        submodel=None,
        file_path='01_DBC/Renault/ZOE_Ph2.dbc'
    )
    assert pt3 == 'BEV', f"Expected BEV for ZOE, got {pt3}"
    assert 'model_name' in src3 or 'BEV' in src3
    
    # Real format 4: ECU vendor MARELLI
    pt4, src4, conf4 = classify_vehicle_powertrain(
        maker='MARELLI',
        model=None,
        submodel=None,
        file_path='01_DBC/_ECU_장비_프로토콜/MARELLI/marelli_ecu.dbc'
    )
    assert pt4 == 'not_vehicle', f"Expected not_vehicle for MARELLI, got {pt4}"
    assert src4 == 'path_token'
    
    # Real format 5: TEVES (ECU vendor)
    pt5, src5, conf5 = classify_vehicle_powertrain(
        maker='TEVES',
        model=None,
        submodel=None,
        file_path='01_DBC/_ECU_장비_프로토콜/TEVES/abs.dbc'
    )
    assert pt5 == 'not_vehicle', f"Expected not_vehicle for TEVES, got {pt5}"
    
    # Real format 6: Dallara (race car, not street vehicle)
    pt6, src6, conf6 = classify_vehicle_powertrain(
        maker='Dallara',
        model='Formula',
        submodel=None,
        file_path='01_DBC/Dallara/formula.dbc'
    )
    assert pt6 == 'not_vehicle', f"Expected not_vehicle for Dallara, got {pt6}"
    
    # Real format 7: Common protocols (공통)
    pt7, src7, conf7 = classify_vehicle_powertrain(
        maker=None,
        model='OBD2',
        submodel=None,
        file_path='01_DBC/_공통_프로토콜/OBD2/obd2.dbc'
    )
    assert pt7 == 'not_vehicle', f"Expected not_vehicle for OBD2 protocol, got {pt7}"
    
    # Real format 8: Shared folder (공용) - this is tricky, depends on content
    # 'Hyundai_Kia_Genesis_공용' is a shared definitions folder, not a vendor
    # Should not be classified as not_vehicle
    pt8, src8, conf8 = classify_vehicle_powertrain(
        maker='Hyundai_Kia_Genesis_공용',
        model='Common Commands',
        submodel=None,
        file_path='02_OBDb/Hyundai_Kia_Genesis/common.json'
    )
    # This should be unknown (no clear BEV/PHEV/HEV indicators)
    assert pt8 == 'unknown', f"Expected unknown for shared folder, got {pt8}"
    
    # Real format 9: Kia Ray EV from Torque
    pt9, src9, conf9 = classify_vehicle_powertrain(
        maker=None,
        model='extendedpids',
        submodel=None,
        file_path='04_Torque_PID/Ray EV/extendedpids/Kia_Ray_EV_Extra_gauges.csv'
    )
    assert pt9 == 'BEV', f"Expected BEV for Ray EV (from path), got {pt9}"
    
    # Real format 10: Chrysler Pacifica (has both ICE and hybrid - ambiguous)
    pt10, src10, conf10 = classify_vehicle_powertrain(
        maker='Chrysler',
        model='Pacifica 2015+',
        submodel=None,
        file_path='02_OBDb/Chrysler/Pacifica_2015+/default.json'
    )
    # Without clear hybrid marker, should be unknown
    assert pt10 == 'unknown', f"Expected unknown for ambiguous Pacifica, got {pt10}"
    
    # Real format 11: Chrysler Pacifica Hybrid (explicit)
    pt11, src11, conf11 = classify_vehicle_powertrain(
        maker='Chrysler',
        model='Pacifica Hybrid',
        submodel=None,
        file_path='02_OBDb/Chrysler/Pacifica_Hybrid/default.json'
    )
    assert pt11 == 'HEV', f"Expected HEV for Pacifica Hybrid, got {pt11}"
    
    # Real format 12: Tesla Model 3
    pt12, src12, conf12 = classify_vehicle_powertrain(
        maker='Tesla',
        model='Model 3',
        submodel=None,
        file_path='01_DBC/Tesla/Model3CAN.dbc'
    )
    assert pt12 == 'BEV', f"Expected BEV for Tesla Model 3, got {pt12}"


def test_bev_combinations():
    """Test BEV combinations (multiple tokens required)."""
    # Kona Electric
    pt, src, conf = classify_vehicle_powertrain(
        maker='Hyundai',
        model='Kona Electric',
        submodel=None,
        file_path=None
    )
    assert pt == 'BEV'
    
    # Niro EV
    pt2, src2, conf2 = classify_vehicle_powertrain(
        maker='Kia',
        model='Niro EV',
        submodel=None,
        file_path=None
    )
    assert pt2 == 'BEV'


def test_phev_priority():
    """Test PHEV takes priority over HEV."""
    pt, src, conf = classify_vehicle_powertrain(
        maker='Jeep',
        model='Wrangler 4xe',
        submodel='Plug-in Hybrid',
        file_path=None
    )
    assert pt == 'PHEV', f"Expected PHEV, got {pt}"


def test_hev_not_phev():
    """Test HEV without plug-in."""
    pt, src, conf = classify_vehicle_powertrain(
        maker='Toyota',
        model='Prius',
        submodel='Hybrid',
        file_path=None
    )
    assert pt == 'HEV', f"Expected HEV for Prius, got {pt}"


def test_unknown_cases():
    """Test that ambiguous cases stay unknown."""
    # Generic Tucson without clear powertrain marker
    pt, src, conf = classify_vehicle_powertrain(
        maker='Hyundai',
        model='Tucson',
        submodel=None,
        file_path='02_OBDb/Hyundai/Tucson/default.json'
    )
    assert pt == 'unknown', f"Expected unknown for generic Tucson, got {pt}"
    
    # Empty/minimal data
    pt2, src2, conf2 = classify_vehicle_powertrain(
        maker=None,
        model=None,
        submodel=None,
        file_path=None
    )
    assert pt2 == 'unknown'


# Regression tests from production data (2026-11-13 user report)
@pytest.mark.parametrize("maker,model,submodel,file_path,expected_pt,description", [
    # WRONG → BEV (were classified as HEV)
    ('Hyundai', 'IONIQ-5', None, None, 'BEV', 'IONIQ-5 specific model'),
    ('Hyundai', 'IONIQ-6', None, None, 'BEV', 'IONIQ-6 specific model'),
    ('Hyundai', 'IONIQ-9', None, None, 'BEV', 'IONIQ-9 specific model'),
    ('Hyundai', 'IONIQ-Electric', None, None, 'BEV', 'IONIQ Electric qualifier'),
    (None, 'Hyundai: Ioniq Electric 38kWh (2020-2021)', None, None, 'BEV', 'Ioniq Electric in model'),
    (None, None, None, '04_Torque_PID/Ioniq EV - 28kWh/extendedpids/Hyundai_Ioniq_EV_*.csv', 'BEV', 'Ioniq EV folder'),
    
    # WRONG → HEV (were classified as BEV due to 'ev' in HEV)
    (None, None, None, '04_Torque_PID/Kia Niro HEV/extendedpids/Kia_Niro_HEV*.csv', 'HEV', 'Niro HEV folder'),
    (None, None, None, '04_Torque_PID/Ioniq HEV/extendedpids/Hyundai_Ioniq_EV_VMCU_data.csv', 'HEV', 'Ioniq HEV folder'),
    
    # WRONG → PHEV (were classified as HEV)
    ('Toyota', 'Prius-Prime', None, None, 'PHEV', 'Prius Prime'),
    ('BMW', '2-Series-Plug-in-Hybrid', None, None, 'PHEV', 'Plug-in Hybrid explicit'),
    
    # AMBIGUOUS → unknown (have multiple variants)
    ('Hyundai', 'Kona', None, None, 'unknown', 'Kona ambiguous base'),
    ('Kia', 'Niro', None, None, 'unknown', 'Niro ambiguous base'),
    (None, 'Kia: Niro/Soul', None, None, 'unknown', 'Niro/Soul ambiguous'),
    ('Porsche', 'Macan', None, '02_OBDb/Porsche/Macan/default.json', 'unknown', 'Macan generic'),
    ('Hyundai', 'Ioniq', None, None, 'unknown', 'Ioniq base without qualifier'),
    
    # MISSED BEV
    ('Audi', 'e-tron', None, None, 'BEV', 'Audi e-tron'),
    ('Audi', 'e-tron-GT', None, None, 'BEV', 'Audi e-tron GT'),
    ('Audi', 'RS-e-tron', None, None, 'BEV', 'Audi RS e-tron'),
    ('BMW', 'iX3', None, None, 'BEV', 'BMW iX3'),
    (None, 'GMC: Sierra EV', None, None, 'BEV', 'GMC Sierra EV'),
    (None, 'KGM: Torres EVX', None, None, 'BEV', 'KGM Torres EVX'),
    ('MG', 'ZS-EV', None, None, 'BEV', 'MG ZS-EV'),
    (None, 'Opel: Ampere-E', None, None, 'BEV', 'Opel Ampere-E'),
    (None, 'Volvo: XC40 BEV', None, None, 'BEV', 'Volvo XC40 BEV'),
    (None, 'Hyundai: Ioniq9', None, None, 'BEV', 'Hyundai Ioniq9'),
    
    # MISSED PHEV
    ('Audi', 'A3-e-tron', None, None, 'PHEV', 'Audi A3 e-tron'),
    ('Chevrolet', 'Volt', None, None, 'PHEV', 'Chevrolet Volt'),
    (None, 'Chevrolet: Volt/Ampera', None, None, 'PHEV', 'Volt/Ampera'),
    ('Ford', 'C-Max-Energi', None, None, 'PHEV', 'Ford C-Max Energi'),
    ('Ford', 'Fusion-Energi', None, None, 'PHEV', 'Ford Fusion Energi'),
    ('Toyota', 'RAV4-Prime', None, None, 'PHEV', 'Toyota RAV4 Prime'),
])
def test_production_regression_cases(maker, model, submodel, file_path, expected_pt, description):
    """Regression tests from real production data (2026-11-13 report)."""
    pt, src, conf = classify_vehicle_powertrain(maker, model, submodel, file_path)
    assert pt == expected_pt, f"{description}: expected {expected_pt}, got {pt} (source: {src})"


# Additional regression tests from 2026-11-13 22:28 report
@pytest.mark.parametrize("maker,model,submodel,file_path,expected_pt,description", [
    # Toyota Prius models (all HEV except Prime)
    ('Toyota', 'Prius', None, None, 'HEV', 'Prius base model'),
    ('Toyota', 'Prius-v', None, None, 'HEV', 'Prius-v'),
    
    # Lexus h suffix = HEV
    ('Lexus', 'ES-300h', None, None, 'HEV', 'Lexus ES-300h'),
    ('Lexus', 'RX450h', None, None, 'HEV', 'Lexus RX450h'),
    ('Lexus', 'NX350h', None, None, 'HEV', 'Lexus NX350h'),
    ('Lexus', 'UX250h', None, None, 'HEV', 'Lexus UX250h'),
    
    # Lexus h+ suffix = PHEV
    ('Lexus', 'RX450h+', None, None, 'PHEV', 'Lexus RX450h+'),
    
    # Mixed powertrain → unknown
    (None, 'Hyundai: Ioniq Hybrid EV (2016-2019)', None, None, 'unknown', 'Mixed Hybrid+EV'),
    
    # BEV-only nameplates
    ('Subaru', 'Solterra', None, None, 'BEV', 'Subaru Solterra'),
    ('Toyota', 'bZ4X', None, None, 'BEV', 'Toyota bZ4X'),
    ('Polestar', '2', None, None, 'BEV', 'Polestar 2'),
    ('VW', 'Enyaq', None, None, 'BEV', 'VW Enyaq'),
    ('Cupra', 'Born', None, None, 'BEV', 'Cupra Born'),
    ('Dacia', 'Spring', None, None, 'BEV', 'Dacia Spring'),
    ('Peugeot', 'e-208', None, None, 'BEV', 'Peugeot e-208'),
    ('Peugeot', 'e-2008', None, None, 'BEV', 'Peugeot e-2008'),
    ('Rivian', 'R1T', None, None, 'BEV', 'Rivian R1T'),
    ('Lucid', 'Air', None, None, 'BEV', 'Lucid Air'),
    
    # Shared/common definitions → not_vehicle
    ('Volkswagen_Group_공용', None, None, None, 'not_vehicle', 'VW Group shared'),
    ('GM_공용', None, None, None, 'not_vehicle', 'GM shared'),
    ('Hyundai_Kia_Genesis_공용', None, None, None, 'not_vehicle', 'HKG shared'),
    ('Honda_Acura_공용', None, None, None, 'not_vehicle', 'Honda/Acura shared'),
    
    # ECU vendor → not_vehicle
    ('MECTRONIK', None, None, None, 'not_vehicle', 'MECTRONIK ECU vendor'),
])
def test_production_regression_2(maker, model, submodel, file_path, expected_pt, description):
    """Additional regression tests from 2026-11-13 22:28 report."""
    pt, src, conf = classify_vehicle_powertrain(maker, model, submodel, file_path)
    assert pt == expected_pt, f"{description}: expected {expected_pt}, got {pt} (source: {src})"
