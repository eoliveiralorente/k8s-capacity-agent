# Changelog

## Kit de entrega — termos de uso e privacidade

- O kit traz `TERMOS_DE_USO.md` e `PRIVACIDADE.md`. O `instalar.sh` avisa que continuar significa aceitar os
  termos e grava no registro da instalação a data, o usuário e o cluster do aceite.

## v1.2.1 — correção na saúde da instalação

- Suporte → Saúde da instalação: a linha "Licença" mostra AVISO, com o que fazer, quando não há licença,
  quando ela está vencida, inválida, em carência ou a 30 dias ou menos do fim. Antes aparecia OK sem licença.

## v1.2.0 — licença pronta para cobrar

**Planos comerciais**
- Planos `essencial`, `profissional` e `enterprise`, com recursos e limites padrão (`licensing/core.py`).
  O painel mostra o nome comercial do plano. Licenças `pro` antigas continuam valendo.
- `license_tool.py` e `kit_cliente.py` aceitam só `--plan`; `--clusters`, `--users`, `--nodes` e `--features` são opcionais.

**Sem licença válida, só a visão geral**
- Sem licença, com licença inválida ou vencida após os 14 dias de carência, o painel mostra só a nota de saúde e o
  número de riscos. Recomendações, nodes, pods, capacidade, custos e relatório pedem licença (HTTP 402).
- Os dados continuam sendo coletados e voltam assim que a licença é instalada. O pacote e o cluster de
  demonstração não são afetados.

**Limite de nodes como aviso**
- Campo opcional `max_nodes` na licença. A tela de licença mostra a média de nodes dos últimos 30 dias (todos os
  clusters, acompanhando o autoscaling), o total atual e o pico, com aviso quando a média passa do contratado.
  Não bloqueia nada: serve de base para ajustar o plano na renovação.

**Painel**
- Botões de "Instalar licença" e "Gerar link de convite" com tamanho normal, numa linha de ações com uma dica.
- Listas de seleção dos formulários com o mesmo visual dos outros campos.

**Instalação e atualização**
- O `instalar.sh` reconhece uma instalação existente e pergunta "Atualizar da versão X para a Y?". Não pede
  o token de novo e mantém dados e licença.
- O kit traz `ATUALIZACAO.md` (atualizar, voltar versão, backup e restauração) e `NOVIDADES.md`.
- Ensaio de instalação para o fornecedor: `tools/ensaio_kind.sh` e `docs/ENSAIO_INSTALACAO.md`.

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
