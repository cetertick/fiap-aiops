# outputs.tf
# ---------------------------------------------------------------------------
# Saidas uteis apos o `terraform apply`, especialmente para conectar o
# kubectl/helm ao cluster e para referenciar os repositorios ECR em outras
# partes do laboratorio (pipelines de CI/CD, manifests Kubernetes, etc).
# ---------------------------------------------------------------------------

output "cluster_name" {
  description = "Nome do cluster EKS criado."
  value       = aws_eks_cluster.this.name
}

output "cluster_endpoint" {
  description = "Endpoint da API do cluster EKS."
  value       = aws_eks_cluster.this.endpoint
}

output "region" {
  description = "Regiao AWS usada para os recursos."
  value       = var.aws_region
}

output "kubeconfig_command" {
  description = "Comando para gerar/atualizar o kubeconfig local apontando para o cluster."
  value       = "aws eks update-kubeconfig --region ${var.aws_region} --name ${aws_eks_cluster.this.name}"
}

output "vpc_id" {
  description = "ID da VPC criada para o cluster."
  value       = module.vpc.vpc_id
}

output "ecr_repository_urls" {
  description = "Mapa com as URLs dos repositorios ECR criados (nome -> URL do repositorio)."
  value       = { for name, repo in aws_ecr_repository.services : name => repo.repository_url }
}

output "alb_controller_status" {
  description = "Nota sobre a instalacao do AWS Load Balancer Controller."
  value       = "AWS Load Balancer Controller instalado via Helm no namespace kube-system (release '${helm_release.aws_load_balancer_controller.name}'). Use `kubectl get pods -n kube-system -l app.kubernetes.io/name=aws-load-balancer-controller` para verificar o status, e crie Ingress com `ingressClassName: alb` para provisionar ALBs reais."
}
