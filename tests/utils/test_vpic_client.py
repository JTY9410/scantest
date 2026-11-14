"""Test NHTSA vPIC client with mocked HTTP calls."""
import pytest
from unittest.mock import Mock, patch
from datetime import datetime, timedelta
from app.utils.vpic_client import (
    map_vpic_to_powertrain,
    decode_vin_vpic,
    get_vpic_cached_model_year,
)


def test_map_vpic_to_powertrain():
    """Test vPIC response mapping to powertrain types."""
    # BEV from electrification level
    powertrain, conf = map_vpic_to_powertrain('BEV', 'Electric', None)
    assert powertrain == 'BEV'
    assert conf >= 0.85
    
    # PHEV from electrification level
    powertrain2, conf2 = map_vpic_to_powertrain('PHEV', 'Electric', 'Gasoline')
    assert powertrain2 == 'PHEV'
    assert conf2 >= 0.85
    
    # HEV from electrification level
    powertrain3, conf3 = map_vpic_to_powertrain('HEV', 'Hybrid', None)
    assert powertrain3 == 'HEV'
    assert conf3 >= 0.80
    
    # BEV from fuel type only
    powertrain4, conf4 = map_vpic_to_powertrain(None, 'Electric', None)
    assert powertrain4 == 'BEV'
    assert conf4 >= 0.80
    
    # ICE from fuel type
    powertrain5, conf5 = map_vpic_to_powertrain(None, 'Gasoline', None)
    assert powertrain5 == 'ICE'
    assert conf5 >= 0.70
    
    # Unknown
    powertrain6, conf6 = map_vpic_to_powertrain(None, None, None)
    assert powertrain6 == 'unknown'
    assert conf6 == 0.0


@patch('app.utils.vpic_client.httpx.get')
def test_decode_vin_vpic_success(mock_get):
    """Test successful vPIC API call (mocked)."""
    # Mock HTTP response
    mock_response = Mock()
    mock_response.json.return_value = {
        'Results': [{
            'ElectrificationLevel': 'BEV',
            'FuelTypePrimary': 'Electric',
            'FuelTypeSecondary': None,
            'Make': 'Tesla',
            'Model': 'Model 3',
            'ModelYear': '2023'
        }]
    }
    mock_response.raise_for_status = Mock()
    mock_get.return_value = mock_response
    
    # Mock database connection
    mock_conn = Mock()
    mock_conn.execute.return_value.fetchone.return_value = None  # No cache hit
    
    # Test
    vin = 'KMHXXXXE0NX123456'
    powertrain, source, confidence = decode_vin_vpic(vin, mock_conn)
    
    assert powertrain == 'BEV'
    assert source == 'vpic'
    assert confidence >= 0.85
    
    # Verify API was called
    mock_get.assert_called_once()
    assert 'vpic.nhtsa.dot.gov' in mock_get.call_args[0][0]


@patch('app.utils.vpic_client.httpx.get')
def test_decode_vin_vpic_cached(mock_get):
    """Test vPIC with cached result (no HTTP call)."""
    # Mock database connection with cached data
    mock_conn = Mock()
    expires_at = datetime.now() + timedelta(days=30)
    mock_conn.execute.return_value.fetchone.return_value = (
        'PHEV',  # electrification_level
        'Electric',  # fuel_type_primary
        'Gasoline',  # fuel_type_secondary
        datetime.now(),  # cached_at
        expires_at  # expires_at
    )
    
    vin = 'KMHXXXXF0NX123456'
    powertrain, source, confidence = decode_vin_vpic(vin, mock_conn)
    
    assert powertrain == 'PHEV'
    assert source == 'vpic_cached'
    assert confidence >= 0.80
    
    # Verify NO API call was made (cache hit)
    mock_get.assert_not_called()


@patch('app.utils.vpic_client.httpx.get')
def test_decode_vin_vpic_timeout(mock_get):
    """Test vPIC API timeout (graceful failure)."""
    import httpx
    mock_get.side_effect = httpx.TimeoutException('Timeout')
    
    mock_conn = Mock()
    mock_conn.execute.return_value.fetchone.return_value = None
    
    vin = 'KMHXXXXE0NX123456'
    powertrain, source, confidence = decode_vin_vpic(vin, mock_conn)
    
    assert powertrain == 'unknown'
    assert source == 'vpic_timeout'
    assert confidence == 0.0


@patch('app.utils.vpic_client.httpx.get')
def test_decode_vin_vpic_offline(mock_get):
    """Test vPIC API offline (graceful failure)."""
    import httpx
    mock_get.side_effect = httpx.ConnectError('Connection failed')
    
    mock_conn = Mock()
    mock_conn.execute.return_value.fetchone.return_value = None
    
    vin = 'KMHXXXXE0NX123456'
    powertrain, source, confidence = decode_vin_vpic(vin, mock_conn)
    
    assert powertrain == 'unknown'
    assert source == 'vpic_offline'
    assert confidence == 0.0


@patch('app.utils.vpic_client.httpx.get')
def test_decode_vin_vpic_http_error(mock_get):
    """Test vPIC API HTTP error (404, etc.)."""
    import httpx
    mock_response = Mock()
    mock_response.status_code = 404
    mock_get.side_effect = httpx.HTTPStatusError('Not found', request=Mock(), response=mock_response)
    
    mock_conn = Mock()
    mock_conn.execute.return_value.fetchone.return_value = None
    
    vin = 'KMHXXXXE0NX123456'
    powertrain, source, confidence = decode_vin_vpic(vin, mock_conn)
    
    assert powertrain == 'unknown'
    assert source == 'vpic_not_found'
    assert confidence == 0.0


def test_get_vpic_cached_model_year():
    """Test retrieving cached model year from vPIC."""
    # Mock database connection with cached year
    mock_conn = Mock()
    mock_conn.execute.return_value.fetchone.return_value = (2023,)
    
    vin = 'KMHXXXXE0NX123456'
    year = get_vpic_cached_model_year(vin, mock_conn)
    
    assert year == 2023
    
    # No cached data
    mock_conn2 = Mock()
    mock_conn2.execute.return_value.fetchone.return_value = None
    
    year2 = get_vpic_cached_model_year(vin, mock_conn2)
    assert year2 is None
