# Changelog

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
- Cabeçalhos de segurança (CSP, HSTS, X-Frame-Options), imagem sem root, kubectl fixado.
- Ambiente de demonstração com dados fictícios (`agent.py demo`).
