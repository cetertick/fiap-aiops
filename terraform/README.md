# Infraestrutura Terraform - FIAP AIOps Lab

Este modulo provisiona a infraestrutura AWS usada na aula: uma VPC, um
cluster EKS (Kubernetes gerenciado), o AWS Load Balancer Controller e
repositorios ECR opcionais.

## O gotcha mais importante: `LabRole` / AWS Academy Learner Lab

As contas do **AWS Academy Learner Lab** usadas nesta turma **nao permitem
criar roles ou policies IAM novas** (uma Service Control Policy do Academy
bloqueia `iam:CreateRole`, `iam:CreatePolicy`, `iam:AttachRolePolicy`, etc).
Se o Terraform tentar criar uma IAM role do jeito "normal", o `apply` vai
falhar com erro de acesso negado.

Em compensacao, **toda conta do Academy ja vem com uma role pronta chamada
`LabRole`** (e um instance profile `LabInstanceProfile`), com permissoes
amplas o suficiente para EKS, EC2, ELB, ECR, etc.

Por isso, este modulo tem uma variavel `use_lab_role` (default `true`) que:

- **`true` (padrao, usado em aula):** o Terraform faz apenas um *lookup*
  (`data "aws_iam_role" "lab_role"`) da `LabRole` existente e reaproveita o
  ARN dela para a role do cluster EKS, a role dos worker nodes e a
  "role" anotada no service account do AWS Load Balancer Controller (sem
  IRSA/OIDC estrito - ver comentarios em `alb-controller.tf`). **Este e o
  caminho que sera efetivamente usado em sala de aula e o unico que
  precisa funcionar sem erros.**
- **`false` (uso fora do Academy, em conta AWS real):** o Terraform cria
  roles e policies IAM dedicadas, do jeito tradicional recomendado pela
  AWS (incluindo um provider OIDC + IRSA para o ALB Controller). Util como
  referencia/portfolio, mas **nao e o caminho testado para a aula**.

Se por algum motivo a sua conta Academy tiver a role com outro nome,
ajuste a variavel `lab_role_name` (default `"LabRole"`).

## Pre-requisitos

1. Ter uma conta no **AWS Academy Learner Lab** e ter clicado em **"Start
   Lab"** (o laboratorio precisa estar com status verde/running).
2. No painel do Learner Lab, clicar em **"AWS Details"** e copiar as
   credenciais temporarias exibidas em `AWS CLI` (elas mudam a cada
   sessao). Exportar como variaveis de ambiente no terminal onde o
   Terraform sera executado:

   ```bash
   export AWS_ACCESS_KEY_ID="..."
   export AWS_SECRET_ACCESS_KEY="..."
   export AWS_SESSION_TOKEN="..."
   export AWS_DEFAULT_REGION="us-east-1"
   ```

   > Atencao: essas credenciais sao temporarias (STS) e expiram quando a
   > sessao do lab termina (tipicamente ~4h) ou quando o lab e reiniciado.
   > Se o `terraform apply`/`destroy` comecar a falhar com erro de
   > autenticacao/token expirado, volte ao painel do Academy, confirme que
   > o lab ainda esta rodando e reexporte as credenciais atualizadas.

3. Ter instalado: Terraform >= 1.6, AWS CLI v2, kubectl e Helm (o Helm e
   usado pelo provider `helm` para instalar o ALB Controller; nao precisa
   rodar comandos `helm` manualmente).

## Como executar

```bash
cd terraform

# (opcional) copie e ajuste as variaveis
cp terraform.tfvars.example terraform.tfvars

terraform init
terraform plan
terraform apply -auto-approve
```

### Tempo esperado de apply: ~15 minutos

A criacao do cluster EKS (control plane) sozinha leva entre **12 e 18
minutos** - isso e normal e esperado do EKS, nao e um erro do Terraform.
Por isso, este modulo deve ser o **PRIMEIRO comando rodado na aula**: dê o
`terraform apply -auto-approve` e deixe rodando em segundo plano (em um
terminal/aba separado) enquanto o instrutor segue com a parte teorica.

**O que fazer/explicar enquanto o cluster sobe (paralelizavel):**

- Explicar a arquitetura geral do laboratorio (microservicos, ArgoCD,
  observabilidade - Prometheus/Loki/Tempo, o agente de AIOps).
- Explicar o gotcha da `LabRole` (secao acima) - e um otimo momento para
  isso, ja que o Terraform esta, literalmente, usando essa role agora.
- Mostrar o codigo HCL (`eks.tf`, `iam.tf`, `vpc.tf`) e os comentarios
  explicando cada bloco.
- Revisar o pipeline de CI/CD (build/push de imagens para o GHCR) que
  sera usado depois que o cluster estiver pronto - nao depende do cluster
  para ser explicado.
- So depois que o `apply` terminar: gerar o kubeconfig e seguir para o
  deploy do ArgoCD/apps.

## Depois do apply: configurar o kubectl

```bash
aws eks update-kubeconfig --region us-east-1 --name aiops-lab-eks
kubectl get nodes
```

(O comando exato, com a regiao e o nome do cluster corretos, tambem
aparece no output `kubeconfig_command` do Terraform: `terraform output
kubeconfig_command`.)

Confira se os 2 nodes do node group `AIOPS-workers` aparecem com `Ready`:

```bash
kubectl get nodes -L node-group
```

## Destruir ao final da aula

Como o backend de state e **local** (ver explicacao abaixo), destrua a
infraestrutura **antes de encerrar a sessao do Learner Lab** (ou antes que
as credenciais expirem), rodando no mesmo diretorio/maquina onde foi feito
o `apply`:

```bash
terraform destroy -auto-approve
```

Se as credenciais expirarem antes do destroy, reexporte credenciais novas
(mesma conta/lab, ver secao de pre-requisitos) e rode o `destroy`
novamente - os recursos continuam existindo na AWS mesmo que o terminal
tenha sido fechado, so o `terraform.tfstate` local precisa estar
preservado (nao delete a pasta do projeto entre a aula e o destroy!).

## Por que o backend de state e local (nao S3)?

As contas do AWS Academy sao **efemeras**: a cada nova sessao as
credenciais mudam e a conta pode ser reciclada. Nao ha garantia de que um
bucket S3 criado em uma sessao vai estar disponivel/acessivel na proxima,
e o ganho de ter state remoto nao compensa a complexidade extra para uma
aula de 1h20. Por isso o backend padrao e o **local** (arquivo
`terraform.tfstate` no proprio diretorio `terraform/`).

Para uma conta AWS real (fora do Academy), veja o comentario em
`versions.tf` explicando como migrar para um backend S3 com lock via
DynamoDB.

## Estrutura dos arquivos

| Arquivo | Conteudo |
|---|---|
| `versions.tf` | Versao do Terraform e dos providers; nota sobre backend local |
| `providers.tf` | Providers AWS, Kubernetes e Helm (autenticacao via `aws eks get-token`) |
| `variables.tf` | Variaveis de entrada, incluindo `use_lab_role` |
| `locals.tf` | Valores locais compartilhados |
| `iam.tf` | Lookup da `LabRole` (modo Academy) ou criacao de roles dedicadas (modo conta real) |
| `vpc.tf` | VPC, subnets publicas/privadas, NAT gateway, tags de auto-discovery |
| `eks.tf` | Cluster EKS, node group `AIOPS-workers`, addons (vpc-cni, coredns, kube-proxy, ebs-csi-driver) |
| `alb-controller.tf` | Instalacao do AWS Load Balancer Controller via Helm |
| `ecr.tf` | Repositorios ECR opcionais para as imagens dos microservicos |
| `outputs.tf` | Saidas (nome do cluster, comando de kubeconfig, URLs do ECR, etc) |
| `terraform.tfvars.example` | Exemplo de arquivo de variaveis |
