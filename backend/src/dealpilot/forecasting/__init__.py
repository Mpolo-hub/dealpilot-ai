"""Forecasting baselines and evaluation building blocks (spec 003).

Implemented so far (tranche 1): the time split, series building, seasonal naive and naive,
the section 7 metrics and the section 8 gate verdict. Also the O2 clean-tree controller
(`cleantree`, with the strict index reader `gitindex`, spec 003 section 13.3); it needs the
optional `formal` extra (pygit2, internal use only) and is not yet validated by AC-FC-26.
The run harness, results record, holdout log and formal runs are not implemented; formal
runs stay refused while O2 is open (spec 003 section 9.5).
"""
