## What and why

## How it was tested

- [ ] `cd backend && python -m pytest -q`
- [ ] `cd frontend && npm test && npm run lint && npm run build && npx tsc --noEmit`
- [ ] Screenshots attached for UI changes

## Checklist

- [ ] No credentials, `.env` files, databases, logs or private screenshots are included
- [ ] Normal tests make no real provider calls (live checks are marked and opt-in)
- [ ] Any new provider-calling job prints an estimate, separates dry run from apply, and stops on exhausted quota
- [ ] Documentation updated where behaviour changed
