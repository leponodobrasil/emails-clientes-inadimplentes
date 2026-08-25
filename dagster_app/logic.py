from __future__ import annotations

import calendar
import os
import smtplib
import traceback
from datetime import date, datetime, timedelta
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from zoneinfo import ZoneInfo

import clickhouse_connect
import holidays
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

TIMEZONE = os.getenv("TIMEZONE", "America/Sao_Paulo")
BRAZIL_HOLIDAYS = holidays.Brazil()

QUERY_CONTAS_RECEBER = """
with base as (
SELECT
    a.E1_FILIAL as filial,
    b.A1_EST as uf,
    b.A1_MUN as municipio,
    b.A1_COD as cod_cliente,
    b.A1_NOME as nome_cliente,
    a.E1_PEDIDO as cod_pedido,
    a.E1_TIPO as doc_tipo,
    c.D2_DOC as documento,
    a.E1_PARCELA as parcela,
    a.E1_VALOR as valor,
    a.E1_HIST as historico,
    toDate(a.E1_VENCORI) as vencimento_original,
    toDate(a.E1_VENCREA) as vencimento_real,
    nullif(trim(a.E1_VEND1),'') as cod_vendedor_tab_contas,
    nullif(trim(b.A1_VEND) ,'') as cod_vendedor_tab_cliente,
    nullif(trim(f.A3_NREDUZ) ,'') as nome_vendedor,
    nullif(trim(f.A3_EMAIL),'') as email_vendedor,
    nullif(trim(f.A3_GEREN),'') as cod_gerente,
    nullif(trim(s.A3_EMAIL),'') as email_gerente
FROM
    aura.SE1010 a final
left join aura.SA1010 b final
on a.E1_LOJA = b.A1_LOJA
and a.E1_CLIENTE = b.A1_COD
and b.D_E_L_E_T_ <> '*'
left join (
SELECT
        D2_FILIAL,
        D2_PEDIDO,
        D2_CLIENTE,
        C5_VENDBB,
        MIN(D2_DOC) AS D2_DOC
    FROM aura.SD2010 d final
    left join aura.SC5010 e final
    on d.D2_FILIAL= e.C5_FILIAL
    and d.D2_PEDIDO = e.C5_NUM
    and e.D_E_L_E_T_ <> '*'
    WHERE d.D_E_L_E_T_ <> '*'
    GROUP BY
        D2_FILIAL,
        D2_PEDIDO,
        D2_CLIENTE,
        C5_VENDBB
) c
on c.D2_FILIAL = a.E1_FILIAL
and c.D2_PEDIDO = a.E1_PEDIDO
and c.D2_CLIENTE = a.E1_CLIENTE
left join aura.SA3010 f final
on b.A1_VEND = f.A3_COD
and f.D_E_L_E_T_ <> '*'
LEFT JOIN aura.SA3010 s final
ON f.A3_GEREN = s.A3_COD
AND s.D_E_L_E_T_ <> '*'
WHERE
    a.D_E_L_E_T_ <> '*'
    and a.E1_VEND1 not in ('100001','100300', '999998')
    and a.E1_SALDO > 0
    and a.E1_PARCELA not like '%J%'
    and a.E1_SITUACA not in('F', 'P')
    and toDate(a.E1_VENCREA) < today()
    and a.E1_PREFIXO <> 'RA'
    and trim(a.E1_TIPO) in ('NF','BOL')
)
select
multiIf(
    nullIf(
        if(
            nullIf(cod_vendedor_tab_contas, '') IS NULL
            OR cod_vendedor_tab_contas <> cod_vendedor_tab_cliente,
            cod_vendedor_tab_cliente,
            cod_vendedor_tab_contas
        ),
        ''
    ) IS NULL,
    cod_gerente,
    if(
        nullIf(cod_vendedor_tab_contas, '') IS NULL
        OR cod_vendedor_tab_contas <> cod_vendedor_tab_cliente,
        cod_vendedor_tab_cliente,
        cod_vendedor_tab_contas
    )
) AS KEY_SEND,
     filial,
     uf,
     municipio,
     cod_cliente,
     nome_cliente,
     cod_pedido,
     doc_tipo,
     documento,
     parcela,
     valor,
     historico,
     vencimento_original,
     vencimento_real,
     cod_vendedor_tab_contas,
     cod_vendedor_tab_cliente,
     nome_vendedor,
     email_vendedor,
     cod_gerente,
     email_gerente
from base
"""

QUERY_VENDEDORES = """
SELECT
    trim(toString(A3_COD)) AS cod_vendedor,
    trim(toString(A3_NREDUZ)) AS nome_vendedor,
    trim(toString(A3_EMAIL)) AS email_vendedor,
    trim(toString(A3_GEREN)) AS cod_gerente
FROM aura.SA3010 a final
LEFT JOIN aura.SA3010 s final
ON a.A3_GEREN = s.A3_COD
AND s.D_E_L_E_T_ <> '*'
WHERE a.D_E_L_E_T_ <> '*'
"""


def get_env(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if value is None:
        raise ValueError(f"Variável de ambiente obrigatória ausente: {name}")
    return value


def as_local_date(day: date | datetime | str | None = None) -> date:
    if day is None:
        return datetime.now(ZoneInfo(TIMEZONE)).date()
    if isinstance(day, datetime):
        return day.astimezone(ZoneInfo(TIMEZONE)).date()
    if isinstance(day, str):
        return datetime.fromisoformat(day).astimezone(ZoneInfo(TIMEZONE)).date()
    return day


def is_business_day(candidate: date) -> bool:
    return candidate.weekday() < 5 and candidate not in BRAZIL_HOLIDAYS


def move_to_next_business_day(candidate: date) -> date:
    next_day = candidate
    while not is_business_day(next_day):
        next_day += timedelta(days=1)
    return next_day


def effective_send_dates_for_month(reference_date: date | datetime | str | None = None) -> set[date]:
    current = as_local_date(reference_date)
    _, last_day = calendar.monthrange(current.year, current.month)
    dates: set[date] = set()
    for target_day in (15, 25):
        if target_day > last_day:
            continue
        target = date(current.year, current.month, target_day)
        dates.add(move_to_next_business_day(target))
    return dates


def should_send_today(reference_date: date | datetime | str | None = None) -> bool:
    today = as_local_date(reference_date)
    return today in effective_send_dates_for_month(today)


def create_data_dir() -> Path:
    base_path = Path.cwd() / "data" / datetime.now(ZoneInfo(TIMEZONE)).strftime("%d%m%Y")
    base_path.mkdir(parents=True, exist_ok=True)
    return base_path


def fetch_dataframes() -> tuple[pd.DataFrame, pd.DataFrame]:
    client = clickhouse_connect.get_client(
        host=get_env("CLICKHOUSE_HOST"),
        port=int(get_env("CLICKHOUSE_PORT", "8123")),
        username=get_env("CLICKHOUSE_USERNAME"),
        password=get_env("CLICKHOUSE_PASSWORD"),
        database=get_env("CLICKHOUSE_DATABASE"),
    )
    df_contas_receber = client.query_df(QUERY_CONTAS_RECEBER)
    df_vendedores_tab = client.query_df(QUERY_VENDEDORES)
    return df_contas_receber, df_vendedores_tab


def build_reports(df_contas_receber: pd.DataFrame, df_vendedores_tab: pd.DataFrame, output_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    gerentes = ["300015", "000207", "000149", "300000", "000148", "000136"]
    df_gerentes = df_vendedores_tab[df_vendedores_tab["cod_vendedor"].isin(gerentes)].copy()

    df_vendedores_com_titulos_atrasados = df_contas_receber["KEY_SEND"].copy().drop_duplicates()
    filter_vendedores = ["999998", "100001", "100300", "999997", "999995", "999994", "999993"]
    df_vendedores_atualizados = df_vendedores_tab[
        df_vendedores_tab["cod_vendedor"].isin(df_vendedores_com_titulos_atrasados)
        & ~df_vendedores_tab["cod_vendedor"].isin(filter_vendedores)
    ].copy()
    df_vendedores_atualizados["email_vendedor"] = df_vendedores_atualizados["email_vendedor"].str.lower()

    for vend in df_vendedores_atualizados["cod_vendedor"]:
        df_filtrado = df_contas_receber[df_contas_receber["KEY_SEND"].isin([vend])]
        df_filtrado.to_excel(output_dir / f"{vend}.xlsx", index=False)

    return df_vendedores_atualizados, df_gerentes


def send_email(email_remetente: str, email_destinatario: str, senha_remetente: str, smtp_server: str, smtp_port: int, nome_vendedor: str, anexo: Path) -> None:
    msg = MIMEMultipart("alternative")
    msg["From"] = email_remetente
    msg["To"] = email_destinatario
    msg["Subject"] = f"Relação de clientes inadimplentes - {nome_vendedor}"

    html_content = f"""
    <!DOCTYPE html>
    <html lang="pt-BR">
    <head>
        <meta charset="UTF-8">
        <style>
            .title {{ display: flex; justify-content: space-between; }}
        </style>
    </head>
    <body style="margin:0; padding:0; background:#f3f4f6; font-family:Arial, Helvetica, sans-serif; color:#1f2937;">
        <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#f3f4f6; padding:24px 12px;">
            <tr>
                <td align="center">
                    <table width="680" cellpadding="0" cellspacing="0" border="0" style="max-width:680px; width:100%; background:#ffffff; border:1px solid #d1d5db;">
                        <tr>
                            <td style="background: #95ace9; padding:22px 28px; color:#ffffff;">
                                <div class="title">
                                    <div>
                                        <div style="font-size:22px; font-weight:bold;">Relação de Clientes Inadimplentes</div>
                                        <div style="font-size:13px; margin-top:6px;">Documento de acompanhamento financeiro</div>
                                    </div>
                                </div>
                            </td>
                        </tr>
                        <tr>
                            <td style="padding:28px;">
                                <p style="margin:0 0 18px 0; font-size:15px; line-height:1.7;">Prezado(a) <strong>{nome_vendedor}</strong>,</p>
                                <p style="margin:0 0 16px 0; font-size:15px; line-height:1.7;">Segue em anexo a relação atualizada de clientes inadimplentes sob sua responsabilidade.</p>
                                <p style="margin:0 0 18px 0; font-size:15px; line-height:1.7;">Solicitamos a verificação dos registros apresentados e, sempre que possível, o acompanhamento junto aos clientes para regularização das pendências.</p>
                                <table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:20px 0; background:#f9fafb; border:1px solid #e5e7eb;">
                                    <tr>
                                        <td style="padding:16px; font-size:14px; line-height:1.7; color:#374151;">
                                            <strong>Orientações:</strong><br>
                                            * Analise o arquivo anexo;<br>
                                            * Priorize títulos vencidos há mais tempo;<br>
                                            * Registre retornos relevantes do cliente.
                                        </td>
                                    </tr>
                                </table>
                                <p style="margin:0 0 18px 0; font-size:15px; line-height:1.7;">Em caso de dúvidas ou necessidade de apoio, a equipe financeira permanece à disposição.</p>
                                <div style="margin:0; font-size:15px; line-height:1.7; display: flex; flex-direction: column; align-items: center;">
                                    <div>Atenciosamente,</div>
                                    <div><strong>Equipe Financeira</strong></div>
                                    <div>Grupo Unità</div>
                                </div>
                            </td>
                        </tr>
                        <tr>
                            <td style="padding:14px 28px; background:#f9fafb; border-top:1px solid #e5e7eb; font-size:12px; color:#6b7280;">
                                Mensagem automática enviada pelo sistema de acompanhamento financeiro.
                            </td>
                        </tr>
                    </table>
                </td>
            </tr>
        </table>
    </body>
    </html>
    """

    msg.attach(MIMEText(html_content, "html", "utf-8"))

    if anexo.exists():
        filename = anexo.name
        with open(anexo, "rb") as file:
            attachment = MIMEApplication(file.read(), Name=filename)
        attachment["Content-Disposition"] = f'attachment; filename="{filename}"'
        msg.attach(attachment)
    else:
        raise FileNotFoundError(f"Arquivo de anexo não encontrado: {anexo}")

    with smtplib.SMTP(smtp_server, smtp_port) as server:
        server.starttls()
        server.login(email_remetente, senha_remetente)
        server.sendmail(email_remetente, email_destinatario, msg.as_string())


def send_error_email(erro: Exception, contexto_vendedor: dict, destinatario_suporte: str | None = None) -> None:
    support_email = destinatario_suporte or get_env("EMAIL_SUPPORT")
    traceback_str = "".join(traceback.format_exception(type(erro), erro, erro.__traceback__))
    cod_vendedor = contexto_vendedor.get("cod_vendedor", "N/A")
    nome_vendedor = contexto_vendedor.get("nome_vendedor", "N/A")

    subject = f"🚨 ERRO no Envio de E-mails - Vendedor {cod_vendedor}"
    body = f"""
    <html>
    <body>
        <h2>Ocorreu uma falha durante o processamento do relatório:</h2>
        <ul>
            <li><b>Vendedor:</b> {nome_vendedor} ({cod_vendedor})</li>
            <li><b>Código do Gerente:</b> {contexto_vendedor.get('cod_gerente', 'N/A')}</li>
            <li><b>E-mail do Vendedor:</b> {contexto_vendedor.get('email_vendedor', 'N/A')}</li>
        </ul>
        <hr>
        <h3>Detalhes Técnicos da Exceção:</h3>
        <pre style='background-color: #f4f4f4; padding: 10px; border-radius: 5px; font-family: monospace;'>{traceback_str}</pre>
    </body>
    </html>
    """

    msg = MIMEMultipart("alternative")
    msg["From"] = get_env("EMAIL_SENDER")
    msg["To"] = support_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "html"))

    with smtplib.SMTP(get_env("SMTP_SERVER"), int(get_env("SMTP_PORT", "587"))) as server:
        server.starttls()
        server.login(get_env("EMAIL_SENDER"), get_env("SMTP_PASSWORD"))
        server.sendmail(get_env("EMAIL_SENDER"), support_email, msg.as_string())


def send_reports(df_vendedores_atualizados: pd.DataFrame, df_gerentes: pd.DataFrame, output_dir: Path) -> list[str]:
    sent_emails: list[str] = []
    for vendedor in df_vendedores_atualizados.itertuples():
        try:
            email_vendedor = (vendedor.email_vendedor or "").strip().lower()
            nome_vendedor = vendedor.nome_vendedor
            cod_vendedor = vendedor.cod_vendedor
            cod_gerente = vendedor.cod_gerente

            if pd.isna(email_vendedor) or email_vendedor == "":
                print(f"Vendedor {cod_vendedor} - {nome_vendedor} não possui e-mail cadastrado.")
                continue

            recipient = email_vendedor
            send_email(
                email_remetente=get_env("EMAIL_SENDER"),
                email_destinatario=recipient,
                senha_remetente=get_env("SMTP_PASSWORD"),
                smtp_server=get_env("SMTP_SERVER"),
                smtp_port=int(get_env("SMTP_PORT", "587")),
                nome_vendedor=nome_vendedor,
                anexo=output_dir / f"{cod_vendedor}.xlsx",
            )
            sent_emails.append(recipient)
        except Exception as exc:  # pragma: no cover - log to support
            send_error_email(
                erro=exc,
                contexto_vendedor={
                    "cod_vendedor": getattr(vendedor, "cod_vendedor", "N/A"),
                    "nome_vendedor": getattr(vendedor, "nome_vendedor", "N/A"),
                    "cod_gerente": getattr(vendedor, "cod_gerente", "N/A"),
                    "email_vendedor": getattr(vendedor, "email_vendedor", "N/A"),
                },
                destinatario_suporte="ti@leponodobrasil.com.br",
            )
    return sent_emails


def execute_report_dispatch() -> dict[str, list[str]]:
    output_dir = create_data_dir()
    df_contas_receber, df_vendedores_tab = fetch_dataframes()
    df_vendedores_atualizados, df_gerentes = build_reports(df_contas_receber, df_vendedores_tab, output_dir)
    sent = send_reports(df_vendedores_atualizados, df_gerentes, output_dir)
    return {"sent_to": sent, "output_dir": str(output_dir)}
