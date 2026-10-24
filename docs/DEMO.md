# Ambiente de demonstração

Empresa e cluster **100% fictícios** para prints, vídeos e reuniões. Nunca use
dados de cliente ou de empregador em material de divulgação.

- Empresa: **Nimbus Pay (demo)** · cluster **prod-pagamentos** (modo agente, somente leitura)
- 6 nodes em 3 pools (control-plane, general, memory), ~45 pods em 10 namespaces
- 7 dias de histórico por hora (confiança "alta" nas recomendações)
- Custos de exemplo: R$ 150/vCPU/mês e R$ 20/GB/mês
- Diário de bordo com 2 pendências (uma atrasada) e 1 nota

História que a tela conta:
- nota de saúde ~60 "Atenção";
- 1 pod em CrashLoopBackOff;
- 2 pods Pending por memória;
- HPA no limite;
- pool *general* superdimensionado;
- pool *memory* apertado;
- economia potencial de ~R$ 3.600/mês.

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

Limitação: o cluster demo é do tipo agente, então as recomendações aparecem como
manuais (sem "Aprovar/Executar"). Para gravar o fluxo de aprovação e execução, use o
laboratório kind.
