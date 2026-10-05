# locals.tf
# ---------------------------------------------------------------------------
# Valores locais compartilhados entre os demais arquivos .tf.
# ---------------------------------------------------------------------------

locals {
  cluster_name = var.cluster_name

  # Tags comuns aplicadas em recursos que nao usam o default_tags do
  # provider (ex.: subnets da VPC, que precisam de tags especificas para
  # auto-discovery do EKS/ALB Controller).
  common_tags = {
    Project   = var.project_name
    ManagedBy = "terraform"
    Class     = "fiap-aiops"
  }
}
