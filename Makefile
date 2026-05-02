lint:
	.\.venv\Scripts\python.exe -m ruff check .

format:
	.\.venv\Scripts\python.exe -m ruff format .

type-check:
	.\.venv\Scripts\python.exe -m mypy .

test:
	.\.venv\Scripts\python.exe -m pytest -v --tb=short

bandit:
	.\.venv\Scripts\python.exe -m bandit -c pyproject.toml -r .

reports:
	.\.venv\Scripts\python.exe -m radon cc -s -a . > docs/reports/complexity.txt
	.\.venv\Scripts\python.exe -m mypy --html-report docs/reports/mypy .
