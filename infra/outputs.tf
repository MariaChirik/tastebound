output "public_ip" {
  value = aws_eip.k3s.public_ip
}

output "ssh_command" {
  value = "ssh ubuntu@${aws_eip.k3s.public_ip}"
}

output "kubeconfig_command" {
  value = "scp ubuntu@${aws_eip.k3s.public_ip}:/etc/rancher/k3s/k3s.yaml ./kubeconfig"
}
