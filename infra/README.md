# infra/

Сервер для Kubernetes-кластера (k3s) в AWS: мережа VPC, підмережа, інтернет-шлюз, брандмауер
(security group), віртуальна машина EC2, окремий диск для даних кластера і статична IP-адреса.
k3s встановлюється під час першого запуску сервера скриптом `k3s-install.sh`.

```
cp terraform.tfvars.example terraform.tfvars
terraform init
terraform validate
terraform plan
```
