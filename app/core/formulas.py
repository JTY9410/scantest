"""안전한 수식 평가기 (SCANNER_ALLOW_EXPERIMENTAL 플래그 준수)"""
import ast
import operator
from typing import Any


# 허용된 연산자 (안전한 수학 연산만)
SAFE_OPERATORS = {
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

# 허용된 함수
SAFE_FUNCTIONS = {
    'abs': abs,
    'round': round,
    'min': min,
    'max': max,
    'int': int,
    'float': float,
}


class SafeEvaluator(ast.NodeVisitor):
    """안전한 수식 평가 AST 방문자"""
    
    def __init__(self, variables: dict[str, Any]):
        self.variables = variables
    
    def visit_Expression(self, node):
        return self.visit(node.body)
    
    def visit_Constant(self, node):
        return node.value
    
    def visit_Name(self, node):
        if node.id in self.variables:
            return self.variables[node.id]
        raise ValueError(f"Undefined variable: {node.id}")
    
    def visit_BinOp(self, node):
        op_type = type(node.op)
        if op_type not in SAFE_OPERATORS:
            raise ValueError(f"Unsafe operator: {op_type.__name__}")
        
        left = self.visit(node.left)
        right = self.visit(node.right)
        return SAFE_OPERATORS[op_type](left, right)
    
    def visit_UnaryOp(self, node):
        op_type = type(node.op)
        if op_type not in SAFE_OPERATORS:
            raise ValueError(f"Unsafe unary operator: {op_type.__name__}")
        
        operand = self.visit(node.operand)
        return SAFE_OPERATORS[op_type](operand)
    
    def visit_Call(self, node):
        if not isinstance(node.func, ast.Name):
            raise ValueError("Only simple function calls allowed")
        
        func_name = node.func.id
        if func_name not in SAFE_FUNCTIONS:
            raise ValueError(f"Unsafe function: {func_name}")
        
        args = [self.visit(arg) for arg in node.args]
        return SAFE_FUNCTIONS[func_name](*args)
    
    def generic_visit(self, node):
        raise ValueError(f"Unsafe AST node: {type(node).__name__}")


def safe_eval(expression: str, variables: dict[str, Any] = None) -> Any:
    """안전하게 수식을 평가
    
    Args:
        expression: 평가할 수식 (예: "x/2", "(x-32768)/10")
        variables: 변수 딕셔너리 (예: {'x': 100})
    
    Returns:
        평가 결과
    
    Raises:
        ValueError: 안전하지 않은 수식이거나 구문 오류
        
    Examples:
        >>> safe_eval("x/2", {'x': 100})
        50.0
        >>> safe_eval("(x-32768)/10", {'x': 33000})
        23.2
        >>> safe_eval("abs(x)", {'x': -5})
        5
    """
    if variables is None:
        variables = {}
    
    try:
        # AST 파싱
        tree = ast.parse(expression, mode='eval')
        
        # 안전한 평가
        evaluator = SafeEvaluator(variables)
        result = evaluator.visit(tree)
        
        return result
    
    except SyntaxError as e:
        raise ValueError(f"Syntax error in expression: {e}")
    except Exception as e:
        raise ValueError(f"Evaluation error: {e}")
