# Clientes Inadimplentes

Projeto de relatórios financeiros automatizados com Dagster, ClickHouse e SMTP.

## Regra de envio

O job dispara nos dias 15 e 25 do mês. Se esse dia cair em fim de semana ou feriado nacional, o envio é movido para o próximo dia útil.

## Ambientes

- Local: use `.env` ou `.env.local` com caminho absoluto do host (`DAGSTER_HOME=C:/.../dagster_home`)
- Produção: use `.env.production` e rode o container com `DAGSTER_HOME=/dagster_home`

## Estrutura persistente

- `dagster_home/` guarda a instância persistente do Dagster (`dagster.yaml`, scheduler, metadados e artefatos)
- `data/` guarda os relatórios gerados por dia

## Execução local

```bash
uv sync
uv run dagster dev -m dagster_app -h 0.0.0.0 -p 3000
```

## Execução em produção com Docker

```bash
docker build -t <seu-usuario>/clientes-inadimplentes:latest .
docker run --env-file .env.production -p 3000:3000 -v $(pwd)/dagster_home:/dagster_home -v $(pwd)/data:/opt/dagster/app/data <seu-usuario>/clientes-inadimplentes:latest
```

Ou com Compose:

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production up --build
```

## Arquivos de ambiente

- `.env` -> local/real do ambiente do desenvolvedor
- `.env.example` -> template geral
- `.env.local.example` -> template para desenvolvimento local
- `.env.production.example` -> template para produção

## Variáveis obrigatórias

- `CLICKHOUSE_HOST`
- `CLICKHOUSE_PORT`
- `CLICKHOUSE_DATABASE`
- `CLICKHOUSE_USERNAME`
- `CLICKHOUSE_PASSWORD`
- `SMTP_SERVER`
- `SMTP_PORT`
- `EMAIL_SENDER`
- `SMTP_PASSWORD`
- `EMAIL_SUPPORT`
- `TIMEZONE`
- `DAGSTER_HOME`
