import ast
import math
import re

_BIN_OPS = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b if b != 0 else (_ for _ in ()).throw(ZeroDivisionError("Division by zero")),
    ast.FloorDiv: lambda a, b: a // b if b != 0 else (_ for _ in ()).throw(ZeroDivisionError("Division by zero")),
    ast.Mod: lambda a, b: a % b if b != 0 else (_ for _ in ()).throw(ZeroDivisionError("Division by zero")),
    ast.Pow: lambda a, b: a ** b if abs(b) <= 100 else (_ for _ in ()).throw(ValueError("Exponent too large")),
}

_UNARY_OPS = {
    ast.UAdd: lambda a: +a,
    ast.USub: lambda a: -a,
}


def _eval_math_node(node):
    if isinstance(node, ast.Expression):
        return _eval_math_node(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return float(node.value)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
        return _UNARY_OPS[type(node.op)](_eval_math_node(node.operand))
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
        return _BIN_OPS[type(node.op)](_eval_math_node(node.left), _eval_math_node(node.right))
    raise ValueError("Unsupported math expression")


def try_calculate(prompt: str) -> str | None:
    cleaned = prompt.strip()

    # Handle "X% of Y" patterns
    pct_match = re.search(r"([+-]?\d+(?:\.\d+)?)\s*%\s*(?:of\s*)?([+-]?\d+(?:\.\d+)?)", cleaned, re.IGNORECASE)
    if pct_match and any(k in cleaned.lower() for k in ["%", "percent", "of"]):
        pct_val = float(pct_match.group(1))
        base_val = float(pct_match.group(2))
        ans = round((pct_val / 100.0) * base_val, 4)
        return f"Calculation: {pct_val}% of {base_val} = {ans:g}"

    # Extract candidate arithmetic expression
    expr_match = re.search(r"[\d\s\+\-\*\/\%\(\)\.\^]+", cleaned)
    if not expr_match:
        return None

    expr = expr_match.group(0).strip().replace("^", "**")
    has_digit = any(ch.isdigit() for ch in expr)
    has_op = any(op in expr for op in ["+", "-", "*", "/", "%", "**"])
    if not (has_digit and has_op):
        return None

    try:
        parsed = ast.parse(expr, mode="eval")
        result = _eval_math_node(parsed)
        if isinstance(result, float) and (math.isnan(result) or math.isinf(result)):
            return "The result of this calculation is infinite or undefined."
        formatted = f"{round(result, 6):g}"
        return f"Calculation: {expr.replace('**', '^')} = {formatted}"
    except ZeroDivisionError:
        return "Division by zero is not allowed. Please change the denominator and try again."
    except Exception:
        return None


_SUBJECT_KNOWLEDGE = [
    {
        "keys": ["algorithm", "complexity", "big o", "sorting", "binary search", "recursion", "time complexity", "space complexity"],
        "title": "Algorithms & Problem Solving",
        "body": (
            "An algorithm is a clear, step-by-step set of instructions to solve a specific problem.\n"
            "* Time & Space Complexity: Describes how runtime or memory grows as input size (n) increases—such as O(1), O(log n), O(n), and O(n log n).\n"
            "* Recursion: A technique where a function calls itself on a smaller subproblem and stops at a base case."
        ),
    },
    {
        "keys": ["data structure", "array", "linked list", "stack", "queue", "tree", "graph", "hash", "heap"],
        "title": "Data Structures",
        "body": (
            "A data structure organizes data in memory so it can be accessed, searched, or updated efficiently.\n"
            "* Stack (LIFO): Last-In, First-Out—useful for undo/redo history or function call stacks.\n"
            "* Queue (FIFO): First-In, First-Out—useful for task queues or breadth-first traversal.\n"
            "* Trees & Graphs: Model hierarchical relationships or connected networks and paths."
        ),
    },
    {
        "keys": ["oop", "object oriented", "class", "object", "inheritance", "polymorphism", "encapsulation", "abstraction"],
        "title": "Object-Oriented Programming (OOP)",
        "body": (
            "OOP models real-world entities using Classes (blueprints) and Objects (instances).\n"
            "* Encapsulation: Bundling data and methods together while controlling direct access.\n"
            "* Inheritance: Allowing a child class to reuse and extend attributes/methods of a parent class.\n"
            "* Polymorphism: Allowing the same interface or method name to behave differently across types.\n"
            "* Abstraction: Hiding internal complexity behind a clean, essential interface."
        ),
    },
    {
        "keys": ["python", "flask", "sql", "database", "html", "css", "loop", "function", "api", "git"],
        "title": "Programming & Web Basics",
        "body": (
            "* Loops (for / while): Repeat a block of code while a condition holds or over items in a sequence.\n"
            "* Functions: Reusable blocks of code that can take inputs (parameters) and return results.\n"
            "* Relational Databases & SQL: Store structured data in tables linked by keys and query it with SQL."
        ),
    },
    {
        "keys": ["math", "algebra", "calculus", "derivative", "integral", "probability", "matrix", "trigonometry", "equation"],
        "title": "Mathematics Basics",
        "body": (
            "Mathematics builds on logical reasoning, patterns, and quantitative relationships.\n"
            "* Algebra: Uses variables and equations to model unknowns and relationships.\n"
            "* Calculus: Focuses on rates of change (derivatives) and accumulation or area (integrals).\n"
            "* Probability: Measures how likely an event is to occur on a scale from 0 to 1."
        ),
    },
    {
        "keys": ["physics", "force", "velocity", "acceleration", "newton", "energy", "momentum", "current", "ohm", "work"],
        "title": "Physics Basics",
        "body": (
            "Physics explains motion, forces, energy, and matter in the physical world.\n"
            "* Newton's Laws: Force relates to mass and acceleration (F = m * a), and action has an equal and opposite reaction.\n"
            "* Work & Energy: Work transfers energy, which can shift between kinetic, potential, and other forms.\n"
            "* Ohm's Law (V = I * R): Connects voltage (V), electric current (I), and resistance (R)."
        ),
    },
    {
        "keys": ["chemistry", "atom", "molecule", "bond", "acid", "base", "ph", "mole", "reaction", "element"],
        "title": "Chemistry Basics",
        "body": (
            "Chemistry studies the composition, properties, and transformations of matter.\n"
            "* Atoms & Ions: Atoms consist of protons, neutrons, and electrons; gaining or losing electrons forms ions.\n"
            "* Chemical Bonds: Ionic, covalent, and metallic bonds hold atoms together in compounds.\n"
            "* Acids, Bases & pH: Describe proton/ion behavior in solutions and acidity or basicity levels."
        ),
    },
]


def _studysync_guide_response(q_lower: str) -> str | None:
    guide_triggers = [
        "studysync", "study sync", "how to use", "guide", "help",
        "auto-schedule", "auto schedule", "schedule", "slot",
        "pdf", "image", "doc", "resource", "deadline",
        "course", "mark done", "filter", "search", "login", "register",
    ]
    if not any(t in q_lower for t in guide_triggers):
        return None

    return (
        "StudySync Quick Usage Guide:\n"
        "1. Add Courses & Tasks: Create a course with its code and title, then add an exam or assignment with its deadline, priority, and estimated hours.\n"
        "2. Run Smart Auto-Schedule: Click Auto-Schedule Pending Tasks to create study slots before each task's deadline based on priority, configured study windows, and your daily study limit.\n"
        "3. Manage Study Resources: Upload PDFs, images (.png, .jpg, .jpeg, .webp), or docs (.docx, .doc, .txt) up to 5 MB with a custom note title, and search or filter them by task.\n"
        "4. Track Progress: Click Mark Done on completed study slots and update task statuses to monitor your completed hours and task progress."
    )


def generate_assistant_reply(message: str) -> str:
    text = (message or "").strip()
    if not text:
        return "Please enter a question, calculation, or study topic so I can help."

    q_lower = text.lower()

    # 1. Math calculation
    calc_ans = try_calculate(text)
    if calc_ans:
        return calc_ans

    # 2. StudySync app guidelines
    guide_ans = _studysync_guide_response(q_lower)
    if guide_ans:
        return guide_ans

    # 3. Core subject explanations
    for item in _SUBJECT_KNOWLEDGE:
        if any(k in q_lower for k in item["keys"]):
            return f"{item['title']} — Basic Concept:\n{item['body']}"

    # 4. Helpful fallback
    return (
        f"I can help explain '{text}' more clearly if you include a bit more context. Try asking:\n"
        "* StudySync Guide: 'How do I use Auto-Schedule?' or 'How do I upload PDFs and images?'\n"
        "* Calculations: '(85 + 78 + 92) / 3' or '15% of 240'\n"
        "* Subject Concepts: 'What is recursion?', 'Explain Newton's second law', or 'What is pH?'"
    )