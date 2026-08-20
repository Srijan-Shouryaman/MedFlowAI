from pathlib import Path

# Keep production layout under services/clinical-nlp while allowing normal
# Python imports in tests and orchestration code.
__path__ = [
    str(Path(__file__).resolve().parents[2] / "clinical-nlp" / "app")
]
