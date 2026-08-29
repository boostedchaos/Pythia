"""Adapter registry. Each module obeys docs/phase-0.5-contract.md.

Every source here was called for real before adoption; the evidence, the terms
verdict and the rejected candidates are in docs/feed-verification.md.
"""
from . import (
    arxiv,
    cisa_kev,
    coingecko,
    federal_register,
    gdelt,
    openai_news,
    openfda,
    state_dept_advisories,
    treasury_yields,
)

ADAPTERS: list = [
    # ai
    arxiv,
    openai_news,
    # cybersecurity
    cisa_kev,
    # politics
    gdelt,
    state_dept_advisories,
    # healthcare
    federal_register,
    openfda,
    # markets
    coingecko,
    treasury_yields,
]

__all__ = ["ADAPTERS"]
