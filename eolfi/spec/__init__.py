"""Especificación de comportamiento sustentada por evidencias (Fase 3)."""
from eolfi.spec.build import build_spec, certainty, diff_specs, latest_spec, review_requirement, spec_tests, store_spec
from eolfi.spec.contract import build_contract, contract_markdown

__all__ = ["build_contract", "build_spec", "certainty", "contract_markdown", "diff_specs", "latest_spec",
           "review_requirement", "spec_tests", "store_spec"]
