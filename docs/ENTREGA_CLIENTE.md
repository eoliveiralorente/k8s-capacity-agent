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
python3 tools/kit_cliente.py --customer "Empresa X" --version 1.1.0 --pilot

# Contrato
python3 tools/kit_cliente.py --customer "Empresa X" --version 1.1.0 \
  --plan enterprise --clusters 3 --users 10 --days 365
```

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

### 5. Encerrar ou renovar

- **Renovar:** gere um kit novo com `--days 365` e envie só a licença. O cliente instala em
  Usuários e custos → Licença, sem reinstalar nada.
- **Encerrar:** revogue o token do cliente no GitHub. A licença expira sozinha na data.

## Checklist antes de enviar

- [ ] Versão do kit = tag publicada no GHCR (`docker pull` com o token do robô funciona)
- [ ] `license_tool.py verify` mostra o cliente, o plano e a validade corretos
- [ ] Token com escopo só `read:packages` e com data de expiração
- [ ] Token enviado por canal diferente do `.zip`
