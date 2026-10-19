<p align="center">
  <img src="src/assets/banner_github.png" alt="CaféDaily-Bot — Seu bot de Daily Scrum no Discord" width="100%">
</p>

<p align="center">
  <strong>Bot Discord para registrar Dailys com painel interativo, relatórios em embed e métricas de gestão para administradores.</strong>
</p>

<p align="center">
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/Python-3.12-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.12"></a>
  <a href="https://discordpy.readthedocs.io/"><img src="https://img.shields.io/badge/discord.py-2.4+-5865F2?style=for-the-badge&logo=discord&logoColor=white" alt="discord.py"></a>
  <a href="https://www.mongodb.com/"><img src="https://img.shields.io/badge/MongoDB-7-47A248?style=for-the-badge&logo=mongodb&logoColor=white" alt="MongoDB"></a>
  <a href="https://www.docker.com/"><img src="https://img.shields.io/badge/Docker-Compose-2496ED?style=for-the-badge&logo=docker&logoColor=white" alt="Docker Compose"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-2B140F?style=for-the-badge" alt="License MIT"></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Slash%20Commands-4-5865F2?style=flat-square" alt="Slash Commands">
  <img src="https://img.shields.io/badge/Modals%20%26%20Buttons-Interações-2B140F?style=flat-square" alt="Modals e Buttons">
  <img src="https://img.shields.io/badge/Métricas-Streak%20%26%20Horário-E67E22?style=flat-square" alt="Métricas">
  <img src="https://img.shields.io/badge/Marca-%232B140F-2B140F?style=flat-square&logoColor=white" alt="Cor da marca">
</p>

---

## Índice

- [Sobre](#sobre)
- [Funcionalidades](#funcionalidades)
- [Fluxo de uso](#fluxo-de-uso)
- [Comandos](#comandos)
- [Stack](#stack)
- [Pré-requisitos](#pré-requisitos)
- [Configuração no Discord](#configuração-no-discord)
- [Variáveis de ambiente](#variáveis-de-ambiente)
- [Instalação](#instalação)
- [Uso](#uso)
- [Estrutura do projeto](#estrutura-do-projeto)
- [Licença](#licença)

---

## Sobre

O **CaféDaily-Bot** centraliza o registro de **Daily Scrum** no Discord: a equipe preenche um formulário (modal) a partir de um painel com botão; cada envio é salvo no **MongoDB** e notificado em um canal privado para administradores, com embed formatado e menção `@everyone`.

Administradores também têm acesso a **métricas de gestão**: sequência de dias com daily, horários habituais de envio e ranking por streak.

---

## Funcionalidades

| Área | Descrição |
|------|-----------|
| **Painel interativo** | Imagem de banner + botão persistente *Registrar Daily* (sobrevive a reinício do bot) |
| **Modal** | 5 campos: projeto, ontem, hoje, amanhã e impedimentos |
| **Canal admin** | Embed com cor de marca `#2B140F`, autor, timestamp e campos organizados |
| **Persistência** | Cada daily na coleção `dailies` com índices por guild, usuário e data |
| **Métricas** | Streak atual, recorde, horário mais comum e ranking entre membros |
| **Deploy** | Docker Compose com serviços `bot` + `mongo` |

---

## Fluxo de uso

```mermaid
sequenceDiagram
  participant Membro
  participant Discord
  participant Bot
  participant MongoDB
  participant Admins

  Membro->>Discord: Clica em Registrar Daily
  Discord->>Bot: Interação (botão)
  Bot->>Discord: Abre modal
  Membro->>Discord: Envia formulário
  Discord->>Bot: modal_submit
  Bot->>MongoDB: insert daily
  Bot->>Admins: @everyone + embed no canal admin
  Bot->>Membro: Confirmação efêmera
```

---

## Comandos

> Todos os comandos abaixo exigem permissão de **Administrador** no servidor. Respostas de métricas são **efêmeras** (só quem executou vê).

| Comando | Descrição |
|---------|-----------|
| `/daily-setup` | Publica o painel (imagem + botão) no canal atual |
| `/daily-stats` `membro` | Métricas individuais: totais, streaks, horários habituais |
| `/daily-ranking-streaks` `limite` | Ranking por dias consecutivos com daily (3–25, padrão 10) |

---

## Stack

| Camada | Tecnologia |
|--------|------------|
| Runtime | Python 3.12 |
| API Discord | [discord.py](https://discordpy.readthedocs.io/) 2.4+ |
| Banco | MongoDB 7 (Motor async) |
| Config | python-dotenv |
| Container | Docker + Docker Compose |

---

## Pré-requisitos

- Conta no [Discord Developer Portal](https://discord.com/developers/applications)
- **Docker** e **Docker Compose** (recomendado) **ou** Python 3.12+ e MongoDB acessível
- Servidor Discord com permissão para convidar o bot e usar slash commands

---

## Configuração no Discord

1. Crie uma **aplicação** e um **Bot**; copie o **token**.
2. Em **OAuth2 → URL Generator**, marque os escopos:
   - `bot`
   - `applications.commands`
3. Permissões sugeridas do bot:
   - Enviar mensagens · Incorporar links · Anexar arquivos
   - Usar comandos de aplicação
   - **Mencionar @everyone, @here e todos os cargos** (canal admin)
4. Convide o bot com a URL gerada.
5. Crie dois canais:
   - **Painel** — visível à equipe que vai registrar dailys
   - **Admin** — restrito à staff; destino dos relatórios
6. No canal admin, em **Permissões**, permita que o bot envie mensagens e use `@everyone`.

### Copiar IDs

Ative **Modo desenvolvedor** em *Configurações do usuário → Avançado* e use *Copiar ID* no servidor e nos canais.

---

## Variáveis de ambiente

Copie o exemplo e preencha:

```bash
cp .env.example .env
```

| Variável | Obrigatório | Descrição |
|----------|:-----------:|-----------|
| `DISCORD_TOKEN` | Sim | Token do bot |
| `DAILY_ADMIN_CHANNEL_ID` | Sim | ID do canal onde as dailys são publicadas |
| `DISCORD_GUILD_ID` | Não | ID do servidor — acelera sync dos slash commands em dev |
| `MONGODB_URI` | Sim | URI do MongoDB (`mongodb://mongo:27017` no Compose) |
| `MONGODB_DB_NAME` | Não | Nome do banco (padrão: `cafedaily`) |
| `TIMEZONE` | Não | Fuso IANA para datas/horários (padrão: `America/Sao_Paulo`) |

---

## Instalação

### Docker (recomendado)

```bash
git clone git@github.com:aethos-tech/CafeDaily-Bot.git
cd CafeDaily-Bot
cp .env.example .env
# Edite .env com token e IDs

docker compose up -d --build
```

Ver logs:

```bash
docker compose logs -f bot
```

> Após alterar o `.env`, recrie o container do bot (o `restart` sozinho **não** recarrega variáveis):
>
> ```bash
> docker compose up -d --force-recreate bot
> ```

### Local (sem Docker)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edite .env — MONGODB_URI deve apontar para seu MongoDB

python -m src.main
```

---

## Uso

1. Um **administrador** executa **`/daily-setup`** no canal do painel.
2. O bot publica a **imagem do painel** e o botão **Registrar Daily**.
3. O membro clica, preenche o **modal** e envia.
4. O bot grava no MongoDB e envia o **embed** no canal admin com `@everyone`.
5. O membro recebe confirmação **privada** (efêmera).

Para acompanhar a equipe:

- **`/daily-stats @membro`** — visão individual (streak, horários, totais).
- **`/daily-ranking-streaks`** — ranking de consistência.

---

## Estrutura do projeto

```
CafeDaily-Bot/
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── .env.example
└── src/
    ├── main.py              # Entrypoint, sync de commands, view persistente
    ├── daily_view.py        # Painel, modal, embed admin
    ├── admin_metrics.py     # /daily-stats e /daily-ranking-streaks
    ├── metrics_service.py   # Cálculo de streaks e horários
    ├── db.py                # MongoDB (Motor)
    └── assets/
        ├── banner_github.png
        └── painel_de_daily.png
```

---

## Licença

Este projeto está sob a licença **MIT**. Veja o arquivo [LICENSE](LICENSE) para mais detalhes.

Copyright © 2026 [Ariel Sousa](https://github.com/aethos-tech) · [Aethos Tech](https://github.com/aethos-tech)

---

<p align="center">
  Desenvolvido por <strong>Ariel Sousa</strong> · <a href="https://github.com/aethos-tech">Aethos Tech</a>
</p>

## Integração com o Kina Hub

O modo gerenciado pelo Hub usa o mesmo CaféDaily, com o Hub como fonte dos relatórios. Ele dispensa MongoDB e não publica respostas em canais compartilhados. O modo original continua disponível quando `HUB_API_URL` não está configurado.

No modo Hub:

1. A administração abre **CaféDaily** no menu do Hub, informa o token e habilita os servidores em que o bot está instalado.
2. A liderança abre **Configurações do projeto → Daily pelo Discord**, escolhe servidor e canal e salva. O serviço publica o painel automaticamente; também é possível solicitar sua atualização pelo Hub.
3. Cada participante gera um código temporário na aba **Daily report** e usa `/hub-vincular codigo` no servidor do projeto. O código expira em 10 minutos e só pode ser usado uma vez.
4. O botão **Registrar Daily** abre um fluxo privado com as perguntas atuais do projeto. Formulários maiores são divididos em etapas, incluindo bloqueios.
5. O envio é validado e salvo no Hub. Atualizar o daily conserva o horário do primeiro envio e mantém um relatório por pessoa, projeto e dia no fuso configurado.
6. Lembretes chegam por DM apenas a contas vinculadas com a opção habilitada e daily pendente. Dias, horário e fuso vêm do projeto; as preferências da conta são respeitadas. O serviço tenta novamente entregas não confirmadas, com intervalo de 10 minutos e limite de três tentativas por pessoa/dia. Mensagens diretas bloqueadas pelo usuário impedem a entrega.

### Serviço no servidor

Use `docker-compose.hub.yml`, com um arquivo `.env.hub` protegido contendo apenas:

```dotenv
HUB_API_URL=https://hub-api.kinatech.com.br
HUB_BRIDGE_KEY=<credencial interna provisionada no servidor>
```

A API do Hub usa a mesma credencial em `DAILY_DISCORD_BRIDGE_KEY` e uma chave AES de 32 bytes em base64 em `DAILY_DISCORD_ENCRYPTION_KEY`. Esses valores são de infraestrutura e não entram no Git. O token do Discord é configurado pelo painel e fica criptografado no banco do Hub.

```bash
docker compose -f docker-compose.hub.yml up -d --build
```

O serviço consulta a configuração a cada 20 segundos. Alterações no token reconectam o bot; desativá-lo no Hub encerra a conexão. Não é preciso editar arquivos ou reiniciar o container para alterar canais, servidores, perguntas ou lembretes.

O convite gerado pelo Hub pede apenas visualização do canal, envio de mensagens, embeds e histórico. O modo Hub não precisa do intent privilegiado de conteúdo de mensagens, nem de permissão de administrador.

### Verificação

```bash
python -m unittest discover -s tests -v
```

Os testes usam transportes locais e não enviam mensagens para pessoas reais no Discord.
