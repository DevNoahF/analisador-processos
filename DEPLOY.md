# Workspace compartilhado com HTTPS

O dashboard já usa uma única conta e um único espaço de dados por instância. Com a implantação abaixo, todas as pessoas da equipe entram pelo mesmo domínio e usam a senha compartilhada. Elas veem os mesmos lotes. Qualquer membro da equipe que conhece a senha pode consultar, alterar, exportar e enviar documentos aos provedores escolhidos.

## O que o servidor precisa

- Um servidor Linux/VPS que você controla e Docker com Docker Compose.
- Um domínio com DNS apontando para esse servidor.
- Portas TCP 80 e 443 acessíveis pela internet para o Caddy obter e renovar o certificado TLS.
- Um volume persistente com backup privado para `/data`.

O dashboard Python precisa de um servidor que execute contêineres; Sites estáticos não podem executar este backend. Ainda não foi publicado online porque o projeto não contém acesso a um servidor, domínio ou VPS.

## Preparar o servidor

1. Copie o projeto para um servidor confiável com SSH e Docker Compose. Não envie `.env`, `.venv/`, `data/` ou documentos ao Git.
2. Copie `.env.example` para `.env`. Defina o domínio real e gere uma frase-senha longa, aleatória e compartilhada somente com as pessoas autorizadas. O servidor usa `SHR_SHARED_PASSWORD` para validar o login de todos. Proteja o arquivo e os backups com acesso restrito (`chmod 600 .env`). O catálogo de IDs atuais está preenchido em `SHR_MODELS_JSON`.
3. Aponte o DNS para o servidor e permita as portas 80/443 no firewall.
4. Inicie com `docker compose up -d --build` e confira `docker compose logs --tail=100 caddy dashboard`.
5. Abra `https://<seu-domínio>` e distribua o endereço e a senha por um canal interno autorizado.

O backend não publica a porta 8765 na internet. Caddy termina HTTPS e é o único caminho de entrada. O volume `shr-data` contém documentos, histórico e chaves de configuração de conta; proteja os backups. As chaves de API individuais só ficam na memória do processo durante uma revisão.

Os IDs do catálogo foram confirmados nas documentações oficiais atuais, mas o acesso de uma chave depende do plano/conta de cada usuário. Antes de enviar autos reais, faça uma revisão de homologação com o provedor escolhido para validar o acesso e a resposta estruturada. Nenhuma chamada é feita sem iniciar uma revisão pelo dashboard.

## Senha compartilhada

`SHR_SHARED_PASSWORD` é configurada somente no `.env` do servidor. Ela não é enviada ao repositório nem embutida no código. Cada membro recebe a mesma senha e compartilha a autorização do workspace. Troque a frase no `.env` e recrie o container para revogá-la. Ao mudar a senha, contas já configuradas continuam vinculadas ao mesmo workspace e novos logins usam o valor atual.

Para rodar só no próprio computador, `./run.sh` mantém o modo local em `127.0.0.1:8765`.
