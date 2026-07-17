# Development Guide

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
