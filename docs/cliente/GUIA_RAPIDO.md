# Capacity Agent: guia rápido de instalação

**Cliente:** {{CLIENTE}} · **Versão:** {{VERSAO}} · **Licença válida até:** {{VALIDADE}}

O Capacity Agent roda **dentro do seu cluster**, somente leitura. Ele mostra riscos, custo e
desperdício e recomenda ajustes. Nada muda no cluster sem aprovação, simulação e auditoria.
Nenhum dado é enviado ao fornecedor.

## 1. Antes de começar (5 min)

- Kubernetes 1.27+ (qualquer cloud ou on-premises), `kubectl` e `helm` 3.8+ com acesso de admin
  **só durante a instalação**.
- **metrics-server** funcionando: `kubectl top nodes` precisa responder.
- Uma StorageClass que crie volumes (2 GiB). O instalador testa isso antes de instalar.
- O **token de acesso à imagem**, enviado separadamente pelo fornecedor.

## 2. Instalar (5 min)

Descompacte o kit e rode, com o `kubectl` apontando para o cluster certo:

```bash
cd capacity-agent-{{SLUG}}
bash instalar.sh
```

Use `bash instalar.sh`: funciona mesmo se o arquivo perdeu a permissão de execução ao descompactar.

O script verifica o ambiente (acesso, versão, permissões, metrics-server, StorageClass), **testa se o
cluster consegue criar um volume** (cria um de 1 GiB e apaga em seguida), confirma o cluster, pede o token (ele não aparece na tela e não é gravado em arquivo) e instala com helm, ou com
kubectl se você não tiver helm. Se algo falhar, ele mostra o motivo provável e grava um registro
`instalacao-*.log` para enviar ao suporte. Outros scripts do kit: `diagnostico.sh` (coleta
informações sem segredos) e `desinstalar.sh`.

### Se o storage falhar

O instalador para **antes de instalar qualquer coisa** e explica a causa (cota do provedor esgotada,
StorageClass inexistente, driver de storage parado, zona ou permissão). As opções:

| Situação | O que fazer |
|---|---|
| O cluster tem outra StorageClass que funciona | `bash instalar.sh --storage-class=<nome>` (veja as opções com `kubectl get storageclass`) |
| Não há StorageClass padrão | Marque uma como padrão: `kubectl patch storageclass <nome> -p '{"metadata":{"annotations":{"storageclass.kubernetes.io/is-default-class":"true"}}}'` |
| Cota de disco do provedor esgotada | Peça mais cota ao provedor ou use outra StorageClass |
| Só para avaliar, sem storage do provedor | O instalador oferece guardar os dados no disco de um node (local-path). Para aceitar sem pergunta: `bash instalar.sh --storage-local`. Se o node for recriado, o histórico se perde |
| O cluster bloqueia o volume de teste | `bash instalar.sh --pular-teste-storage` |

## 3. Primeiro acesso (5 min)

```bash
kubectl -n capacity-agent port-forward svc/capacity-agent 8080:80
```

Abra `http://localhost:8080` e siga os passos:

1. **Criar conta.** A primeira conta é a de administrador. Depois disso, novos usuários entram por convite.
2. **Usuários e custos → Licença.** Instale o arquivo `{{LICENCA}}`.
3. **Usuários e custos → Custos da infraestrutura.** Cadastre o preço de cada tipo de máquina
   (R$ por hora ou por mês, como na sua fatura) e os custos fixos (taxa do Kubernetes gerenciado,
   load balancers). Os tipos encontrados no cluster aparecem para você só preencher o valor.
4. **Visão Geral → Nova Avaliação.**

Em poucos minutos aparecem a nota de saúde, os riscos e as recomendações. Na tela **Custos** você
vê o custo do mês, a capacidade ociosa e o custo por namespace. A média pelo histórico (que
acompanha o autoscaling) aparece depois de 24 h de coleta.

## 4. Opcional

| O quê | Onde |
|---|---|
| Alertas no Slack, Teams, webhook ou e-mail | Usuários e custos → Alertas |
| Assistente de IA com a IA da sua empresa (Claude, OpenAI, Azure, Gemini, Tess, OpenRouter ou Ollama local, sem dados saindo da empresa) | Assistente IA → Configuração (admin) |
| Acesso por HTTPS, sem port-forward | `--set ingress.enabled=true --set ingress.host=capacity.suaempresa.com.br` |
| Permitir aplicar ajustes **após aprovação** | `rbac.allowRightsizing: true` no `values-{{SLUG}}.yaml` |

## 5. Segurança, em uma frase por item

- **Permissões:** leitura de nodes, pods, eventos, workloads, HPAs e métricas. Escrita só se você
  ligar `allowRightsizing`, e sempre depois de aprovação.
- **Dados:** ficam no volume do seu cluster. Segredos são cifrados, e a licença é validada offline.
- **Licença:** avisa 30 dias antes de vencer e tem 14 dias de carência. Depois disso o painel mostra só a visão
  geral até a renovação; nenhum dado é perdido.
- **IA:** desligada até um admin configurar. Antes de qualquer envio, tokens, senhas, IPs e
  e-mails são mascarados, e a IA nunca executa nada.
- **Contêiner:** sem root, sistema de arquivos somente leitura e sem capabilities.

## 6. Para remover

```bash
bash desinstalar.sh
```

## Suporte

Pelo WhatsApp do fornecedor. Para um diagnóstico rápido, envie o pacote gerado em
**Suporte → Baixar pacote de suporte**: ele não inclui logs de aplicações, senhas nem chaves.
