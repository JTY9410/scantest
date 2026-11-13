"""Safe formula evaluator without eval()."""
import ast
import operator
import re
from typing import Any


class SafeFormulaEvaluator:
    """안전한 수식 평가기 - eval() 없이 AST로 파싱."""
    
    # 허용된 연산자
    OPERATORS = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv,
        ast.Mod: operator.mod,
        ast.Pow: operator.pow,
        ast.USub: operator.neg,
        ast.UAdd: operator.pos,
    }
    
    # 허용된 비교 연산자
    COMPARISONS = {
        ast.Eq: operator.eq,
        ast.NotEq: operator.ne,
        ast.Lt: operator.lt,
        ast.LtE: operator.le,
        ast.Gt: operator.gt,
        ast.GtE: operator.ge,
    }
    
    # 허용된 함수
    FUNCTIONS = {
        'abs': abs,
        'min': min,
        'max': max,
        'round': round,
        'int': int,
        'float': float,
    }
    
    def __init__(self):
        self.variables = {}
    
    def evaluate(self, formula: str, variables: dict[str, Any]) -> Any:
        """수식 평가.
        
        Args:
            formula: 평가할 수식 (예: "A * 0.1 + B", "value / 10")
            variables: 변수 값 딕셔너리 (예: {"A": 100, "B": 50})
        
        Returns:
            계산 결과
        
        Raises:
            ValueError: 허용되지 않은 연산이나 구문 오류
        """
        self.variables = variables
        
        try:
            # 수식을 AST로 파싱
            tree = ast.parse(formula, mode='eval')
            result = self._eval_node(tree.body)
            return result
        except (SyntaxError, ValueError, KeyError) as e:
            raise ValueError(f"Invalid formula '{formula}': {e}")
    
    def _eval_node(self, node: ast.AST) -> Any:
        """AST 노드 평가."""
        if isinstance(node, ast.Constant):
            # 상수 (숫자, 문자열 등)
            return node.value
        
        elif isinstance(node, ast.Num):  # Python 3.7 호환
            return node.n
        
        elif isinstance(node, ast.Name):
            # 변수 참조
            if node.id not in self.variables:
                raise ValueError(f"Undefined variable: {node.id}")
            return self.variables[node.id]
        
        elif isinstance(node, ast.BinOp):
            # 이항 연산 (a + b, a * b 등)
            if type(node.op) not in self.OPERATORS:
                raise ValueError(f"Unsupported operator: {type(node.op).__name__}")
            
            left = self._eval_node(node.left)
            right = self._eval_node(node.right)
            op_func = self.OPERATORS[type(node.op)]
            return op_func(left, right)
        
        elif isinstance(node, ast.UnaryOp):
            # 단항 연산 (-a, +a)
            if type(node.op) not in self.OPERATORS:
                raise ValueError(f"Unsupported unary operator: {type(node.op).__name__}")
            
            operand = self._eval_node(node.operand)
            op_func = self.OPERATORS[type(node.op)]
            return op_func(operand)
        
        elif isinstance(node, ast.Compare):
            # 비교 연산 (a > b, a == b)
            left = self._eval_node(node.left)
            
            for op, comparator in zip(node.ops, node.comparators):
                if type(op) not in self.COMPARISONS:
                    raise ValueError(f"Unsupported comparison: {type(op).__name__}")
                
                right = self._eval_node(comparator)
                op_func = self.COMPARISONS[type(op)]
                
                if not op_func(left, right):
                    return False
                left = right
            
            return True
        
        elif isinstance(node, ast.Call):
            # 함수 호출
            if not isinstance(node.func, ast.Name):
                raise ValueError("Only simple function calls are allowed")
            
            func_name = node.func.id
            if func_name not in self.FUNCTIONS:
                raise ValueError(f"Unsupported function: {func_name}")
            
            args = [self._eval_node(arg) for arg in node.args]
            func = self.FUNCTIONS[func_name]
            return func(*args)
        
        elif isinstance(node, ast.IfExp):
            # 삼항 연산자 (a if condition else b)
            test = self._eval_node(node.test)
            if test:
                return self._eval_node(node.body)
            else:
                return self._eval_node(node.orelse)
        
        else:
            raise ValueError(f"Unsupported AST node: {type(node).__name__}")


def evaluate_formula(formula: str, variables: dict[str, Any]) -> Any:
    """수식 평가 헬퍼 함수.
    
    Examples:
        >>> evaluate_formula("A * 0.1", {"A": 100})
        10.0
        >>> evaluate_formula("(A + B) / 2", {"A": 10, "B": 20})
        15.0
        >>> evaluate_formula("value / 10", {"value": 500})
        50.0
    """
    evaluator = SafeFormulaEvaluator()
    return evaluator.evaluate(formula, variables)


def parse_obdb_formula(fmt: dict) -> str:
    """OBDb fmt 구조를 수식 문자열로 변환.
    
    OBDb 포맷:
    - div: value / div
    - mul: value * mul
    - add: value + add
    - sign: true면 signed 정수
    """
    parts = []
    
    if 'mul' in fmt:
        parts.append(f"value * {fmt['mul']}")
    
    if 'div' in fmt:
        if parts:
            parts.append(f"({parts.pop()}) / {fmt['div']}")
        else:
            parts.append(f"value / {fmt['div']}")
    
    if 'add' in fmt:
        if parts:
            parts.append(f"({parts.pop()}) + {fmt['add']}")
        else:
            parts.append(f"value + {fmt['add']}")
    
    if not parts:
        return "value"
    
    return parts[0]


def parse_torque_formula(formula_str: str) -> str:
    """Torque 수식을 표준 형식으로 변환.
    
    Torque 포맷:
    - val{PID_NAME}: 다른 PID 참조
    - 일반 산술 연산
    """
    # val{...}를 변수명으로 변환 (간단히 제거)
    formula = re.sub(r'val\{([^}]+)\}', r'\1', formula_str)
    
    # 변수명 정리 (공백 등 제거)
    formula = re.sub(r'[^\w\s\+\-\*/\(\)\.]', '', formula)
    
    return formula.strip()
