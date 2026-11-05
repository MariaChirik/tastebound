# Архітектура

Система складається з мікросервісів: API Gateway (Nginx), Auth, Catalog, Order, Payment,
Tracking, Notification, Recommendation і Frontend. Дані зберігаються в PostgreSQL, кошики
та позиції кур'єрів - у Redis.

| Сервіс | Ендпоїнти |
| --- | --- |
| Auth | `GET /health`, `POST /register`, `POST /login` |
| Catalog | `GET /health`, `GET /dishes` (фільтри `exclude_allergens`, `diet`) |
| Order | `GET /health`, `POST /orders`, `GET /orders/<id>`, `POST /orders/<id>/cancel` |
