# Site do Capacity Agent (só o produto)

Site estático: não precisa de servidor nem banco de dados.

## Antes de publicar

- Troque `[SEU-EMAIL]` em `index.html` pelo e-mail de contato.
- Em `termos.html` e `privacidade.html`, troque `[E-MAIL DE CONTATO]` e `[COMARCA]`.
- **Peça a um advogado para revisar os termos e a política de privacidade antes de publicar.**
- O WhatsApp do botão "Pedir o teste" é o (11) 94722-9481. Troque em `index.html` se for outro.

## Publicar no Cloudflare Pages (grátis, recomendado)

1. Crie uma conta em pages.cloudflare.com.
2. Create a project → Direct Upload → arraste esta pasta inteira.
3. Em Custom domains, adicione o seu domínio (ex.: capacityagent.com.br) e siga as instruções de DNS.

## Publicar no GitHub Pages (grátis)

1. Crie um repositório público, por exemplo `capacity-agent-site`, e envie os arquivos desta pasta.
2. Settings → Pages → Source: branch `main`, pasta `/ (root)`.
3. Para domínio próprio: em Settings → Pages → Custom domain, informe o domínio e crie no DNS
   um registro CNAME apontando para `<seu-usuario>.github.io`.

## Novo artigo no blog

1. Copie `blog/requests-kubernetes.html` com outro nome e troque o texto.
2. Acrescente um cartão para ele em `blog/index.html` e na seção Blog de `index.html`.

## Arquivos

| Arquivo | O que é |
|---|---|
| `index.html` | Página principal |
| `styles.css` | Visual do site e do blog |
| `blog/index.html` | Lista de artigos |
| `blog/requests-kubernetes.html` | Primeiro artigo |
| `capacity-agent-demo.mp4`, `poster.jpg` | Vídeo da demonstração e a imagem de capa dele |
| `termos.html`, `privacidade.html` | Termos de uso e política de privacidade |
| `favicon.svg` | Ícone da aba do navegador |
