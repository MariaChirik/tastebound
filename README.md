# Tastebound

```
services/
  auth/
  catalog/
  order/
  payment/
  tracking/
  notification/
  recommendation/
frontend/
deploy/        # docker-compose.yml, API Gateway (Nginx)
infra/
tests/
docs/
.github/
```

## Локальний запуск

1. Скопіювати `.env.example` у `.env` і задати `AUTH_SECRET_KEY`, `POSTGRES_PASSWORD`
   та `ADMIN_PASSWORD`.
2. `docker compose -f deploy/docker-compose.yml --env-file .env up -d --build`
3. Застосунок: http://localhost:8080, листи-сповіщення: http://localhost:8025

Ролі: клієнт оформлює звичайне або спільне замовлення і платить свою частку, співробітник
ресторану веде меню і готує, кур'єр доставляє, адміністратор підтверджує працівників
і модерує. Опис сервісів - у `docs/architecture.md`.
