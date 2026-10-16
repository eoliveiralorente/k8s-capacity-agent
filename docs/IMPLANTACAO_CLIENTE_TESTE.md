# Instalar o Capacity Agent no servidor do cliente

Este guia é destinado ao administrador do servidor do cliente. Ao final, o
painel estará disponível somente no próprio servidor ou por túnel SSH. Não
publique a porta HTTP diretamente na internet.

## O que o fornecedor deve entregar

O cliente precisa receber estes arquivos, todos da mesma versão:

- `capacity-agent-teste-2.tar`: imagem Docker pré-construída.
- `compose.customer.yaml`: configuração de execução.
- O SHA-256 de `capacity-agent-teste-2.tar`, enviado separadamente ou por um
  canal confiável.

O cliente não precisa do código-fonte nem precisa construir a imagem. Não
inclua no pacote `.env`, kubeconfigs, bancos de dados ou chaves de criptografia.

## 1. Preparar o servidor

Este procedimento assume um servidor Ubuntu ou Debian com acesso `sudo` e
arquitetura compatível com a imagem recebida. A imagem de teste deste guia é
`linux/amd64`. É necessário ter Docker Engine instalado.

Confirme que o daemon Docker está acessível:

```bash
sudo docker info
```

Confirme que o plugin Docker Compose v2 está instalado:

```bash
sudo docker compose version
```

Se o comando mostrar uma versão `v2...`, siga para a seção 2. Se retornar
`docker: unknown command: docker compose`, instale o plugin.

### Instalar o plugin Compose v2 no Ubuntu/Debian

O pacote chama-se `docker-compose-plugin` e é distribuído pelo repositório
oficial do Docker. Não use `apt install docker compose`, `docker-composer` ou
`docker composer`.

Execute:

```bash
. /etc/os-release
case "$ID" in
  ubuntu|debian) ;;
  *) echo "Este procedimento de instalação do Compose é para Ubuntu/Debian." >&2; exit 1 ;;
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

O último comando precisa mostrar a versão do Compose. Se o pacote não for
encontrado, pare e confirme a versão/nome da distribuição; não tente instalar
pacotes chamados `docker` ou `compose`. O comando `apt-get` precisa de `sudo`.

## 2. Copiar e verificar o pacote

Crie uma pasta exclusiva para esta instalação:

```bash
sudo mkdir -p /opt/capacity-agent-teste
sudo chown "$USER":"$(id -gn)" /opt/capacity-agent-teste
```

Copie `capacity-agent-teste-2.tar` e `compose.customer.yaml` para essa pasta.
Por exemplo, na máquina de onde os arquivos serão enviados:

```bash
scp capacity-agent-teste-2.tar compose.customer.yaml \
  usuario@servidor-do-cliente:/opt/capacity-agent-teste/
```

Substitua `usuario@servidor-do-cliente` pelo usuário e endereço SSH reais. No
servidor, confirme que os dois arquivos chegaram e valide o hash fornecido:

```bash
cd /opt/capacity-agent-teste
ls -lh capacity-agent-teste-2.tar compose.customer.yaml
echo '<SHA256 recebido>  capacity-agent-teste-2.tar' | sha256sum --check -
```

Substitua `<SHA256 recebido>` pelo valor enviado pelo fornecedor. Prossiga
somente se aparecer `capacity-agent-teste-2.tar: OK`. Se o arquivo não existir,
repita a cópia antes de continuar. Se o hash divergir, não carregue a imagem;
solicite uma nova cópia ao fornecedor.

Carregue a imagem e confira a tag:

```bash
sudo docker load --input capacity-agent-teste-2.tar
sudo docker image inspect capacity-agent:teste-2 \
  --format '{{.Os}}/{{.Architecture}}'
```

O resultado deve corresponder à arquitetura do servidor, por exemplo
`linux/amd64`.

## 3. Iniciar o painel

Crie o arquivo `.env` com a tag entregue. Ele guarda somente a referência da
imagem; não contém senhas nem a chave de criptografia:

```bash
cd /opt/capacity-agent-teste
printf 'CAPACITY_AGENT_IMAGE=capacity-agent:teste-2\n' > .env
```

Valide a configuração e inicie:

```bash
sudo docker compose --env-file .env -p cliente-teste \
  -f compose.customer.yaml config
sudo docker compose --env-file .env -p cliente-teste \
  -f compose.customer.yaml up -d
```

O primeiro comando deve exibir a configuração sem erro; o segundo deve indicar
que o container iniciou. Consulte o estado e os logs:

```bash
sudo docker compose --env-file .env -p cliente-teste \
  -f compose.customer.yaml ps
sudo docker compose --env-file .env -p cliente-teste \
  -f compose.customer.yaml logs --tail=100
```

Verifique se a aplicação responde:

```bash
curl --fail http://127.0.0.1:8080/
```

O Compose publica a porta somente em `127.0.0.1`. Para acesso a partir da sua
estação, mantenha um túnel SSH aberto:

```bash
ssh -L 8080:127.0.0.1:8080 usuario@servidor-do-cliente
```

Depois abra [http://localhost:8080](http://localhost:8080) na estação. Crie a
conta inicial e entre no painel.

## 4. Cadastrar um cluster para o teste

Na aba **Cluster**, envie um kubeconfig autorizado para o teste. O servidor
precisa alcançar o endpoint da API Kubernetes informado nesse arquivo. Use
credenciais de teste ou credenciais expressamente autorizadas pelo cliente.

Não é necessário definir `CAPACITY_AGENT_ENCRYPTION_KEY`: na primeira execução,
a aplicação gera uma chave e a armazena junto com o banco no volume Docker
`cliente-teste_capacity-agent-data`.

**Não remova esse volume nem altere o nome do projeto `cliente-teste`.** O volume
guarda o banco, a chave de criptografia e os kubeconfigs cifrados. Perder o
volume ou separar o banco da chave pode tornar os kubeconfigs irrecuperáveis.

## 5. Parar, iniciar e remover

Parar os containers sem apagar os dados:

```bash
sudo docker compose --env-file .env -p cliente-teste \
  -f compose.customer.yaml down
```

Iniciar novamente:

```bash
sudo docker compose --env-file .env -p cliente-teste \
  -f compose.customer.yaml up -d
```

Para remover definitivamente os dados do teste, obtenha autorização do cliente
e então remova também o volume:

```bash
sudo docker compose --env-file .env -p cliente-teste \
  -f compose.customer.yaml down -v
```

O comando `down -v` apaga o banco, a chave e os kubeconfigs armazenados. Não o
use para uma simples parada ou atualização.

## Atualizar para uma nova versão

O fornecedor deve entregar uma nova imagem, com nova tag, arquivo `.tar` e
SHA-256. Copie a imagem para `/opt/capacity-agent-teste`, valide o hash e
carregue-a, por exemplo:

```bash
echo '<NOVO_SHA256>  capacity-agent-teste-3.tar' | sha256sum --check -
sudo docker load --input capacity-agent-teste-3.tar
printf 'CAPACITY_AGENT_IMAGE=capacity-agent:teste-3\n' > .env
sudo docker compose --env-file .env -p cliente-teste \
  -f compose.customer.yaml up -d
```

Mantenha o mesmo nome do projeto e o volume para preservar os dados entre
versões.
