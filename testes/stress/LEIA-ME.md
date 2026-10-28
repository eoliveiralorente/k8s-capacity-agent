# Stress test do cluster k8s-auto (autoscaling) + validação do Capacity Agent

Objetivo: ver como o cluster reage a carga (HPA, criação e remoção de nodes, falta de memória) e conferir
se o Capacity Agent percebe cada situação e recomenda o que deveria.

> **Custo:** cada worker que o autoscaler cria é uma VM cobrada enquanto existir. No fim, rode
> `bash stress.sh parar`, espere o scale-down e depois `bash stress.sh limpar`.
>
> **Uso interno:** o cluster é da conta SaveInCloud. Prints e números deste teste não vão para o site
> nem para materiais públicos.

## 0. Preparar (15 min)

1. No painel, em **k8s-auto → Baixar kubeconfig**, salve como `~/.kube/k8s-auto.yaml` no WSL.
2. Em **Trabalhadores → default-worker → lápis**, anote o **mínimo e o máximo** de workers do grupo.
   Para o teste, um máximo de 3 ou 4 já basta.
3. Num terminal, só para este cluster:
   ```bash
   export KUBECONFIG=~/.kube/k8s-auto.yaml
   cd ~/repo_oficial/k8s-capacity-agent-v2/testes/stress
   bash stress.sh checar
   ```
   O script só roda com um `KUBECONFIG` próprio, e só se todos os nodes começarem com `k8s-auto`.
   Os outros clusters não são tocados.
   Se o `metrics-server` não responder, instale antes de seguir, porque o HPA e o Capacity Agent dependem dele:
   ```bash
   kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml
   ```

## 1. Instalar o Capacity Agent no cluster (20 min)

Aproveite para testar o **kit do cliente com o instalador novo** (teste de storage incluído):

```bash
cd ~/repo_oficial/k8s-capacity-agent-v2
python3 tools/kit_cliente.py --customer "Teste k8s-auto" --version 1.3.2 --pilot
cd entregas/teste-k8s-auto
echo 'sampleMinutes: 5' >> values-teste-k8s-auto.yaml     # amostra a cada 5 min no teste (o padrão é 15)
bash instalar.sh
```

Use um token `read:packages` só para este teste e apague depois. Instale a licença do kit no
painel e cadastre os preços das máquinas em Usuários e custos para ver também os custos.

Abra o painel: `kubectl -n capacity-agent port-forward svc/capacity-agent 8083:80` → http://localhost:8083
(o 8080, 8081 e 8082 já estão em uso). Clique em **Nova Avaliação** e anote a **linha de base**:
nota, riscos e nodes.

## 2. Rodar os cenários

Deixe o monitor gravando num **segundo terminal** (com o mesmo `export KUBECONFIG`) durante tudo:

```bash
bash stress.sh monitorar
```

Rode um cenário por vez, espere o efeito e clique em **Nova Avaliação** no Capacity Agent antes do próximo.

| # | Comando | O que acontece | Tempo | O que observar no cluster | O que o Capacity Agent deve mostrar |
|---|---|---|---|---|---|
| 1 | `bash stress.sh cpu` | php-apache com HPA (1 a 20) + 4 geradores de carga | 15 min | HPA sobe; pods Pending; worker novo | Pods Pending com a causa; HPA perto do máximo; nodes com CPU alta |
| 2 | `bash stress.sh cpu 10` | mais carga | 10 min | HPA no máximo? mais workers? | "HPA no limite"; Uso da CPU reservada alto |
| 3 | `bash stress.sh nodes 2` | pods de 500m/512Mi que exigem cerca de 2 workers a mais | 15 min | **tempo do Pending até o node Ready**; o limite do grupo é respeitado? | Pending por falta de CPU/memória; capacidade e pools |
| 4 | `bash stress.sh parar` | carga zerada | 20 a 30 min | **scale-down**: em quanto tempo os nodes extras somem | Capacidade ociosa enquanto os nodes extras existem; aviso de nodes da licença |
| 5 | `bash stress.sh memoria` | OOMKill em loop + pod com request 64Mi usando ~450M | 20 min | OOMKilled, CrashLoopBackOff; o node aguenta? | **Risco crítico** do CrashLoop; recomendação "aumentar requests" de memória |
| 6 | `bash stress.sh vizinho` | pod sem limit consumindo ~2 CPUs com request de 100m | 20 min | lentidão dos outros pods do node | **Uso da CPU reservada acima de 100%** (correção da 1.3.2); aumentar request de CPU |
| 7 | `bash stress.sh desperdicio` | 3 pods ociosos reservando 700m/1Gi | 1 h ou mais | podem forçar um worker a mais sem uso real | Reduzir requests; ociosidade e economia em Custos |

`bash stress.sh status` mostra a situação a qualquer momento.

Os cenários 5, 6 e 7 podem rodar juntos e ficar algumas horas. As recomendações do Capacity Agent ganham
confiança com o histórico: "média" a partir de 12 amostras (1 h com `sampleMinutes: 5`).

## 3. Encerrar e analisar

```bash
bash stress.sh parar          # espere os workers extras sumirem (o monitor mostra)
bash stress.sh relatorio      # gera relatorio-AAAAMMDD-HHMM.md com tempos e eventos
bash stress.sh limpar         # apaga o namespace stress-test
```

O relatório calcula sozinho:
- workers no início e no pico;
- tempo do primeiro Pending até o primeiro worker novo (scale-up);
- tempo até voltar ao número inicial (scale-down);
- pico de Pending, de réplicas do HPA, de CPU e memória e de OOMKilled;
- os eventos do autoscaler.

Depois, preencha a tabela de pontos bons e ruins.

## O que costuma aparecer (para guiar a análise)

**Cluster**
- *Bom:* scale-up em 3 a 6 min, nodes novos entrando Ready, HPA estável sem oscilar.
- *Ruim:* scale-up acima de 10 min (os usuários sentem); o máximo do grupo baixo deixa pods Pending;
  o scale-down não acontece por causa de pods sem controller, PDB ou volume local; o HPA oscila
  (sobe e desce em sequência); OOM derruba outros pods do node; o node fica NotReady por pressão de memória.
- Pods sem limit (cenário 6) mostram por que limits e requests importam: o vizinho rouba CPU.

**Capacity Agent: anote o que faltou**
- Detectou cada situação? Em quanto tempo depois de acontecer?
- A causa do Pending veio certa (CPU, memória, limite de nodes)?
- A recomendação faz sentido e os números batem com o `kubectl top`?
- O aviso de nodes da licença considerou a média do mês, não o pico?
- O que um SRE gostaria de ver e não viu (por exemplo, a linha do tempo do scale-up)? Isso vira backlog.
