# Development Guide

For a first-time clone - prerequisites, `./scripts/setup.sh`, `./scripts/run_all.sh` - see the
[README Quick Start](../README.md#quick-start). This guide assumes that's already done and covers
running individual pieces by hand (e.g. the backend without the frontend, or vice versa).

## Backend

```bash
python -m intelligence.cli init-db --config config.yaml
python -m intelligence.cli run --config config.yaml
uvicorn backend.app.main:app --reload --port 8000
```

## Frontend

```bash
cd frontend
npm install
npm run dev
```

## Testing

```bash
pytest -q
cd frontend && npm test
```

## Notes

- Keep docs synchronized with implementation changes
- Update YAML examples when config fields change
- Avoid claiming unimplemented behavior in user-facing copy
