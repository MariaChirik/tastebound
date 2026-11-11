# deploy/

## Docker Compose

```
cp .env.example .env
docker compose -f deploy/docker-compose.yml --env-file .env up -d --build
```

Застосунок: http://localhost:8080, тестова пошта: http://localhost:8025.

## Kubernetes (k3s)

Маніфести лежать у `k8s/`: Namespace, ConfigMap, StatefulSet для PostgreSQL і Redis,
Deployment і Service для кожного сервісу, шлюз Nginx та Ingress. Секрет створюється з `.env`,
у репозиторії є лише приклад `k8s/secret.example.yaml`.

```
k3d cluster create tastebound -p "8081:80@loadbalancer"
kubectl apply -f deploy/k8s/namespace.yaml
kubectl -n tastebound create secret generic tastebound-secrets --from-env-file=.env
kubectl apply -k deploy/k8s
kubectl -n tastebound get pods
```

Застосунок: http://localhost:8081, тестова пошта: http://mail.tastebound.localhost:8081.
