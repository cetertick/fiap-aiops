# providers.tf
# ---------------------------------------------------------------------------
# Configuracao dos providers AWS, Kubernetes e Helm.
#
# O provider AWS usa as credenciais padrao do ambiente (variaveis de
# ambiente AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_SESSION_TOKEN,
# exportadas a partir do painel "AWS Details" do Learner Lab). Nao
# colocamos credenciais hardcoded aqui - isso e proposital.
#
# Os providers Kubernetes e Helm precisam se autenticar no cluster EKS.
# Usamos o padrao recomendado pela AWS/HashiCorp: um plugin "exec" que
# chama `aws eks get-token` no momento em que o provider precisa falar com
# a API do cluster. Isso evita guardar um token estatico no state e
# funciona bem mesmo quando o token expira entre o `plan` e o `apply`
# (comum em sessoes longas de aula).
#
# Alternativa mais simples (e tambem valida) seria usar o data source
# `aws_eks_cluster_auth`, que gera um token no momento do `plan`/`apply`:
#
#   data "aws_eks_cluster_auth" "this" {
#     name = module.eks... # ou aws_eks_cluster.this.name
#   }
#
# Optamos pelo plugin exec porque o token gerado por ele e sempre "fresco"
# a cada chamada da API, o que e mais robusto durante uma aula de 1h20
# onde o cluster fica em uso por um tempo prolongado.
# ---------------------------------------------------------------------------

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project   = var.project_name
      ManagedBy = "terraform"
      Class     = "fiap-aiops"
    }
  }
}

# Dados do cluster EKS (endpoint e CA) usados para configurar os providers
# kubernetes e helm. Dependem do cluster criado em eks.tf.
data "aws_eks_cluster" "this" {
  name = local.cluster_name

  depends_on = [
    aws_eks_cluster.this
  ]
}

provider "kubernetes" {
  host                   = data.aws_eks_cluster.this.endpoint
  cluster_ca_certificate = base64decode(data.aws_eks_cluster.this.certificate_authority[0].data)

  exec {
    api_version = "client.authentication.k8s.io/v1beta1"
    command     = "aws"
    args        = ["eks", "get-token", "--cluster-name", local.cluster_name, "--region", var.aws_region]
  }
}

provider "helm" {
  kubernetes {
    host                   = data.aws_eks_cluster.this.endpoint
    cluster_ca_certificate = base64decode(data.aws_eks_cluster.this.certificate_authority[0].data)

    exec {
      api_version = "client.authentication.k8s.io/v1beta1"
      command     = "aws"
      args        = ["eks", "get-token", "--cluster-name", local.cluster_name, "--region", var.aws_region]
    }
  }
}
