# Changelog

## v1.3.3 — ajuda dentro do painel

- **Menu Ajuda:** primeiros passos, guia de cada tela, papéis de usuário, glossário (request, limit, p95, confiança,
  uso da CPU reservada…), perguntas frequentes e problemas com solução. Vai junto com a imagem e funciona sem internet.
- **Botão "?" no título de cada tela:** abre a ajuda direto no tópico daquela tela.
- **Busca na ajuda**, que ignora acentos ("licenca" acha "licença").

## v1.3.2 — recomendações só do que é do cliente

- **Componentes do sistema à parte:** recomendações em `kube-system` e namespaces da plataforma (componentes
  que o provedor instala e reverte no upgrade) vão para o grupo "Componentes do sistema (gerenciados pelo
  provedor)", recolhido no fim da lista, com severidade baixa. Não entram no contador do menu, na nota, na
  economia potencial nem nos alertas. A lista de namespaces é configurável em
  `CAPACITY_AGENT_SYSTEM_NAMESPACES` (padrão: kube-system, kube-public, kube-node-lease, calico-system,
  tigera-operator). Namespaces protegidos do cliente, como `monitoring`, continuam no fluxo normal.
- **Requests em sentidos opostos:** quando a CPU desce e a memória sobe (ou o contrário), a recomendação
  aparece em "Ajustar requests (um recurso sobe, outro desce)", não mais em "Aumentar requests".
- "Ajustar requests (sobra)" passa a se chamar "Reduzir requests (sobra)".

## v1.3.1 — Visão Geral mais fiel ao risco

- **Uso da CPU reservada** (antes "Eficiência de CPU"): acima de 100% o card fica amarelo e avisa "acima do
  reservado: risco de disputa de CPU". Os pods estão usando mais do que reservaram, o que é risco, não eficiência.
  Abaixo de 30% avisa que sobra CPU reservada. A nota desconta 10 pontos acima de 100%, como já fazia acima de 90%.
- **Manchete curta:** quando o destaque é uma recomendação, a Visão Geral mostra só o que fazer, sem motivo,
  base e efeitos. O texto completo continua em Recomendações.
- **Recomendação sem histórico não vira alerta:** com confiança baixa ela fica só na lista, aguardando dados. Não
  conta como risco, não vai para a manchete e não dispara Slack, Teams, webhook ou e-mail.
- Texto das recomendações: "1 amostra" no singular e só os recursos que mudam (sem "CPU 20m → 20m").

## Kit de entrega — instalador com teste de storage

Correções que vieram de uma instalação real em cliente:
- **Testa o storage antes de instalar:** cria um volume de 1 GiB e um pod mínimo, espera o volume ficar pronto e
  apaga tudo (inclusive o volume no provedor). Se falhar, nada é instalado e o erro é explicado em português:
  cota esgotada, StorageClass inexistente, tipo de volume inválido, zona, permissão do driver ou driver parado.
- **Opções novas:** `--storage-class=<nome>`, `--storage-local` (dados no disco de um node via local-path, para
  avaliação) e `--pular-teste-storage`. `--help` lista todas.
- **Tentativa anterior com volume pendente:** o volume vazio é recriado com a StorageClass atual.
- Na atualização, com o volume já em uso, o teste de storage é pulado.
- Funciona com `bash instalar.sh`, mesmo se o arquivo perdeu a permissão de execução no download.
- Acha o chart como `.tgz` ou como pasta extraída.

## v1.3.0 — instalação gratuita e pedido de teste no painel

- **Instalação grátis em um comando**, sem token: o chart é publicado como pacote OCI no GHCR a cada release
  (`helm install capacity-agent oci://ghcr.io/eoliveiralorente/charts/capacity-agent`). Sem licença, o
  painel mostra a nota de saúde e o número de riscos.
- **Botão "Pedir teste grátis de 30 dias"** nas telas bloqueadas, na visão geral e na tela de licença. O link
  é configurável no chart (`trialUrl`); vazio esconde o botão.

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
