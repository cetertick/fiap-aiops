# versions.tf
# ---------------------------------------------------------------------------
# Define a versao minima do Terraform e os providers usados no modulo, com
# as versoes "pinadas" (fixadas em faixas conhecidas) para garantir builds
# reproduziveis durante a aula.
# ---------------------------------------------------------------------------

terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }

    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.0"
    }

    helm = {
      source  = "hashicorp/helm"
      version = "~> 2.0"
    }
  }

  # -------------------------------------------------------------------------
  # Backend: LOCAL (padrao) de propósito.
  #
  # Por que local e nao S3?
  # As contas do AWS Academy Learner Lab sao efemeras: a cada nova sessao
  # ("Start Lab") as credenciais (AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY /
  # AWS_SESSION_TOKEN) mudam e a conta pode ser reciclada/zerada. Nao existe
  # garantia de que um bucket S3 criado em uma sessao vai persistir ou estar
  # acessivel na sessao seguinte, e manter state remoto em uma conta que
  # "desaparece" em ~4h nao traz beneficio real para uma aula de 1h20.
  #
  # Para uma conta AWS "de verdade" (fora do Academy), migre para um backend
  # S3 (+ DynamoDB para lock) assim:
  #
  # backend "s3" {
  #   bucket         = "meu-bucket-de-tfstate"
  #   key            = "fiap-aiops/terraform.tfstate"
  #   region         = "us-east-1"
  #   dynamodb_table = "terraform-locks"
  #   encrypt        = true
  # }
  #
  # Como o backend nao aceita variaveis, troque manualmente os valores acima
  # e rode `terraform init -migrate-state` quando for usar uma conta real.
  # backend "local" {} # (comportamento padrao do Terraform; bloco omitido)
}
