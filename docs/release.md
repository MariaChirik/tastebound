# Реліз і відкіт

## Реліз

Реліз запускається тегом на main:

```
git tag v1.0.0
git push origin v1.0.0
```

Workflow Release збирає образи з цим тегом, чекає підтвердження в середовищі `production` (Settings, Environments, Required reviewers) і оновлює Kubernetes. Для розгортання в кластері потрібен секрет `KUBE_CONFIG` (kubeconfig у base64); без нього крок розгортання пропускається.

## Відкіт

Історія версій і повернення попередньої:

```
kubectl -n tastebound rollout history deployment/order
kubectl -n tastebound rollout undo deployment/order
kubectl -n tastebound rollout status deployment/order
```

Повернення конкретної версії з історії:

```
kubectl -n tastebound rollout undo deployment/order --to-revision=2
```
