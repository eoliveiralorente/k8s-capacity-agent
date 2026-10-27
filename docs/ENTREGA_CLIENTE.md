# Entrega para um cliente (procedimento do fornecedor)

Uso interno. Para cada cliente novo (piloto ou contrato), siga estes passos.

## Uma vez só: conta-robô para leitura da imagem

A imagem `ghcr.io/eoliveiralorente/k8s-capacity-agent` é privada. O cliente baixa a imagem com um
token **só de leitura**. Para não usar um token da sua conta pessoal (que enxerga todos os seus
pacotes e repositórios), crie uma conta-robô:

1. Crie uma conta no GitHub para o robô, por exemplo `capacity-agent-bot`, com um e-mail seu e 2FA ligado.
2. Na sua conta, abra o pacote `k8s-capacity-agent` → **Package settings → Manage access** →
   adicione `capacity-agent-bot` com permissão **Read**.
3. O robô só enxerga esse pacote, mais nada.

## Por cliente

### 1. Token de leitura (2 min)

Logado como `capacity-agent-bot`: **Settings → Developer settings → Personal access tokens →
Tokens (classic) → Generate new token**.

- **Note:** `cliente-<nome>-<ano>`, por exemplo `cliente-empresa-x-2026`
- **Expiration:** fim do piloto mais 15 dias, ou fim do contrato
- **Scope:** apenas `read:packages`

Um token por cliente: se um cliente sair, você revoga só o dele.

### 2. Kit (1 min)

```bash
# Piloto: enterprise, 1 cluster, 5 usuários, 30 dias
python3 tools/kit_cliente.py --customer "Empresa X" --version 1.2.1 --pilot

# Contrato: o plano define recursos e limites (use --days 30 para mensal)
python3 tools/kit_cliente.py --customer "Empresa X" --version 1.2.1 --plan essencial --days 365
python3 tools/kit_cliente.py --customer "Empresa X" --version 1.2.1 --plan profissional --days 365
python3 tools/kit_cliente.py --customer "Empresa X" --version 1.2.1 --plan enterprise \
  --clusters 6 --users 50 --nodes 150 --days 365
```

| Plano | Clusters | Usuários | Nodes (aviso) | Recursos |
|---|---|---|---|---|
| essencial | 1 | 10 | 20 | aprovação e execução |
| profissional | 3 | 25 | 60 | + alertas e assistente de IA |
| enterprise | sob proposta (padrão 10) | sob proposta (padrão 100) | sob proposta | + modo agente |

O limite de nodes é a média do mês e só gera aviso no painel. Confira na renovação, na tela de licença do cliente
ou no pacote de suporte, e ajuste o plano se o uso passou do contratado.

Sem licença válida (vencida há mais de 14 dias), o painel do cliente mostra só a nota de saúde e o número de
riscos. Os dados continuam guardados e voltam assim que a licença nova é instalada.

O comando gera `entregas/<cliente>/` e `entregas/capacity-agent-<cliente>-<versão>.zip` com a licença, o chart,
o `values`, o `instalar.sh` e o `GUIA_RAPIDO.md` preenchido. A pasta `entregas/` fica fora do Git.

A licença é assinada com a chave privada em `~/.capacity-license/private.pem`, que nunca entra no repositório.
Confira com `python3 tools/license_tool.py verify entregas/<cliente>/<cliente>.license.json`.

### 3. Envio

- **E-mail:** o `.zip`.
- **WhatsApp (outro canal):** o token, com a mensagem "Cole este token quando o instalar.sh pedir. Ele só permite baixar a imagem."
- Ofereça 30 min de instalação acompanhada por chamada. A instalação leva cerca de 15 min.

### 4. Acompanhamento do piloto

| Quando | O quê |
|---|---|
| Dia 1 | Instalação, cadastro de preços, primeira avaliação |
| Dia 7 | Reunião de diagnóstico: riscos, custo do mês, capacidade ociosa, top 5 economias |
| Dia 21 | Revisão do que foi aplicado e da economia confirmada |
| Dia 30 | Decisão: contrato (emitir licença anual) ou encerrar (revogar token) |

### 5. Atualizar um cliente para uma versão nova

1. Publique a versão (tag `vX.Y.Z`) e confira no GHCR que a imagem existe.
2. Gere o kit com a versão nova e `--force`, com o mesmo plano do cliente:
   `python3 tools/kit_cliente.py --customer "Empresa X" --version 1.2.1 --plan profissional --days 365 --force`
3. Envie só o `.zip`. O cliente roda `./instalar.sh` de novo e confirma a atualização
   (passo a passo no `ATUALIZACAO.md` do kit). Ele não precisa do token nem de instalar a licença outra vez:
   a licença que já está no painel continua valendo.
4. Se o token do cliente venceu, gere um novo e envie pelo WhatsApp junto com o aviso.

### 6. Encerrar ou renovar

- **Renovar:** gere um kit novo com `--days 365` e envie só a licença. O cliente instala em
  Usuários e custos → Licença, sem reinstalar nada.
- **Encerrar:** revogue o token do cliente no GitHub. A licença expira sozinha na data.

## Checklist antes de enviar

- [ ] Versão do kit = tag publicada no GHCR (`docker pull` com o token do robô funciona)
- [ ] `license_tool.py verify` mostra o cliente, o plano e a validade corretos
- [ ] Token com escopo só `read:packages` e com data de expiração
- [ ] Token enviado por canal diferente do `.zip`
