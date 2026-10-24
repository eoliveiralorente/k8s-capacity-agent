# Publicar atualizações e instalar o Capacity Agent no cliente

O fluxo usa GitHub Actions para testar e publicar uma imagem no GitHub Container
Registry (GHCR) quando uma versão é marcada no Git. O cliente escolhe quando
aplicar cada versão, executando um comando no servidor. A atualização preserva
o volume com banco, chave de criptografia e kubeconfigs e tenta reverter a
imagem automaticamente se o healthcheck falhar.

## 1. Publicar uma nova versão (responsável pelo produto)

Faça merge das alterações aprovadas na branch principal e atualize sua cópia:

```bash
git switch main
git pull --ff-only origin main
```

Crie e envie uma tag SemVer nova. Exemplo para a versão `1.2.3`:

```bash
git tag -a v1.2.3 -m "Release 1.2.3"
git push origin v1.2.3
```

Não reutilize uma tag já publicada. O push da tag inicia a workflow **Publish
container image**, que executa os testes focados e, se passarem, constrói
imagens `linux/amd64` e `linux/arm64`, publica no GHCR com as tags `1.2.3`,
`1.2` e `latest` e cria um GitHub Release com `compose.customer.yaml` e
`update-customer.sh` anexados.

No GitHub, abra **Actions** e confirme que a execução terminou com sucesso.
Depois confira o pacote de container em **Packages** e a página do release.
Informe ao cliente a versão sem o `v` (neste exemplo, `1.2.3`). O cliente baixa
os dois arquivos anexados ao release. Não envie imagem `.tar` nem código-fonte.

### Acesso do cliente ao GHCR

O pacote normalmente é privado. Antes da instalação, conceda ao cliente acesso
de leitura ao pacote ou, se a política do produto permitir distribuição
pública, altere a visibilidade do pacote para público nas configurações do
GitHub Packages. Para pacote privado, o cliente precisa de um Personal Access
Token (classic) com escopo `read:packages`, entregue por um canal seguro.
Nunca coloque o token em um arquivo do projeto ou no comando do atualizador.

## 2. Preparação inicial do servidor do cliente

Este procedimento assume Ubuntu ou Debian, Docker Engine instalado, acesso
administrativo `sudo`, arquitetura `amd64` ou `arm64` e acesso ao endpoint do
cluster Kubernetes que será testado. Não exponha o painel HTTP diretamente à
internet.

Confirme Docker e Compose:

```bash
sudo docker info
sudo docker compose version
```

Se `docker compose` não existir, instale o plugin Compose v2 pelo repositório
oficial do Docker para a distribuição do servidor. No Ubuntu/Debian:

```bash
. /etc/os-release
case "$ID" in
  ubuntu|debian) ;;
  *) echo "Este trecho é para Ubuntu/Debian." >&2; exit 1 ;;
esac
DOCKER_CODENAME="${UBUNTU_CODENAME:-$VERSION_CODENAME}"

sudo apt-get update
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL "https://download.docker.com/linux/$ID/gpg" \
  -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/$ID $DOCKER_CODENAME stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-compose-plugin
sudo docker compose version
```

O comando final precisa mostrar uma versão `v2...`. O pacote correto é
`docker-compose-plugin`; `apt install docker compose` não instala Compose.

Crie uma pasta para esta instalação e coloque nela os arquivos
`compose.customer.yaml` e `update-customer.sh` fornecidos pelo responsável do
produto, baixados dos anexos do release GitHub que corresponde à versão:

```bash
sudo mkdir -p /opt/capacity-agent
sudo chown "$USER":"$(id -gn)" /opt/capacity-agent
cd /opt/capacity-agent
```

Para pacote privado, autentique-se no GHCR uma vez. O Docker pedirá o token sem
que seja necessário digitá-lo como parte do comando:

```bash
sudo docker login ghcr.io --username <usuario-github>
```

Quando solicitado, informe o Personal Access Token com `read:packages` no campo
de senha. Não compartilhe nem registre o token em logs. Para um pacote público,
esta etapa pode ser ignorada.

Crie `.env` com o pacote e a versão inicial. Substitua `<VERSAO>` pela tag de
release:

```bash
umask 077
printf 'CAPACITY_AGENT_IMAGE=ghcr.io/eoliveiralorente/k8s-capacity-agent:<VERSAO>\n' > .env
```

Exemplo:

```bash
printf 'CAPACITY_AGENT_IMAGE=ghcr.io/eoliveiralorente/k8s-capacity-agent:1.2.3\n' > .env
```

Baixe e inicie a imagem:

```bash
sudo docker compose --env-file .env -p cliente-capacity-agent \
  -f compose.customer.yaml pull
sudo docker compose --env-file .env -p cliente-capacity-agent \
  -f compose.customer.yaml up -d
sudo docker compose --env-file .env -p cliente-capacity-agent \
  -f compose.customer.yaml ps
curl --fail http://127.0.0.1:8080/
```

O painel deve responder em `http://127.0.0.1:8080` no servidor. Para acessá-lo
de uma estação de trabalho, mantenha aberto um túnel SSH:

```bash
ssh -L 8080:127.0.0.1:8080 usuario@servidor-do-cliente
```

Abra `http://localhost:8080` na estação, crie a conta inicial e cadastre um
kubeconfig autorizado para teste.

## 3. Atualizar para uma nova versão (cliente)

O responsável pelo produto informa a nova tag publicada (por exemplo, `1.2.4`).
O script `update-customer.sh` instalado na seção 2 pode ser mantido entre
versões; substitua-o somente se as notas do release informarem que ele mudou.
No servidor, rode um único comando:

```bash
cd /opt/capacity-agent
bash update-customer.sh 1.2.4
```

O script baixa a versão do GHCR, atualiza apenas `CAPACITY_AGENT_IMAGE`, recria
o container e espera o healthcheck por até 90 segundos. Se o download falhar ou
o serviço não ficar saudável, tenta restaurar a imagem anterior e mostra os
logs. Se o pacote for privado, o login GHCR precisa continuar válido.

Use somente tags de release `MAJOR.MINOR.PATCH`, como `1.2.4`; não use `latest`
para atualizar. A versão explícita permite saber exatamente o que foi
implantado e facilita o rollback.

## 4. Dados, parada e remoção

O Compose mantém banco e chave de criptografia no volume Docker
`cliente-capacity-agent_capacity-agent-data`. Preserve esse volume e o nome do
projeto `cliente-capacity-agent` entre as reinicializações e atualizações. Não
é necessário configurar `CAPACITY_AGENT_ENCRYPTION_KEY`: a aplicação cria e
persiste a chave no volume.

Para parar sem apagar os dados:

```bash
sudo docker compose --env-file .env -p cliente-capacity-agent \
  -f compose.customer.yaml down
```

Para iniciar novamente, use o comando `up -d` da seção 2. Para apagar
definitivamente os dados, somente com autorização do cliente:

```bash
sudo docker compose --env-file .env -p cliente-capacity-agent \
  -f compose.customer.yaml down -v
```

`down -v` apaga banco, chave e kubeconfigs cifrados. Não o use para atualizar
nem para uma parada normal. Mantenha backup protegido do volume e teste a
restauração.
