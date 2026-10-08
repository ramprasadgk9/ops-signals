"""Finding trust: how often each kind of finding turned out to be real, measured on public data.

    .venv/bin/python -m benchmark.finding_trust.run

Every finding a user sees will carry "findings like this were real X% of the time (n checked)".
This package measures X per finding group - type, whether 2+ analyzers agreed, importance band -
on datasets whose incidents were marked by outside researchers (NAB, RCAEval). See run.py.
"""
