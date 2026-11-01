"""Forecasting baselines and evaluation harness (spec 003).

Tranche 1: the time split, series building, seasonal naive and naive, the section 7
metrics and the section 8 gate verdict. O2 clean-tree controller (`cleantree`, with the
strict index reader `gitindex`, section 13.3); it needs the optional `formal` extra
(pygit2, internal use only). O2 was closed on 2026-11-01 (D30).

Tranche 2 (2026-11-01): model-visible inputs (`inputs`), forecasting and scoring
(`engine`), the results record (`records`), the decision seed (`seed`), the holdout log
(`holdout_log`) and the harness with its command line (`evaluate`). The command line runs
exploratory backtests only. Formal runs need a candidate model, a commit, a CLEAN result,
a matching decision seed and their own authorization (section 9.5); none has been run.
"""
