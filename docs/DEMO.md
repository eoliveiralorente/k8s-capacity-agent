# Ambiente de demonstração

Empresa e cluster **100% fictícios** para prints, vídeos e reuniões. Nunca use
dados de cliente ou de empregador em material de divulgação.

- Empresa: **Nimbus Pay (demo)** · cluster **prod-pagamentos** (modo agente, somente leitura)
- 6 nodes em 3 pools (control-plane, general, memory), ~45 pods em 10 namespaces
- 7 dias de histórico por hora (confiança "alta" nas recomendações)
- Tabela de preços fictícia por tipo de máquina: std-4x8 R$ 0,38/h, std-8x32 R$ 0,95/h,
  mem-8x64 R$ 1,40/h, mais custos fixos (Kubernetes gerenciado, 2 load balancers, volumes)
- Diário de bordo com 2 pendências (uma atrasada) e 1 nota

História que a tela conta:
- nota de saúde ~60 "Atenção";
- 1 pod em CrashLoopBackOff;
- 2 pods Pending por memória;
- HPA no limite;
- pool *general* superdimensionado;
- pool *memory* apertado;
- custo do cluster ~R$ 5.050/mês, com ~R$ 2.300/mês (52%) de capacidade ociosa;
- pool *memory* com autoscaling (2 → 3 nodes no horário comercial): média dos últimos 7 dias ~R$ 5.350/mês;
- economia potencial de ~R$ 1.400/mês (1 node a menos no pool *general* = R$ 693,50/mês).

## Criar ou renovar

Docker (painel local):

```bash
sudo docker compose -p capacity-agent-v2 exec capacity-agent python agent.py demo --password 'Escolha-Uma-Senha'
```

Kubernetes (chart):

```bash
kubectl -n capacity-agent exec deploy/capacity-agent -- python agent.py demo --password 'Escolha-Uma-Senha'
```

Entre com `demo@capacity-agent.local` e a senha escolhida. Rodar de novo refaz o
histórico e a avaliação (a conta e o diário são mantidos). Use `--email` para outra conta.

Fluxo de aprovação: no cluster demo as recomendações ficam executáveis. "Aprovar",
"Simular" e "Executar" funcionam normalmente (com auditoria e mudança de status), mas a
execução é **simulada**: o painel mostra o comando kubectl, a saída e como reverter, e
nada é aplicado em cluster algum. Namespaces protegidos e recomendações de baixa
confiança continuam manuais, como num cluster real. Depois de atualizar o painel, rode
`agent.py demo` de novo para as recomendações saírem executáveis.
