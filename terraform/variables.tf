# variables.tf
# ---------------------------------------------------------------------------
# Variaveis de entrada do modulo. Os defaults foram escolhidos para
# funcionar "out of the box" em uma conta AWS Academy Learner Lab, com
# instancias modestas (ha limites de vCPU/tipo de instancia no Academy).
# ---------------------------------------------------------------------------

variable "project_name" {
  description = "Nome do projeto, usado como prefixo/tag em todos os recursos."
  type        = string
  default     = "aiops-lab"
}

variable "aws_region" {
  description = "Regiao AWS onde os recursos serao criados. us-east-1 e a regiao mais comumente disponivel em contas AWS Academy."
  type        = string
  default     = "us-east-1"
}

variable "vpc_cidr" {
  description = "Bloco CIDR da VPC criada para o cluster EKS."
  type        = string
  default     = "10.0.0.0/16"
}

variable "cluster_name" {
  description = "Nome do cluster EKS. Usado nas tags de subnet para auto-discovery do ALB Controller e no kubeconfig."
  type        = string
  default     = "aiops-lab-eks"
}

variable "cluster_version" {
  description = "Versao do Kubernetes/EKS. Mantida em uma versao estavel e amplamente suportada pelos modulos usados."
  type        = string
  default     = "1.30"
}

variable "node_instance_type" {
  description = "Tipo de instancia EC2 para os worker nodes do EKS. t3.medium e suficiente para a carga da aula (ArgoCD, apps de exemplo, stack de observabilidade) e respeita os limites de instancia do AWS Academy."
  type        = string
  default     = "t3.medium"
}

variable "node_desired_size" {
  description = "Numero desejado de worker nodes no managed node group."
  type        = number
  default     = 2
}

variable "node_min_size" {
  description = "Numero minimo de worker nodes no managed node group."
  type        = number
  default     = 2
}

variable "node_max_size" {
  description = "Numero maximo de worker nodes no managed node group (permite algum scale-out pontual durante a aula)."
  type        = number
  default     = 4
}

# ---------------------------------------------------------------------------
# *** O GOTCHA MAIS IMPORTANTE DESTA AULA ***
#
# Contas do AWS Academy Learner Lab tem uma Service Control Policy (SCP)
# que BLOQUEIA a criacao de roles/policies IAM (iam:CreateRole,
# iam:CreatePolicy, iam:AttachRolePolicy, etc). Ou seja, Terraform NAO
# consegue criar roles IAM dedicadas para o cluster EKS, para os node
# groups ou para IRSA (IAM Roles for Service Accounts).
#
# Em compensacao, toda conta do Academy ja vem com uma role pre-existente
# chamada "LabRole" (e um instance profile "LabInstanceProfile") com
# permissoes amplas, suficientes para EKS, EC2, ELB, ECR etc.
#
# Por isso, quando `use_lab_role = true` (o padrao, usado em sala de aula),
# o modulo usa `data "aws_iam_role" "lab_role"` (ver iam.tf) para localizar
# a LabRole existente e reaproveitar o ARN dela para:
#   1) a service role do cluster EKS;
#   2) a role do managed node group;
#   3) a "role" do service account do AWS Load Balancer Controller
#      (sem IRSA/OIDC trust policy estrita - ver alb-controller.tf).
#
# Quando `use_lab_role = false` (uso em uma conta AWS real, fora do
# Academy, para fins de portfolio), o modulo cria roles e policies IAM
# dedicadas do jeito tradicional/recomendado pela AWS.
#
# O caminho `use_lab_role = true` e o que sera efetivamente usado em aula
# e, portanto, o caminho testado e garantido funcionar.
# ---------------------------------------------------------------------------
variable "use_lab_role" {
  description = "Se true (padrao, modo AWS Academy), reaproveita a LabRole existente para EKS/nodes/ALB Controller em vez de criar roles IAM novas (que sao bloqueadas pela SCP do Academy). Se false, cria roles IAM dedicadas (modo 'conta AWS real')."
  type        = bool
  default     = true
}

variable "lab_role_name" {
  description = "Nome da role pre-existente no AWS Academy Learner Lab (normalmente 'LabRole')."
  type        = string
  default     = "LabRole"
}
