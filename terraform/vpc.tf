# vpc.tf
# ---------------------------------------------------------------------------
# VPC dedicada ao cluster EKS, usando o modulo oficial da comunidade
# terraform-aws-modules/vpc/aws. Criamos 2 subnets publicas e 2 privadas
# em 2 AZs distintas, com um unico NAT Gateway (em vez de um por AZ) para
# economizar Elastic IPs - o Academy frequentemente limita o numero de
# EIPs disponiveis por conta.
#
# As tags de subnet abaixo sao OBRIGATORIAS para:
#   - O EKS/VPC CNI descobrir em quais subnets colocar ENIs de pods.
#   - O AWS Load Balancer Controller descobrir automaticamente em quais
#     subnets criar ALBs (subnets publicas) e NLBs/ALBs internos
#     (subnets privadas), via as tags kubernetes.io/role/elb e
#     kubernetes.io/role/internal-elb.
# ---------------------------------------------------------------------------

data "aws_availability_zones" "available" {
  state = "available"
}

module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.8"

  name = "${var.project_name}-vpc"
  cidr = var.vpc_cidr

  # Usa as 2 primeiras AZs disponiveis na regiao para manter o cluster
  # simples e rapido de provisionar durante a aula.
  azs = slice(data.aws_availability_zones.available.names, 0, 2)

  public_subnets  = [cidrsubnet(var.vpc_cidr, 4, 0), cidrsubnet(var.vpc_cidr, 4, 1)]
  private_subnets = [cidrsubnet(var.vpc_cidr, 4, 2), cidrsubnet(var.vpc_cidr, 4, 3)]

  # Um unico NAT Gateway compartilhado entre as subnets privadas.
  # Reduz custo e numero de Elastic IPs usados (importante no Academy).
  enable_nat_gateway = true
  single_nat_gateway = true

  enable_dns_hostnames = true
  enable_dns_support   = true

  # Tag generica exigida pelo EKS para que o control plane e o VPC CNI
  # reconhecam a VPC/subnets como pertencentes ao cluster.
  # "shared" = a subnet pode ser usada por mais de um cluster.
  public_subnet_tags = {
    "kubernetes.io/cluster/${local.cluster_name}" = "shared"
    # Exigida pelo AWS Load Balancer Controller para localizar subnets
    # publicas onde criar ALBs "internet-facing" (ex.: Ingress do ArgoCD).
    "kubernetes.io/role/elb" = "1"
  }

  private_subnet_tags = {
    "kubernetes.io/cluster/${local.cluster_name}" = "shared"
    # Exigida pelo AWS Load Balancer Controller para localizar subnets
    # privadas onde criar ALBs/NLBs internos.
    "kubernetes.io/role/internal-elb" = "1"
  }

  tags = local.common_tags
}
