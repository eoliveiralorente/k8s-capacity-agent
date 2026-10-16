# Procedimento — Capacity Agent

Guia para instalar e operar o Capacity Agent em diferentes ambientes Kubernetes.
O provedor, a empresa e o cluster são definidos conforme cada implantação.
O aplicativo pode ser hospedado em diferentes ambientes e conectar clusters
Kubernetes compatíveis, desde que o servidor consiga alcançar o endpoint da
API configurado no kubeconfig.

---

## Pré-requisitos (verificar uma vez)

```bash
# Python 3.10 ou superior
python3 --version

# O kubectl é necessário para validar kubeconfigs e consultar clusters.
kubectl version --client
```

| Item               | Valor                                    |
| ------------------ | ---------------------------------------- |
| Pasta do projeto   | Diretório onde o repositório foi clonado |
| Porta do dashboard | `8080`                                   |

O Capacity Agent não exige OCI, GCP ou outro provedor específico para iniciar.
Para avaliar um cluster, é necessário ter acesso Kubernetes válido; a forma de
obter credenciais varia conforme o provedor e a configuração do ambiente.


---

## 1. Primeira vez — instalar dependências

```bash
cd /caminho/para/capacity-agent
python3 -m pip install -r requirements.txt
```

Substitua `/caminho/para/capacity-agent` pelo diretório real do repositório.
Se usar um ambiente virtual, ative-o antes de instalar as dependências e iniciar
o sistema.

---



## 2. Uso diário — iniciar o dashboard

```bash
cd /caminho/para/capacity-agent
mkdir -p .capacity-agent
if [ ! -s .capacity-agent/encryption.key ]; then
  (umask 077; python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())' > .capacity-agent/encryption.key)
fi
chmod 600 .capacity-agent/encryption.key
export CAPACITY_AGENT_ENCRYPTION_KEY="$(cat .capacity-agent/encryption.key)"
export CAPACITY_AGENT_COOKIE_SECURE=false
./serve.sh --host 127.0.0.1 --port 8080
```

O bloco cria a chave apenas na primeira execução e a reutiliza nas seguintes.
Mantenha o terminal aberto enquanto usar o sistema; encerre com `Ctrl+C`.
Para desenvolvimento com recarga automática, acrescente `--reload` ao comando
`./serve.sh`.

**Abrir no navegador:**


| Página              | URL                                                                |
| ------------------- | ------------------------------------------------------------------ |
| Dashboard DevOps    | [http://localhost:8080](http://localhost:8080)                     |
| Relatório gerencial | [http://localhost:8080/relatorio](http://localhost:8080/relatorio) |


**Encerrar:** `Ctrl+C` no terminal.

### Alternativa (se `./serve.sh` falhar)

```bash
python3 agent.py serve --host 127.0.0.1 --port 8080
```

### Conectar a um cluster Kubernetes

Abra [http://localhost:8080](http://localhost:8080), entre na conta e, na aba
**Cluster**, envie o kubeconfig, valide o acesso e selecione a conexão. O painel
consulta os nodes sem armazenar o arquivo em texto puro. Não apague nem
substitua `.capacity-agent/encryption.key`: sem a chave original, os kubeconfigs
já cadastrados não poderão ser descriptografados.

O diretório `.capacity-agent/` é ignorado pelo Git; faça backup seguro da chave.
`CAPACITY_AGENT_COOKIE_SECURE=false` deve ser usado somente em localhost. Para
acesso remoto, configure a chave no secret manager, publique atrás de HTTPS e siga
[docs/MULTI_TENANT.md](MULTI_TENANT.md).

O kubeconfig precisa ser válido no ambiente onde o Capacity Agent está rodando.
O aplicativo valida o arquivo e consulta os nodes antes de cadastrá-lo; plugins
de autenticação `exec` e referências externas a certificados não são aceitos.
Os passos para obter ou preparar o kubeconfig dependem do provedor Kubernetes
(por exemplo, GKE, EKS, AKS, OpenShift ou uma distribuição autogerenciada).

---

## 2.1. Testar em Docker

Instale Docker Engine com o plugin Docker Compose ou Docker Desktop. No
diretório do projeto, crie o arquivo `.env` com uma chave Fernet persistente.
Execute isto apenas na primeira instalação; o comando não substitui um `.env`
que já exista:

```bash
if [ ! -f .env ]; then
  umask 077
  printf 'CAPACITY_AGENT_ENCRYPTION_KEY=%s\n' \
    "$(python3 -c 'import base64, secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())')" > .env
fi
```

Não apague nem substitua `.env`: a mesma chave é necessária para ler kubeconfigs
já cadastrados. O arquivo é ignorado pelo Git.
Construa e inicie o contêiner:

```bash
docker compose up --build -d
docker compose ps
docker compose logs -f
```

Abra [http://localhost:8080](http://localhost:8080). O Compose publica o painel
somente no próprio computador. O banco, relatórios e demais arquivos ficam no
volume Docker `capacity-agent-data` e sobrevivem à recriação do contêiner.
`docker compose down` mantém os dados; **não use `docker compose down -v`** se
quiser preservá-los. Faça backup do volume e da chave em conjunto.
Esta configuração usa SQLite e deve rodar como uma única réplica. Não escale
horizontalmente nem compartilhe o volume entre várias instâncias; para isso,
será necessário migrar para um banco de dados cliente/servidor.

O contêiner precisa conseguir alcançar o endpoint Kubernetes indicado pelo
kubeconfig enviado. Para uso em Kubernetes, o acesso remoto e o HTTPS devem ser
configurados pelo ambiente do cliente; a publicação via Compose acima é apenas
para teste local.

---


## 3. Avaliar o cluster (atualizar dados)

Escolha **uma** opção:

**Opção A — pelo dashboard**

1. Abrir [http://localhost:8080](http://localhost:8080)
2. Clicar em **Nova Avaliação**
3. Aguardar conclusão e recarregar a página

**Opção B — pelo terminal**

```bash
cd /caminho/para/capacity-agent
python3 agent.py evaluate
```

> Só atualiza dados após **Nova Avaliação** ou `evaluate`. Atualizar a página (F5) sozinha **não** reavalia o cluster.

---



## 4. Fluxo DevOps — aprovar recomendações

```bash
# Ver pendentes
python3 agent.py list --status pending

# Aprovar
python3 agent.py approve <ID> --by "Seu Nome"

# Rejeitar
python3 agent.py reject <ID> --by "Seu Nome" --reason "motivo"

# Simular execução
python3 agent.py execute --dry-run

# Executar aprovadas (altera o cluster)
python3 agent.py execute --force
```

No dashboard: aba **Recomendações** → aprovar/rejeitar/executar pelos modais.

---



## 5. Relatórios para gestão



### Relatório executivo (HTML / PDF)

```bash
python3 agent.py relatorio
```

- Abrir o HTML gerado em `.capacity-agent/reports/executive-*.html`
- Ou acessar [http://localhost:8080/relatorio](http://localhost:8080/relatorio) (com dashboard rodando)
- **Exportar PDF:** botão *Exportar PDF / Imprimir* ou `Ctrl+P` → Salvar como PDF



### Documento de cenário do ambiente

```bash
python3 agent.py cenario-doc
```

Gera um relatório HTML do ambiente avaliado em `docs/`.

- Abrir no Chrome/Edge
- **Exportar PDF:** botão *Exportar PDF / Imprimir* ou `Ctrl+P`
- Configurar: A4, gráficos de fundo ativado

---



## 6. Comandos úteis

```bash
python3 agent.py status          # status do agent e gate DevOps
python3 agent.py list            # todas as recomendações
python3 agent.py report <ID>     # relatório de uma avaliação
python3 agent.py --help          # ajuda geral
```

---



## 7. Problemas comuns


| Sintoma                        | Solução                                                                                   |
| ------------------------------ | ----------------------------------------------------------------------------------------- |
| `uvicorn não encontrado`       | Ative o ambiente Python do projeto e instale `requirements.txt`                           |
| Dashboard mostra dados antigos | Rodar **Nova Avaliação** ou `python3 agent.py evaluate`                                   |
| `kubectl` sem acesso           | Verifique as credenciais e o contexto usando as instruções do provedor do cluster         |
| Porta 8080 em uso              | `./serve.sh --port 8081`                                                                  |


---



## Checklist rápido (copiar e usar)

```
[ ] cd /caminho/para/capacity-agent
[ ] kubectl config current-context (contexto esperado selecionado?)
[ ] ./serve.sh                 (dashboard no ar?)
[ ] http://localhost:8080      (abriu no navegador?)
[ ] Nova Avaliação             (dados atualizados?)
[ ] Revisar abas Overview / Capacity / Scheduling
[ ] Aprovar recomendações pendentes (se houver)
[ ] Gerar relatório gerencial (relatorio ou /relatorio)
[ ] Ctrl+C                     (encerrar quando terminar)
```

---



## Referência — ordem típica de uma sessão

```
1. ./serve.sh
2. Abrir http://localhost:8080
3. Nova Avaliação
4. Analisar dashboard
5. Aprovar/rejeitar recomendações
6. Exportar relatório para gestão (se necessário)
7. Ctrl+C
```

---

*Última atualização: setembro/2026 · Capacity Agent*