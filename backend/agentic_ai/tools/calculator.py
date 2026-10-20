import math

from langchain_core.tools import tool


def _finite_result(value: float) -> float:
    if not math.isfinite(value):
        raise ValueError("The result is outside the supported numeric range.")
    return value


@tool
def add_numbers(first: float, second: float) -> float:
    """Add two numbers."""
    return _finite_result(first + second)


@tool
def subtract_numbers(first: float, second: float) -> float:
    """Subtract the second number from the first."""
    return _finite_result(first - second)


@tool
def multiply_numbers(first: float, second: float) -> float:
    """Multiply two numbers."""
    return _finite_result(first * second)


@tool
def divide_numbers(first: float, second: float) -> float:
    """Divide the first number by the second."""
    if second == 0:
        raise ValueError("Cannot divide by zero.")
    return _finite_result(first / second)


tools = [add_numbers, subtract_numbers, multiply_numbers, divide_numbers]
tools_by_name = {calculator.name: calculator for calculator in tools}


if __name__ == "__main__":
    print(add_numbers.invoke({"first": 10.2, "second": 5.8}))