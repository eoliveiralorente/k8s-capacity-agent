# Changelog

## v1.1.0 — custo do cluster por node

**Custos** (nova tela "Custos"; o card "Economia potencial" da Visão Geral leva até ela)
- Tabela de preços por tipo de máquina (instance-type, node pool, nome do node ou `*`), em R$/hora ou R$/mês.
- Custo de cada node rateado para os workloads pelos requests; capacidade ociosa em R$ e %.
- Custo por namespace e por node pool; custos fixos do cluster (Kubernetes gerenciado, load balancers, volumes).
- Economia de "reduzir pool" usa o preço real de 1 node; rightsizing usa o R$/vCPU e R$/GB efetivos dos nodes.
- Preço por hora × 730 h/mês; média de nodes pelo histórico (acompanha autoscaling) e gasto real dos últimos 7 dias.
- R$/vCPU e R$/GB continuam como preço de referência para nodes sem preço (marcado como aproximado).

**Entrega e demonstração**
- Kit de entrega por cliente (`tools/kit_cliente.py`): licença, chart, values, `instalar.sh` e guia rápido de uma página.
- Pacote de demonstração local (`tools/pacote_demo.sh`): Docker, dados fictícios, sem cluster e sem token;
  modo `CAPACITY_AGENT_DEMO_ONLY` bloqueia clusters reais e licença e mostra uma faixa de demonstração.

**Auditoria e Assistente IA**
- Log de auditoria em frases legíveis, com ícone por ação e detalhes técnicos sob demanda.
- Provedor Tess AI; contexto do cluster ativo enviado junto da pergunta; conversa recomeça ao trocar de cluster.

## v1.0.0 — primeira versão comercial

**Visão executiva**
- Nota de saúde (0–100) com manchete, KPIs (riscos, economia, eficiência de CPU, disponibilidade).
- Prioridades agora, maiores economias e pendências abertas na Visão Geral.
- Mapa de capacidade por node com uso real × reservado e detalhe de pods por node.

**Recomendações**
- Rightsizing de requests por container com histórico e nível de confiança.
- Réplicas e HPA: aumentar/reduzir réplicas, criar HPA, ajustar maxReplicas.
- Pools subutilizados e causas de pods Pending (memória, CPU, PVC, taints, afinidade).
- Estimativa de economia em R$/mês por recomendação; agrupamento por tipo e impacto.
- Gate de aprovação, simulação `--dry-run=server` e execução auditada; GitOps vira manual.

**Operação**
- Diário de bordo: pendências (responsável, prazo, status) e notas, vinculadas a nodes e recomendações.
- Alertas por Slack, Teams, webhook e e-mail, com deduplicação e lembretes.
- Assistente IA somente leitura (Anthropic, OpenAI, Azure OpenAI, Ollama) com cota diária.
- Relatório executivo para gestores.

**Plataforma**
- Qualquer cloud ou on-premises; detecção de node pools por provedor.
- Três modos: self-hosted no cluster (Helm), painel central + coletor (somente saída) e kubeconfig.
- Multiusuário com convites, papéis e auditoria; licença offline Ed25519; pacote de suporte sem segredos.
- Cabeçalhos de segurança (CSP, HSTS, X-Frame-Options), imagem sem root, kubectl no último patch estável a cada build.
- Ambiente de demonstração com dados fictícios (`agent.py demo`).
