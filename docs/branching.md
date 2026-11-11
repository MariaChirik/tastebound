# Гілки та перевірки

## Гілки
- `main` - стабільна версія, змінюється лише через pull request.
- `develop` - інтеграційна гілка.
- `feature/<назва>` - гілка для окремої задачі.

## Захист main
- Require a pull request before merging (Required approvals = 0).
- Require status checks to pass: `lint`, `test (auth)`, `test (catalog)`, `test (order)`, `test (payment)`, `test (tracking)`, `test (notification)`, `test (recommendation)`, `test (frontend)`, `docker build (...)` для кожного образу, `compose config`, `secrets-scan`.
- Block force pushes.

## CI (.github/workflows/ci.yml)
| Завдання | Інструмент |
| --- | --- |
| lint | flake8 |
| test (auth / catalog / order) | PyTest |
| docker build | Docker (збірка образів кожного сервісу і фронтенду) |
| compose config | Docker Compose (перевірка deploy/docker-compose.yml) |
| secrets-scan | gitleaks |
- Назви гілок для задач: feature/назва-задачі.
