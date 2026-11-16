"""Tesla VIN decoder using committed VIN코드표."""

# Tesla VIN Position Mappings (from VIN코드표 sheet)
# Position 4: Model
TESLA_MODEL_CODES = {
    'S': 'Model S',
    '3': 'Model 3',
    'X': 'Model X',
    'Y': 'Model Y',
}

# Position 10: Year
TESLA_YEAR_CODES = {
    '9': 2009, 'A': 2010, 'B': 2011, 'C': 2012, 'D': 2013,
    'E': 2014, 'F': 2015, 'G': 2016, 'H': 2017, 'J': 2018,
    'K': 2019, 'L': 2020, 'M': 2021, 'N': 2022, 'P': 2023,
    'R': 2024, 'S': 2025, 'T': 2026, 'V': 2027, 'W': 2028,
    'X': 2029, 'Y': 2030,
}

# Position 8: Motor/Drive (examples, may vary by model)
TESLA_MOTOR_CODES = {
    'A': 'Single Motor RWD',
    'B': 'Dual Motor AWD',
    'C': 'Performance Dual Motor',
    'D': 'Dual Motor',
    'E': 'Dual Motor AWD',
    'F': 'Performance AWD',
    # Add more as needed
}

# Position 11: Plant
TESLA_PLANT_CODES = {
    'F': 'Fremont',
    'C': 'Shanghai',
    'B': 'Berlin',
    # Add more as needed
}


def decode_tesla_vin(vin: str) -> dict:
    """Decode Tesla VIN.
    
    Returns:
        dict with wmi, model, year, motor_code, plant_code, serial
        Returns None for fields that can't be decoded.
    """
    if not vin or len(vin) < 17:
        return {}
    
    wmi = vin[0:3]  # Pos 1-3
    if wmi != '5YJ':
        return {}  # Not a Tesla VIN
    
    model_code = vin[3]  # Pos 4
    model = TESLA_MODEL_CODES.get(model_code)
    
    year_code = vin[9]  # Pos 10
    year = TESLA_YEAR_CODES.get(year_code)
    
    motor_code = vin[7]  # Pos 8
    motor = TESLA_MOTOR_CODES.get(motor_code, f'Code-{motor_code}')
    
    plant_code = vin[10]  # Pos 11
    plant = TESLA_PLANT_CODES.get(plant_code, f'Plant-{plant_code}')
    
    serial = vin[11:17]  # Pos 12-17
    
    return {
        'wmi': wmi,
        'model_code': model_code,
        'model': model,
        'year_code': year_code,
        'year': year,
        'motor_code': motor_code,
        'motor': motor,
        'plant_code': plant_code,
        'plant': plant,
        'serial': serial,
        'valid': model is not None and year is not None,
    }
