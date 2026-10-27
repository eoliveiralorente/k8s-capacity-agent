# Ensaio de instalação (antes de divulgar)

Uso interno. Objetivo: instalar, atualizar e bloquear a licença do jeito que o cliente vai fazer, num
cluster limpo, antes que o primeiro cliente encontre um problema. Leva cerca de 40 minutos.

O ensaio usa um cluster kind separado (`capacity-ensaio`, kubeconfig `~/.kube/kind-ensaio.yaml`).
Ele não toca no laboratório, na produção nem no contexto padrão do kubectl.

## 0. Publicar a versão 1.2.0

```bash
cd ~/repo_oficial/k8s-capacity-agent-v2
git add -A
git commit -m "v1.2.0: planos comerciais, painel restrito sem licença, aviso de nodes e guia de atualização"
git tag v1.2.0
git push origin main --tags
```

Acompanhe em **GitHub → Actions → Release** (testes, Trivy e publicação, cerca de 10 minutos). Quando
ficar verde, confira que a imagem baixa com o token de cliente:

```bash
echo '<TOKEN>' | docker login ghcr.io -u eoliveiralorente --password-stdin
docker pull ghcr.io/eoliveiralorente/k8s-capacity-agent:1.2.0
docker logout ghcr.io
```

## 1. Criar o cluster limpo

```bash
tools/ensaio_kind.sh criar
export KUBECONFIG=~/.kube/kind-ensaio.yaml
kubectl config current-context        # tem que ser kind-capacity-ensaio
```

## 2. Instalar a versão anterior, como um cliente que já existe

```bash
python3 tools/kit_cliente.py --customer "Ensaio" --version 1.1.0 --pilot --registry-user eoliveiralorente --force
mkdir -p ~/ensaio && cd ~/ensaio && rm -rf capacity-agent-ensaio
unzip -q ~/repo_oficial/k8s-capacity-agent-v2/entregas/capacity-agent-ensaio-1.1.0.zip
cd capacity-agent-ensaio && ./instalar.sh
```

Cole o token quando pedir. Depois:

```bash
kubectl -n capacity-agent port-forward svc/capacity-agent 8090:80
```

Abra `http://localhost:8090` (porta 8090 para não conflitar com o laboratório), crie a conta, instale
`ensaio.license.json`, cadastre um preço de máquina e clique em **Nova Avaliação**.

## 3. Atualizar para a 1.2.0 com o kit novo

```bash
cd ~/repo_oficial/k8s-capacity-agent-v2
python3 tools/kit_cliente.py --customer "Ensaio" --version 1.2.0 --pilot --registry-user eoliveiralorente --force
cd ~/ensaio && rm -rf capacity-agent-ensaio
unzip -q ~/repo_oficial/k8s-capacity-agent-v2/entregas/capacity-agent-ensaio-1.2.0.zip
cd capacity-agent-ensaio && ./instalar.sh
```

O instalador deve dizer *"Já existe um Capacity Agent neste namespace (versão 1.1.0)"* e perguntar se
quer atualizar. Ele **não** deve pedir o token.

## 4. Testar a licença

```bash
cd ~/repo_oficial/k8s-capacity-agent-v2
python3 tools/license_tool.py issue --customer "Ensaio vencido" --plan essencial --days -20 -o ~/ensaio/vencida.license.json
python3 tools/license_tool.py issue --customer "Ensaio" --plan profissional --days 30 -o ~/ensaio/valida.license.json
```

Instale `vencida.license.json` no painel: só a visão geral deve ficar aberta, com cadeado nas outras
telas. Depois instale `valida.license.json`: tudo deve liberar na hora.

## 5. Suporte e remoção

```bash
cd ~/ensaio/capacity-agent-ensaio
./diagnostico.sh
./desinstalar.sh
```

## 6. Apagar o ensaio

```bash
unset KUBECONFIG
cd ~/repo_oficial/k8s-capacity-agent-v2 && tools/ensaio_kind.sh apagar
```

## Checklist do ensaio

| # | O que conferir | Resultado |
|---|---|---|
| 1 | Release v1.2.0 verde no GitHub Actions e `docker pull` com o token de cliente funciona | |
| 2 | Verificação do ambiente (1/5) sem nenhum ✘ | |
| 3 | Token colado sem aparecer na tela e sem ficar no `instalacao-*.log` | |
| 4 | Painel abre, conta criada, licença do piloto instalada | |
| 5 | Primeira avaliação com nota, riscos e mapa de nodes | |
| 6 | Atualização para 1.2.0 sem pedir token, com dados e licença mantidos | |
| 7 | Tela de licença mostra a linha "Nodes" | |
| 8 | Licença vencida: só visão geral; licença válida: tudo libera na hora | |
| 9 | Botões "Instalar licença" e "Gerar link de convite" com tamanho normal | |
| 10 | `diagnostico.sh` gera o arquivo, sem token nem segredos | |
| 11 | `desinstalar.sh` remove tudo | |

Qualquer item que falhar: anote a mensagem exata e o passo, e corrija antes do primeiro cliente.
