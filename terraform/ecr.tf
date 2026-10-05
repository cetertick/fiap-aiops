# ecr.tf
# ---------------------------------------------------------------------------
# Repositorios ECR (Elastic Container Registry) para as imagens dos
# microservicos do laboratorio.
#
# IMPORTANTE: o fluxo PADRAO de CI/CD deste repositorio publica as imagens
# no GitHub Container Registry (ghcr.io), nao no ECR. Isso evita o
# incomodo de credenciais STS do AWS Academy (que expiram/rotacionam a
# cada sessao) dentro do GitHub Actions, o que tornaria o pipeline fragil
# entre uma aula e outra.
#
# Estes repositorios ECR sao providos como um CAMINHO ALTERNATIVO/OPCIONAL
# para equipes que preferirem um registry nativo da AWS (por exemplo, para
# explorar integracao com ECR scanning, replicacao entre regioes, etc).
# Eles NAO sao necessarios para o fluxo padrao da aula.
# ---------------------------------------------------------------------------

locals {
  ecr_repositories = [
    "fiap-aiops-orders-api",
    "fiap-aiops-payments-api",
    "fiap-aiops-inventory-api",
    "fiap-aiops-aiops-agent",
    "fiap-aiops-postmortem-service",
  ]
}

resource "aws_ecr_repository" "services" {
  for_each = toset(local.ecr_repositories)

  name = each.value

  # Faz scan de vulnerabilidades automaticamente a cada push de imagem.
  image_scanning_configuration {
    scan_on_push = true
  }

  image_tag_mutability = "MUTABLE"

  tags = merge(local.common_tags, {
    Name = each.value
  })
}

# Mantem apenas as 10 imagens mais recentes de cada repositorio, para nao
# acumular imagens antigas indefinidamente (relevante mesmo em conta
# efemera do Academy, caso o repo seja reaproveitado em varias turmas).
resource "aws_ecr_lifecycle_policy" "services" {
  for_each = aws_ecr_repository.services

  repository = each.value.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Mantem apenas as 10 imagens mais recentes"
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = 10
        }
        action = {
          type = "expire"
        }
      }
    ]
  })
}
