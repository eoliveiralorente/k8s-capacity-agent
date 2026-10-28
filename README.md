# Capacity Agent

**Capacidade, custo e risco do seu cluster Kubernetes em uma tela — com aprovação humana antes de qualquer mudança.**

O Capacity Agent analisa nodes, pods e workloads de qualquer cluster Kubernetes (AWS, Azure,
GCP, OCI, OpenStack/SaveInCloud ou on-premises) e entrega:

- **Nota de saúde do cluster** (0–100) com a explicação do que pesou.
- **Prioridades**: pods em CrashLoop, Pending, nodes sob pressão, HPAs no limite.
- **Economia em R$/mês**: rightsizing de requests, réplicas, HPA e pools superdimensionados,
  com base em até 14 dias de histórico.
- **Gate de aprovação**: nenhuma mudança é aplicada sem aprovação; simulação com `--dry-run=server`;
  workloads gerenciados por GitOps viram recomendação manual.
- **Mapa de nodes** clicável: o que roda em cada node, uso real × reservado.
- **Diário de bordo** do time: pendências e notas vinculadas a nodes e recomendações.
- **Assistente IA** opcional (Anthropic, OpenAI, Azure OpenAI ou Ollama interno), somente leitura.
- **Alertas** por Slack, Teams, webhook e e-mail; **relatório executivo** para gestores.
- Multiusuário com papéis (leitor, operador, admin), auditoria completa e licença offline.

## Instalação em 5 minutos (Helm, dentro do cluster)

Requisitos: Kubernetes 1.27+, `helm` 3.8+, metrics-server (`kubectl top nodes` funcionando)
e uma StorageClass padrão.

Grátis e sem token: sem licença, o painel mostra a nota de saúde e o número de riscos. Para ver
os detalhes, as recomendações e os custos, peça a licença de teste de 30 dias no próprio painel.

```bash
helm upgrade --install capacity-agent \
  oci://ghcr.io/eoliveiralorente/charts/capacity-agent --version 1.3.2 \
  --namespace capacity-agent --create-namespace \
  --set clusterName="Produção"

kubectl -n capacity-agent rollout status deploy/capacity-agent
kubectl -n capacity-agent port-forward svc/capacity-agent 8080:80
```

Abra <http://localhost:8080>, clique em **Criar conta** (essa conta vira o administrador) e depois
em **Nova Avaliação**. A instalação padrão é **100% somente leitura**.

Próximos passos: [docs/cliente/INSTALACAO.md](docs/cliente/INSTALACAO.md) (Ingress/TLS, custos,
alertas, IA, licença) · [Segurança](docs/cliente/SEGURANCA.md) ·
[Atualização](docs/cliente/ATUALIZACAO.md) · [Solução de problemas](docs/cliente/SOLUCAO_DE_PROBLEMAS.md).

## Outras formas de instalar

- **Painel central + coletor por cluster** (vários clusters, conexão só de saída):
  [charts/capacity-collector](charts/capacity-collector/README.md).
- **Docker Compose** (avaliação local): [docs/IMPLANTACAO_CLIENTE_TESTE.md](docs/IMPLANTACAO_CLIENTE_TESTE.md).

## Demonstração

Ambiente com empresa e cluster fictícios, para conhecer o produto sem conectar um cluster:
[docs/DEMO.md](docs/DEMO.md).

## Segurança, em resumo

- Imagem sem root, sistema de arquivos somente leitura, sem capabilities.
- Kubeconfigs e segredos criptografados (Fernet); senhas com scrypt.
- Cada release passa por testes automáticos e scan de vulnerabilidades (Trivy).
- Dados ficam no seu ambiente: nenhuma telemetria é enviada ao fornecedor.

## Licença

Software comercial. A edição Community (1 cluster, 2 usuários) é gratuita; recursos como
execução de mudanças, modo agente, alertas e Assistente IA exigem licença.
Contato: [Otera Tech](https://otera-tech-instituti-6nk8.bolt.host/).
