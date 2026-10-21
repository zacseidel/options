"""Read-only research: event studies that pick thresholds for new categories (PLAN-signals §2.5).

Each module writes `docs/research/NN-<topic>.md` and `data/research/<topic>.json` and never touches
the strategy tables. Thresholds are chosen on the in-sample part of the history; the out-of-sample
part is reported next to it.
"""
