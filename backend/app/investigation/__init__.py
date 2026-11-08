"""Guided investigation: from a finding, an AI model checks what it can through read-only tools and
suggests where to look next. It never decides a root cause; the person does (docs/investigate.md).

- context.py   what the model is told about the finding, and whether it can be investigated
- tools.py     the read-only checks it may run, with their limits
- loop.py      one round: ask the model, run its checks, stop when a stop rule is met
- service.py   start, continue, stop, mark steps, save to a case; what the API returns
"""
