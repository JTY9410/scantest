"""Tests for safe formula evaluator."""
import pytest

from app.modules.definitions.formula_eval import (
    SafeFormulaEvaluator,
    evaluate_formula,
    parse_obdb_formula,
)


def test_simple_arithmetic():
    """기본 산술 연산 테스트."""
    assert evaluate_formula("A + B", {"A": 10, "B": 20}) == 30
    assert evaluate_formula("A - B", {"A": 50, "B": 30}) == 20
    assert evaluate_formula("A * B", {"A": 5, "B": 6}) == 30
    assert evaluate_formula("A / B", {"A": 100, "B": 4}) == 25.0


def test_complex_expressions():
    """복합 표현식 테스트."""
    assert evaluate_formula("(A + B) / 2", {"A": 10, "B": 20}) == 15.0
    assert evaluate_formula("A * 0.1 + 5", {"A": 100}) == 15.0
    assert evaluate_formula("A * 256 + B", {"A": 1, "B": 144}) == 400


def test_unary_operators():
    """단항 연산자 테스트."""
    assert evaluate_formula("-A", {"A": 10}) == -10
    assert evaluate_formula("+A", {"A": 10}) == 10
    assert evaluate_formula("A + (-B)", {"A": 10, "B": 5}) == 5


def test_power_and_modulo():
    """거듭제곱과 나머지 연산 테스트."""
    assert evaluate_formula("A ** 2", {"A": 5}) == 25
    assert evaluate_formula("A % B", {"A": 17, "B": 5}) == 2


def test_functions():
    """허용된 함수 테스트."""
    assert evaluate_formula("abs(A)", {"A": -10}) == 10
    assert evaluate_formula("min(A, B)", {"A": 10, "B": 5}) == 5
    assert evaluate_formula("max(A, B)", {"A": 10, "B": 5}) == 10
    assert evaluate_formula("round(A)", {"A": 3.7}) == 4
    assert evaluate_formula("int(A)", {"A": 3.9}) == 3
    assert evaluate_formula("float(A)", {"A": 10}) == 10.0


def test_comparison_operators():
    """비교 연산자 테스트."""
    assert evaluate_formula("A > B", {"A": 10, "B": 5}) is True
    assert evaluate_formula("A < B", {"A": 5, "B": 10}) is True
    assert evaluate_formula("A == B", {"A": 10, "B": 10}) is True
    assert evaluate_formula("A != B", {"A": 10, "B": 5}) is True


def test_value_variable():
    """'value' 변수 (OBD 응답값) 테스트."""
    assert evaluate_formula("value / 10", {"value": 500}) == 50.0
    assert evaluate_formula("value * 0.1", {"value": 1000}) == 100.0
    assert evaluate_formula("value * 256 + 100", {"value": 2}) == 612


def test_obdb_formula_parsing():
    """OBDb fmt → 수식 변환 테스트."""
    assert parse_obdb_formula({"div": 10}) == "value / 10"
    assert parse_obdb_formula({"mul": 0.1}) == "value * 0.1"
    assert parse_obdb_formula({"add": -40}) == "value + -40"
    assert parse_obdb_formula({"mul": 256, "div": 4}) == "(value * 256) / 4"
    assert parse_obdb_formula({}) == "value"


def test_undefined_variable():
    """정의되지 않은 변수 에러 테스트."""
    with pytest.raises(ValueError, match="Undefined variable"):
        evaluate_formula("A + B", {"A": 10})


def test_unsupported_operations():
    """허용되지 않은 연산 에러 테스트."""
    evaluator = SafeFormulaEvaluator()
    
    # attribute access 불가
    with pytest.raises(ValueError):
        evaluator.evaluate("value.__class__", {"value": 10})
    
    # import 불가
    with pytest.raises(ValueError):
        evaluator.evaluate("__import__('os')", {})


def test_no_builtins():
    """내장 함수 접근 불가 테스트."""
    with pytest.raises(ValueError):
        evaluate_formula("__builtins__", {})
    
    with pytest.raises(ValueError):
        evaluate_formula("open('file.txt')", {})


def test_real_obd_formulas():
    """실제 OBD 수식 테스트."""
    # Engine coolant temp: A - 40
    assert evaluate_formula("A - 40", {"A": 80}) == 40
    
    # Engine RPM: (A * 256 + B) / 4
    assert evaluate_formula("(A * 256 + B) / 4", {"A": 0x0C, "B": 0x80}) == 800.0
    
    # Vehicle speed: A
    assert evaluate_formula("A", {"A": 60}) == 60
    
    # Battery voltage: (A * 256 + B) * 0.1
    assert evaluate_formula("(A * 256 + B) * 0.1", {"A": 1, "B": 144}) == 40.0
