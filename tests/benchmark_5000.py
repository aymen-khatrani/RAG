"""Test de charge facultatif : python tests/benchmark_5000.py

Écrit un PDF synthétique dans benchmark_local, sans toucher à data/input.
Installer requirements-tests.txt avant de l'utiliser. Ce corpus simple n'est pas
représentatif de normes complexes et ne mesure pas la qualité normative.
"""
import sys
import json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline_local import Config, run_pipeline
from create_demo import create_large

if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1] / "benchmark_local"
    (root / "input").mkdir(parents=True, exist_ok=True)
    pdf = root / "input" / "synthetic_5000.pdf"
    if not pdf.exists():
        create_large(pdf, pages=5000)
    run = run_pipeline(Config(root / "input", root / "output", max_pages=None, progress_every=500))
    print((run / "summary.json").read_text(encoding="utf-8"))
