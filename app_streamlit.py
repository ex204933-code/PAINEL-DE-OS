"""
app_streamlit.py
Painel de gerenciamento (CRUD) para o gerente da assistência técnica.
Lê e grava no Supabase (tabelas: clientes e ordens_servico).

Como executar:
    pip install streamlit supabase pandas
    streamlit run app_streamlit.py

Credenciais (nunca escritas no código): defina em .streamlit/secrets.toml
    SUPABASE_URL = "https://SEU-PROJETO.supabase.co"
    SUPABASE_KEY = "SUA_CHAVE"
    PAINEL_SENHA = "uma-senha"   # opcional: protege o painel com senha
ou como variáveis de ambiente com os mesmos nomes.
"""

import os
import re

import pandas as pd
import streamlit as st
from supabase import create_client

# ---------------------------------------------------------------------
# Configuração da página
# ---------------------------------------------------------------------
st.set_page_config(page_title="Painel - Assistência Técnica", page_icon="🖥️", layout="wide")

# ---------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------
STATUS = ["Aberto", "Em análise", "Aguardando peça", "Concluído", "Entregue"]
REGEX_EMAIL = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
REGEX_CELULAR = re.compile(r"^[0-9]{10,13}$")
COLUNAS_OS = ["OS", "Cliente", "E-mail", "Celular", "Endereço", "Modelo",
              "Problema", "Status", "Abertura", "Atualização", "ID Cliente"]


# ---------------------------------------------------------------------
# Leitura das credenciais: primeiro st.secrets, depois variáveis de ambiente
# ---------------------------------------------------------------------
def obter_config(nome):
    try:
        if nome in st.secrets:
            return str(st.secrets[nome])
    except Exception:
        pass  # sem arquivo secrets.toml: segue para as variáveis de ambiente
    return os.environ.get(nome, "")


# ---------------------------------------------------------------------
# Senha opcional do painel (só é exigida se PAINEL_SENHA estiver definida)
# ---------------------------------------------------------------------
senha_painel = obter_config("PAINEL_SENHA")
if senha_painel and not st.session_state.get("autenticado"):
    st.title("🔒 Painel restrito")
    digitada = st.text_input("Senha", type="password")
    if st.button("Entrar"):
        if digitada == senha_painel:
            st.session_state["autenticado"] = True
            st.rerun()
        else:
            st.error("Senha incorreta.")
    st.stop()


# ---------------------------------------------------------------------
# Conexão com o Supabase (criada uma única vez e reaproveitada)
# ---------------------------------------------------------------------
@st.cache_resource
def conectar(url, chave):
    return create_client(url, chave)


URL = obter_config("SUPABASE_URL")
CHAVE = obter_config("SUPABASE_KEY")
if not URL or not CHAVE:
    st.error("Credenciais não encontradas. Defina `SUPABASE_URL` e `SUPABASE_KEY` em "
             "`.streamlit/secrets.toml` ou como variáveis de ambiente.")
    st.stop()

sb = conectar(URL, CHAVE)


# ---------------------------------------------------------------------
# Funções auxiliares
# ---------------------------------------------------------------------
def erro_amigavel(e):
    """Traduz erros comuns do banco para mensagens compreensíveis."""
    texto = str(e)
    if "23505" in texto or "duplicate key" in texto.lower():
        return "Já existe um cliente cadastrado com este e-mail."
    if "23503" in texto:
        return "Operação bloqueada: o cliente ainda possui ordens de serviço."
    if "row-level security" in texto.lower() or "42501" in texto:
        return "Permissão negada pelo RLS. Use a chave service_role ou crie as políticas."
    return texto


def formatar_data(ts):
    """Converte o timestamp do banco para dd/mm/aaaa hh:mm (horário de Brasília)."""
    if not ts:
        return ""
    return pd.to_datetime(ts, utc=True).tz_convert("America/Sao_Paulo").strftime("%d/%m/%Y %H:%M")


def validar_cliente(nome, endereco, email, celular):
    """Valida os dados do cliente. Retorna lista de erros (vazia = ok)."""
    erros = []
    if not nome:
        erros.append("Informe o nome do cliente.")
    if not endereco:
        erros.append("Informe o endereço.")
    if not email or not REGEX_EMAIL.match(email):
        erros.append("Informe um e-mail com formato válido.")
    if not celular or not REGEX_CELULAR.match(celular):
        erros.append("O celular deve ter apenas números, de 10 a 13 dígitos.")
    return erros


def carregar_ordens():
    """Busca as ordens de serviço já com os dados do cliente (join via FK)."""
    resp = (
        sb.table("ordens_servico")
        .select("id, cliente_id, modelo_computador, problema_relatado, status, "
                "data_abertura, data_atualizacao, clientes(nome, email, celular_whatsapp, endereco)")
        .order("id", desc=True)
        .execute()
    )
    linhas = []
    for r in resp.data:
        c = r.get("clientes") or {}
        linhas.append({
            "OS": r["id"],
            "Cliente": c.get("nome", ""),
            "E-mail": c.get("email", ""),
            "Celular": c.get("celular_whatsapp", ""),
            "Endereço": c.get("endereco", ""),
            "Modelo": r["modelo_computador"],
            "Problema": r["problema_relatado"],
            "Status": r["status"],
            "Abertura": formatar_data(r["data_abertura"]),
            "Atualização": formatar_data(r["data_atualizacao"]),
            "ID Cliente": r["cliente_id"],
        })
    return pd.DataFrame(linhas, columns=COLUNAS_OS)


def carregar_clientes():
    """Lista todos os clientes ordenados por nome."""
    return sb.table("clientes").select("*").order("nome").execute().data


# --- Callbacks de exclusão (rodam antes de a página recarregar) ---------
def excluir_os(os_id):
    try:
        sb.table("ordens_servico").delete().eq("id", os_id).execute()
        st.session_state["flash"] = ("success", f"OS {os_id} excluída com sucesso.")
    except Exception as e:
        st.session_state["flash"] = ("error", f"Não foi possível excluir: {erro_amigavel(e)}")
    st.session_state["conf_os"] = False  # desmarca a confirmação


def excluir_cliente(cliente_id, nome):
    try:
        sb.table("clientes").delete().eq("id", cliente_id).execute()
        st.session_state["flash"] = ("success", f"Cliente {nome} excluído com sucesso.")
    except Exception as e:
        st.session_state["flash"] = ("error", f"Não foi possível excluir: {erro_amigavel(e)}")
    st.session_state["conf_cli"] = False


# ---------------------------------------------------------------------
# Cabeçalho e mensagem de retorno da última ação (flash)
# ---------------------------------------------------------------------
st.title("🖥️ Painel de Gerenciamento")

if "flash" in st.session_state:
    tipo, mensagem = st.session_state.pop("flash")
    getattr(st, tipo)(mensagem)

# ---------------------------------------------------------------------
# Carrega os dados (uma vez por execução da página)
# ---------------------------------------------------------------------
try:
    df_todas = carregar_ordens()
    clientes = carregar_clientes()
except Exception as e:
    st.error(f"Erro ao ler o banco de dados: {erro_amigavel(e)}")
    st.stop()

# ---------------------------------------------------------------------
# Barra lateral: filtros (nome, e-mail e status)
# ---------------------------------------------------------------------
st.sidebar.header("🔎 Filtros")
filtro_nome = st.sidebar.text_input("Nome do cliente", placeholder="Ex.: Maria")
filtro_email = st.sidebar.text_input("E-mail", placeholder="Ex.: maria@email.com")
filtro_status = st.sidebar.multiselect("Status", STATUS, placeholder="Todos")

df = df_todas.copy()
if filtro_nome:
    df = df[df["Cliente"].str.contains(filtro_nome, case=False, na=False, regex=False)]
if filtro_email:
    df = df[df["E-mail"].str.contains(filtro_email, case=False, na=False, regex=False)]
if filtro_status:
    df = df[df["Status"].isin(filtro_status)]

# ---------------------------------------------------------------------
# Abas principais
# ---------------------------------------------------------------------
aba_consultar, aba_cadastrar, aba_editar, aba_indicadores = st.tabs(
    ["📋 Consultar", "➕ Cadastrar", "✏️ Editar/Excluir", "📊 Indicadores"]
)

# =====================================================================
# ABA 1 - CONSULTAR (listar, filtrar e exportar CSV)
# =====================================================================
with aba_consultar:
    st.subheader("Ordens de serviço")
    st.caption(f"Exibindo {len(df)} de {len(df_todas)} ordens (filtros na barra lateral).")
    st.dataframe(df, hide_index=True)

    # Desafio opcional: exportar os dados filtrados em CSV
    # (utf-8-sig para o Excel abrir os acentos corretamente)
    st.download_button(
        "⬇️ Exportar CSV (dados filtrados)",
        data=df.to_csv(index=False).encode("utf-8-sig"),
        file_name="ordens_servico.csv",
        mime="text/csv",
        disabled=df.empty,
    )

# =====================================================================
# ABA 2 - CADASTRAR (nova OS, com cliente existente ou novo)
# =====================================================================
with aba_cadastrar:
    st.subheader("Nova ordem de serviço")

    # Contador usado para "zerar" o formulário após um cadastro com sucesso
    k = st.session_state.setdefault("n_form", 0)

    modo = st.radio("Cliente", ["Cliente já cadastrado", "Novo cliente"], horizontal=True)

    with st.form(f"form_nova_os_{k}"):
        cliente_id = None
        if modo == "Cliente já cadastrado":
            if clientes:
                nomes = {c["id"]: f'{c["nome"]} ({c["email"]})' for c in clientes}
                cliente_id = st.selectbox("Cliente", list(nomes.keys()),
                                          format_func=lambda i: nomes[i], key=f"cli_{k}")
            else:
                st.info("Nenhum cliente cadastrado ainda. Escolha 'Novo cliente'.")
        else:
            col1, col2 = st.columns(2)
            novo_nome = col1.text_input("Nome do cliente", key=f"nome_{k}")
            novo_email = col2.text_input("E-mail", key=f"email_{k}")
            novo_endereco = st.text_input("Endereço", key=f"end_{k}")
            novo_celular = st.text_input("Celular/WhatsApp (somente números)",
                                         placeholder="11987654321", key=f"cel_{k}")

        modelo = st.text_input("Modelo do computador", key=f"modelo_{k}")
        problema = st.text_area("Problema apresentado", key=f"prob_{k}")
        status_novo = st.selectbox("Status inicial", STATUS, index=0, key=f"st_{k}")
        enviado = st.form_submit_button("Cadastrar OS", type="primary")

    if enviado:
        erros = []
        if modo == "Cliente já cadastrado":
            if cliente_id is None:
                erros.append("Selecione um cliente.")
        else:
            novo_nome, novo_endereco = novo_nome.strip(), novo_endereco.strip()
            novo_email, novo_celular = novo_email.strip().lower(), novo_celular.strip()
            erros += validar_cliente(novo_nome, novo_endereco, novo_email, novo_celular)
        if not modelo.strip():
            erros.append("Informe o modelo do computador.")
        if not problema.strip():
            erros.append("Descreva o problema apresentado.")

        if erros:
            st.error("Corrija os itens abaixo:\n\n" + "\n".join(f"- {e}" for e in erros))
        else:
            try:
                if modo == "Novo cliente":
                    novo = sb.table("clientes").insert({
                        "nome": novo_nome, "endereco": novo_endereco,
                        "email": novo_email, "celular_whatsapp": novo_celular,
                    }).execute()
                    cliente_id = novo.data[0]["id"]
                ordem = sb.table("ordens_servico").insert({
                    "cliente_id": cliente_id,
                    "modelo_computador": modelo.strip(),
                    "problema_relatado": problema.strip(),
                    "status": status_novo,
                }).execute()
                st.session_state["flash"] = ("success",
                                             f"OS nº {ordem.data[0]['id']} cadastrada com sucesso!")
                st.session_state["n_form"] = k + 1  # formulário novo (vazio)
                st.rerun()
            except Exception as e:
                st.error(f"Não foi possível cadastrar: {erro_amigavel(e)}")

# =====================================================================
# ABA 3 - EDITAR / EXCLUIR
# =====================================================================
with aba_editar:

    # ---------------- Alterar o status de uma OS ----------------
    st.subheader("Alterar status de uma OS")
    if df_todas.empty:
        st.info("Não há ordens de serviço cadastradas.")
    else:
        rotulos_os = {
            r["OS"]: f'OS {r["OS"]} - {r["Cliente"]} - {r["Modelo"]} ({r["Status"]})'
            for _, r in df_todas.iterrows()
        }
        os_sel = st.selectbox("Ordem de serviço", list(rotulos_os.keys()),
                              format_func=lambda i: rotulos_os[i], key="sel_status_os")
        status_atual = df_todas.loc[df_todas["OS"] == os_sel, "Status"].iloc[0]
        novo_status = st.selectbox("Novo status", STATUS,
                                   index=STATUS.index(status_atual), key=f"novo_status_{os_sel}")
        if st.button("Salvar status"):
            try:
                # data_atualizacao é renovada pelo gatilho do banco (schema.sql)
                sb.table("ordens_servico").update({"status": novo_status}).eq("id", os_sel).execute()
                st.session_state["flash"] = ("success", f"Status da OS {os_sel} alterado para '{novo_status}'.")
                st.rerun()
            except Exception as e:
                st.error(f"Não foi possível atualizar: {erro_amigavel(e)}")

    st.divider()

    # ---------------- Editar dados do cliente ----------------
    st.subheader("Editar dados do cliente")
    if not clientes:
        st.info("Não há clientes cadastrados.")
    else:
        nomes_cli = {c["id"]: f'{c["nome"]} ({c["email"]})' for c in clientes}
        cli_sel = st.selectbox("Cliente", list(nomes_cli.keys()),
                               format_func=lambda i: nomes_cli[i], key="sel_edit_cli")
        atual = next(c for c in clientes if c["id"] == cli_sel)

        # A chave inclui o id do cliente para os campos recarregarem ao trocar de cliente
        with st.form(f"form_edit_cli_{cli_sel}"):
            ed_nome = st.text_input("Nome", value=atual["nome"])
            ed_endereco = st.text_input("Endereço", value=atual["endereco"])
            ed_email = st.text_input("E-mail", value=atual["email"])
            ed_celular = st.text_input("Celular/WhatsApp (somente números)",
                                       value=atual["celular_whatsapp"])
            salvar_cli = st.form_submit_button("Salvar alterações", type="primary")

        if salvar_cli:
            ed_nome, ed_endereco = ed_nome.strip(), ed_endereco.strip()
            ed_email, ed_celular = ed_email.strip().lower(), ed_celular.strip()
            erros = validar_cliente(ed_nome, ed_endereco, ed_email, ed_celular)
            if erros:
                st.error("Corrija os itens abaixo:\n\n" + "\n".join(f"- {e}" for e in erros))
            else:
                try:
                    sb.table("clientes").update({
                        "nome": ed_nome, "endereco": ed_endereco,
                        "email": ed_email, "celular_whatsapp": ed_celular,
                    }).eq("id", cli_sel).execute()
                    st.session_state["flash"] = ("success", "Dados do cliente atualizados.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Não foi possível atualizar: {erro_amigavel(e)}")

    st.divider()

    # ---------------- Excluir (sempre com confirmação) ----------------
    st.subheader("🗑️ Excluir")
    col_os, col_cli = st.columns(2)

    # Excluir uma ordem de serviço
    with col_os:
        st.markdown("**Excluir ordem de serviço**")
        if df_todas.empty:
            st.info("Não há ordens de serviço.")
        else:
            os_del = st.selectbox("Ordem de serviço", list(rotulos_os.keys()),
                                  format_func=lambda i: rotulos_os[i], key="sel_del_os")
            confirma_os = st.checkbox(f"Confirmo a exclusão permanente da OS {os_del}", key="conf_os")
            st.button("Excluir OS", type="primary", disabled=not confirma_os,
                      on_click=excluir_os, args=(os_del,))

    # Excluir um cliente (só se não tiver OS, por causa do ON DELETE RESTRICT)
    with col_cli:
        st.markdown("**Excluir cliente**")
        if not clientes:
            st.info("Não há clientes.")
        else:
            cli_del = st.selectbox("Cliente", list(nomes_cli.keys()),
                                   format_func=lambda i: nomes_cli[i], key="sel_del_cli")
            qtd_os = int((df_todas["ID Cliente"] == cli_del).sum())
            if qtd_os > 0:
                st.warning(f"Este cliente possui {qtd_os} OS. Exclua as ordens primeiro "
                           "(o banco impede apagar clientes com histórico).")
            nome_del = next(c["nome"] for c in clientes if c["id"] == cli_del)
            confirma_cli = st.checkbox(f"Confirmo a exclusão permanente de {nome_del}", key="conf_cli")
            st.button("Excluir cliente", type="primary",
                      disabled=(not confirma_cli) or qtd_os > 0,
                      on_click=excluir_cliente, args=(cli_del, nome_del))

# =====================================================================
# ABA 4 - INDICADORES (métricas e gráfico)
# =====================================================================
with aba_indicadores:
    st.subheader("Indicadores gerais")
    st.caption("Considera todas as ordens, independentemente dos filtros da barra lateral.")

    contagem = df_todas["Status"].value_counts().reindex(STATUS, fill_value=0)

    # Uma métrica para o total e uma para cada status
    colunas = st.columns(len(STATUS) + 1)
    colunas[0].metric("Total de OS", len(df_todas))
    for coluna, status in zip(colunas[1:], STATUS):
        coluna.metric(status, int(contagem[status]))

    st.markdown("**Ordens de serviço por status**")
    st.bar_chart(contagem)

    st.metric("Clientes cadastrados", len(clientes))
