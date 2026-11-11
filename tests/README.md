# tests/

Unit-тести кожного сервісу лежать поруч із кодом: `services/<сервіс>/tests/`, тести фронтенду -
у `frontend/tests/`. Тут лежать API-тести: колекція Postman і оточення для неї.

- `postman/tastebound.postman_collection.json` - стан сервісів, реєстрація і права доступу,
  каталог із фільтром алергенів, спільне замовлення з оплатою часток, скасування з поверненням
  коштів, оцінки та рекомендації.
- `postman/local.postman_environment.json` - для запуску з Postman на http://localhost:8080.
- `postman/ci.postman_environment.json` - для запуску Newman у мережі Docker Compose.

Запуск Newman проти застосунку, піднятого через Docker Compose:

```
docker run --rm --network tastebound_frontend -v "$PWD/tests/postman:/etc/newman" \
  postman/newman:6-alpine run tastebound.postman_collection.json -e ci.postman_environment.json
```
