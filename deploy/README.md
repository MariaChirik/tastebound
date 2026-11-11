# deploy/

Локальний запуск усього застосунку (етап 2 плану):

```
cp .env.example .env          # заповніть AUTH_SECRET_KEY і POSTGRES_PASSWORD
docker compose -f deploy/docker-compose.yml --env-file .env up -d --build
```

Застосунок відкривається на http://localhost:8080. Сервіси доступні через шлюз:
`/api/auth/health`, `/api/catalog/health`, `/api/orders/...`, `/api/payments/...` тощо.

Маніфести Kubernetes з'являться в `k8s/` на етапі 3.
