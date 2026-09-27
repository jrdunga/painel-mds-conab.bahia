import streamlit as st
import pandas as pd
import os
import altair as alt
import requests
import unicodedata
import json

# Configuração da página (deve ser o primeiro comando Streamlit)
st.set_page_config(page_title="Dashboard CONAB", page_icon="🌾", layout="wide")

# Caminhos dos arquivos dinâmicos (resolve a pasta 'data' não importando de onde o script for rodado)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "..", "data")

EXCEL_FILE = os.path.join(DATA_DIR, "Relatorio_Global_Agregado.xlsx")

@st.cache_data
def load_geojson():
    """
    Baixa os limites territoriais (GeoJSON) dos municípios da Bahia (código 29)
    direto de um repositório público confíavel.
    """
    url = "https://raw.githubusercontent.com/tbrugz/geodata-br/master/geojson/geojs-29-mun.json"
    try:
        r = requests.get(url)
        data = r.json()
        for f in data['features']:
            name = f['properties']['name']
            # Normalização (sem acentos e tudo maiúsculo) para fazer o 'match' perfeito com os nossos dados
            norm = unicodedata.normalize('NFKD', name).encode('ASCII', 'ignore').decode('utf-8').upper()
            f['properties']['name_norm'] = norm
        return data
    except:
        return None

@st.cache_data
def load_data():
    """
    Carrega os dados e converte silenciosamente para o formato Parquet.
    O formato Parquet é extremamente rápido para dashboards web e garantirá 
    que o app rode liso quando publicado na internet.
    Cache invalidation trigger: 1
    """
    parquet_prod = os.path.join(DATA_DIR, "data_produtos.parquet")
    parquet_forn = os.path.join(DATA_DIR, "data_fornecedores.parquet")
    parquet_cons = os.path.join(DATA_DIR, "data_consumidores.parquet")
    parquet_geral = os.path.join(DATA_DIR, "data_geral.parquet")
    
    if os.path.exists(parquet_prod) and os.path.exists(parquet_forn) and os.path.exists(parquet_cons) and os.path.exists(parquet_geral):
        df_prod = pd.read_parquet(parquet_prod)
        df_forn = pd.read_parquet(parquet_forn)
        df_cons = pd.read_parquet(parquet_cons)
        df_geral = pd.read_parquet(parquet_geral)
    else:
        df_prod = pd.read_excel(EXCEL_FILE, sheet_name="Produtos")
        df_forn = pd.read_excel(EXCEL_FILE, sheet_name="Fornecedores")
        df_cons = pd.read_excel(EXCEL_FILE, sheet_name="Consumidores")
        try:
            df_geral = pd.read_excel(EXCEL_FILE, sheet_name="Geral")
        except:
            df_geral = pd.DataFrame()
            
        for df in [df_prod, df_forn, df_cons, df_geral]:
            if not df.empty:
                for col in df.select_dtypes(include=['object']).columns:
                    df[col] = df[col].astype(str)
                    
        # --- APLICA DICIONÁRIO DE PRODUTOS ---
        try:
            dic_file = os.path.join(DATA_DIR, "dicionario_produtos.json")
            if os.path.exists(dic_file):
                dic_df = pd.read_json(dic_file)
                mapping = dict(zip(dic_df["Produto_Original"].str.strip(), dic_df["Produto_Global"].str.strip()))
                
                col_p = next((c for c in df_prod.columns if "produto" in c.lower() and "quantidade" not in c.lower()), None)
                if col_p:
                    df_prod[col_p] = df_prod[col_p].str.strip().map(mapping).fillna(df_prod[col_p].str.strip())
        except Exception as e:
            pass # Falha silenciosa, segue sem o dicionário
        
        df_prod.to_parquet(parquet_prod)
        df_forn.to_parquet(parquet_forn)
        df_cons.to_parquet(parquet_cons)
        if not df_geral.empty:
            df_geral.to_parquet(parquet_geral)
        
    return df_prod, df_forn, df_cons, df_geral

def main():
    st.title("🌾 Dashboard de Distribuição - CONAB")
    st.markdown("Visualização consolidada do histórico de Produtos, Fornecedores e Consumidores na Bahia.")
    
    # Carrega os dados
    try:
        df_prod, df_forn, df_cons, df_geral = load_data()
    except Exception as e:
        st.error("Erro ao carregar dados. O arquivo `Relatorio_Global_Agregado.xlsx` já foi gerado?")
        st.code(str(e))
        return
        
    # --- BARRA LATERAL (FILTROS) ---
    st.sidebar.header("Filtros Globais")
    
    # Pega todos os anos disponíveis (usando a tabela de produtos como base)
    if "Ano" in df_prod.columns:
        anos_disponiveis = sorted(df_prod["Ano"].dropna().unique().tolist(), reverse=True)
        ano_selecionado = st.sidebar.multiselect("Selecione o(s) Ano(s):", options=anos_disponiveis, default=anos_disponiveis)
    else:
        ano_selecionado = []
        
    if "Município" in df_prod.columns:
        municipios_disponiveis = sorted(df_prod["Município"].dropna().unique().tolist())
        municipio_selecionado = st.sidebar.multiselect("Selecione o(s) Município(s):", options=municipios_disponiveis, default=[])
    else:
        municipio_selecionado = []
        
    # Carrega a Cesta Básica
    cesta_basica_file = os.path.join(DATA_DIR, "cesta_basica.json")
    produtos_cesta = []
    if os.path.exists(cesta_basica_file):
        try:
            import json
            with open(cesta_basica_file, 'r', encoding='utf-8') as f:
                produtos_cesta = json.load(f)
        except:
            pass

    st.sidebar.markdown("---")
    somente_cesta = False
    if produtos_cesta:
        somente_cesta = st.sidebar.toggle("🛒 Mostrar apenas Cesta Básica")

    # Identifica a coluna do Produto para criar o filtro
    col_prod_nome = next((c for c in df_prod.columns if "produto" in c.lower() and "quantidade" not in c.lower()), None)
    if col_prod_nome:
        produtos_disponiveis = sorted(df_prod[col_prod_nome].dropna().unique().tolist())
        produto_selecionado = st.sidebar.multiselect("Selecione o(s) Produto(s) para Análise Cruzada:", options=produtos_disponiveis, default=[])
    else:
        produto_selecionado = []
        
    # Aplica os filtros nos DataFrames
    def filtrar_df(df):
        if df.empty: return df
        df_filtrado = df.copy()
        if ano_selecionado and "Ano" in df_filtrado.columns:
            df_filtrado = df_filtrado[df_filtrado["Ano"].isin(ano_selecionado)]
        if municipio_selecionado and "Município" in df_filtrado.columns:
            df_filtrado = df_filtrado[df_filtrado["Município"].isin(municipio_selecionado)]
            
        # Filtro Cruzado: se Cesta Básica ou Produto selecionado, filtra os projetos que os possuem
        col_razao_prod = next((c for c in df_prod.columns if "razão social" in c.lower() or "entidade" in c.lower()), None)
        if (somente_cesta or produto_selecionado) and col_prod_nome and col_razao_prod:
            # Encontra as Entidades/Razões Sociais que fornecem os produtos selecionados
            df_temp_prod = df_prod.copy()
            if somente_cesta:
                df_temp_prod = df_temp_prod[df_temp_prod[col_prod_nome].isin(produtos_cesta)]
            if produto_selecionado:
                df_temp_prod = df_temp_prod[df_temp_prod[col_prod_nome].isin(produto_selecionado)]
            entidades_validas = df_temp_prod[col_razao_prod].dropna().unique().tolist()
            
            # Se a aba atual tiver a coluna de Produto (ex: Aba Produtos), filtra o produto diretamente
            if col_prod_nome in df_filtrado.columns:
                if somente_cesta:
                    df_filtrado = df_filtrado[df_filtrado[col_prod_nome].isin(produtos_cesta)]
                if produto_selecionado:
                    df_filtrado = df_filtrado[df_filtrado[col_prod_nome].isin(produto_selecionado)]
            else:
                # Se for aba Fornecedores ou Geral, filtra pela lista de Entidades cruzadas!
                col_razao_atual = next((c for c in df_filtrado.columns if "razão social" in c.lower() or "entidade" in c.lower()), None)
                if col_razao_atual:
                    df_filtrado = df_filtrado[df_filtrado[col_razao_atual].isin(entidades_validas)]
                    
        return df_filtrado
        
    df_prod_f = filtrar_df(df_prod)
    df_forn_f = filtrar_df(df_forn)
    df_cons_f = filtrar_df(df_cons)
    df_geral_f = filtrar_df(df_geral)
    
    # --- KPIs GERAIS ---
    st.markdown("### Visão Geral")
    col1, col2, col3 = st.columns(3)
    
    total_municipios = df_prod["Município"].nunique() if "Município" in df_prod.columns else 0
    
    # Tenta achar a coluna de Razão Social baseada no padrão do agregador
    col_razao_prod = next((c for c in df_prod.columns if "razão social" in c.lower() or "entidade" in c.lower()), None)
    total_entidades = df_prod[col_razao_prod].nunique() if col_razao_prod else 0
    
    total_produtos = len(df_prod)
    
    col1.metric("Municípios Atendidos", total_municipios)
    col2.metric("Entidades/Cooperativas Únicas", total_entidades)
    col3.metric("Lotes/Ocorrências de Produtos", f"{total_produtos:,}".replace(",", "."))
    
    # --- VISÃO GERAL FINANCEIRA (POR ANO) ---
    col_previsto = next((c for c in df_forn_f.columns if "previsto" in c.lower() and "valor" in c.lower()), None)
    col_executado = next((c for c in df_forn_f.columns if "executado" in c.lower() and "valor" in c.lower()), None)
    
    # Função robusta para limpar valores monetários que possam estar como texto ("R$ 1.234,56")
    def limpa_moeda(val):
        if pd.isna(val): return 0.0
        if isinstance(val, (int, float)): return float(val)
        s = str(val).upper().replace("R$", "").replace(" ", "").strip()
        if s == "" or s == "NAN" or s == "N/A" or s == "NONE": return 0.0
        if "," in s and "." in s: s = s.replace(".", "").replace(",", ".")
        elif "," in s: s = s.replace(",", ".")
        try: return float(s)
        except: return 0.0

    # Identifica a coluna de Valor Total / Estimado na aba Geral
    col_previsto_geral = next((c for c in df_geral.columns if ("previsto" in c.lower() or "total" in c.lower() or "aquisição" in c.lower()) and "quantidade" not in c.lower() and "valor" in c.lower()), None)

    if col_previsto_geral and "Ano" in df_geral.columns and not df_geral.empty:
        # --- GRÁFICO ÚNICO: EVOLUÇÃO FINANCEIRA GERAL VS CESTA BÁSICA ---
        st.markdown("#### Evolução Financeira Anual (Estimado: Geral vs Cesta Básica)")
        
        # 1. Total Geral (Imune a filtros, usando Aba Geral)
        df_fin_geral = df_geral[["Ano", col_previsto_geral]].copy()
        df_fin_geral[col_previsto_geral] = df_fin_geral[col_previsto_geral].apply(limpa_moeda)
        df_fin_geral_ano = df_fin_geral.groupby("Ano")[col_previsto_geral].sum().reset_index()
        df_fin_geral_ano["Categoria"] = "Todos os Produtos"
        
        # 2. Total Apenas Cesta Básica
        entidades_cesta_geral = []
        if produtos_cesta and col_prod_nome and col_razao_prod:
            entidades_cesta_geral = df_prod[df_prod[col_prod_nome].isin(produtos_cesta)][col_razao_prod].dropna().unique().tolist()
            
        col_razao_geral = next((c for c in df_geral.columns if "razão social" in c.lower() or "entidade" in c.lower()), None)
        
        if col_razao_geral and entidades_cesta_geral:
            df_fin_cesta = df_geral[df_geral[col_razao_geral].isin(entidades_cesta_geral)][["Ano", col_previsto_geral]].copy()
            df_fin_cesta[col_previsto_geral] = df_fin_cesta[col_previsto_geral].apply(limpa_moeda)
            df_fin_cesta_ano = df_fin_cesta.groupby("Ano")[col_previsto_geral].sum().reset_index()
            df_fin_cesta_ano["Categoria"] = "Cesta Básica"
        else:
            # Se não tiver cesta básica, cria dataframe vazio
            df_fin_cesta_ano = pd.DataFrame(columns=["Ano", col_previsto_geral, "Categoria"])
            
        # 3. Junta os dois e plota
        df_chart_fin = pd.concat([df_fin_geral_ano, df_fin_cesta_ano], ignore_index=True)
        df_chart_fin = df_chart_fin.rename(columns={col_previsto_geral: "Montante (R$)"})
        
        chart_fin = alt.Chart(df_chart_fin).mark_bar().encode(
            x=alt.X("Ano:O", title="Ano", axis=alt.Axis(labelAngle=0)),
            xOffset="Categoria:N",
            y=alt.Y("Montante (R$):Q", title="Valor Total Estimado (R$)"),
            color=alt.Color("Categoria:N", title="Legenda", scale=alt.Scale(domain=["Todos os Produtos", "Cesta Básica"], range=["#3b82f6", "#10b981"])),
            tooltip=[
                alt.Tooltip("Ano:O", title="Ano"),
                alt.Tooltip("Categoria:N", title="Categoria"),
                alt.Tooltip("Montante (R$):Q", title="Valor Total (R$)", format=",.2f")
            ]
        ).properties(height=600)
        
        st.altair_chart(chart_fin, use_container_width=True)

    st.markdown("---")
    
    # --- ABAS INTERATIVAS ---
    aba4, aba1 = st.tabs(["🗺️ Regiões Territoriais", "🍎 Produtos"])
    
    with aba1:
        st.subheader("Análise de Produtos")
        
        if not df_prod_f.empty and col_prod_nome:
            
            # --- NOVO GRÁFICO: INCIDÊNCIA POR PRODUTO ---
            st.markdown("### 📊 Incidência por Produto")
            st.write("Ranking dos produtos com maior número de ocorrências (lotes/projetos). **Clique em uma coluna para ver a tabela detalhada!**")
            
            df_inc = df_prod_f.groupby(col_prod_nome).size().reset_index(name="Incidência")
            # Pega os Top 20 para o gráfico não ficar espremido
            df_inc = df_inc.sort_values(by="Incidência", ascending=False).head(20)
            
            click_prod = alt.selection_point(name="click_prod", fields=[col_prod_nome])
            
            chart_inc = alt.Chart(df_inc).mark_bar(color="#3b82f6").encode(
                x=alt.X(f"{col_prod_nome}:N", sort="-y", title="Produto", axis=alt.Axis(labelAngle=-45)),
                y=alt.Y("Incidência:Q", title="Qtd. Ocorrências"),
                opacity=alt.condition(click_prod, alt.value(1.0), alt.value(0.5)),
                tooltip=[
                    alt.Tooltip(f"{col_prod_nome}:N", title="Produto"),
                    alt.Tooltip("Incidência:Q", title="Ocorrências")
                ]
            ).add_params(click_prod).properties(height=350)
            
            event = st.altair_chart(chart_inc, use_container_width=True, on_select="rerun")
            
            # Lógica para exibir a tabela de detalhamento caso um produto seja clicado
            selected_items = event.selection.get("click_prod", [])
            if selected_items:
                sel_prod_name = selected_items[0].get(col_prod_nome)
                if sel_prod_name:
                    st.markdown(f"#### 🔎 Tabela Detalhada: {sel_prod_name}")
                    df_detalhe = df_prod_f[df_prod_f[col_prod_nome] == sel_prod_name].copy()
                    
                    # Filtra colunas de interesse (Cidades, Entidades, Valores)
                    col_razao_det = next((c for c in df_prod_f.columns if "razão social" in c.lower() or "entidade" in c.lower()), "Razão Social")
                    col_mun_det = "Município" if "Município" in df_prod_f.columns else None
                    col_prev_det = next((c for c in df_prod_f.columns if "previsto" in c.lower() and "valor" in c.lower()), None)
                    
                    cols_show = []
                    if col_mun_det: cols_show.append(col_mun_det)
                    cols_show.append(col_razao_det)
                    if col_prev_det:
                        df_detalhe[col_prev_det] = df_detalhe[col_prev_det].apply(lambda x: f"R$ {x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if pd.notnull(x) else "R$ 0,00")
                        cols_show.append(col_prev_det)
                        
                    st.dataframe(df_detalhe[cols_show].dropna(how="all").reset_index(drop=True), use_container_width=True)

            # --- NOVO GRÁFICO 2: VALOR TOTAL POR PRODUTO ---
            st.markdown("---")
            st.markdown("### 💰 Valor Total Estimado por Produto")
            st.write("Ranking dos produtos com maior valor financeiro estimado associado. **Clique em uma coluna para ver a tabela detalhada!**")
            
            col_prev = next((c for c in df_prod_f.columns if "previsto" in c.lower() and "valor" in c.lower()), None)
            if col_prev:
                def limpa_moeda_local(val):
                    if pd.isna(val): return 0.0
                    if isinstance(val, (int, float)): return float(val)
                    s = str(val).upper().replace("R$", "").replace(" ", "").strip()
                    if s in ["", "NAN", "N/A", "NONE"]: return 0.0
                    if "," in s and "." in s: s = s.replace(".", "").replace(",", ".")
                    elif "," in s: s = s.replace(",", ".")
                    try: return float(s)
                    except: return 0.0
                    
                df_val_temp = df_prod_f.copy()
                df_val_temp[col_prev] = df_val_temp[col_prev].apply(limpa_moeda_local)
                
                df_val = df_val_temp.groupby(col_prod_nome)[col_prev].sum().reset_index(name="Valor Total")
                df_val = df_val.sort_values(by="Valor Total", ascending=False).head(20)
                
                click_val = alt.selection_point(name="click_val", fields=[col_prod_nome])
                
                chart_val = alt.Chart(df_val).mark_bar(color="#10b981").encode(
                    x=alt.X(f"{col_prod_nome}:N", sort="-y", title="Produto", axis=alt.Axis(labelAngle=-45)),
                    y=alt.Y("Valor Total:Q", title="Valor Total (R$)"),
                    opacity=alt.condition(click_val, alt.value(1.0), alt.value(0.5)),
                    tooltip=[
                        alt.Tooltip(f"{col_prod_nome}:N", title="Produto"),
                        alt.Tooltip("Valor Total:Q", title="Valor Estimado (R$)", format=",.2f")
                    ]
                ).add_params(click_val).properties(height=350)
                
                event_val = st.altair_chart(chart_val, use_container_width=True, on_select="rerun")
                
                selected_items_val = event_val.selection.get("click_val", [])
                if selected_items_val:
                    sel_prod_name_val = selected_items_val[0].get(col_prod_nome)
                    if sel_prod_name_val:
                        st.markdown(f"#### 🔎 Tabela Detalhada: {sel_prod_name_val}")
                        df_detalhe_val = df_prod_f[df_prod_f[col_prod_nome] == sel_prod_name_val].copy()
                        
                        cols_show_val = []
                        if col_mun_det: cols_show_val.append(col_mun_det)
                        cols_show_val.append(col_razao_det)
                        df_detalhe_val[col_prev] = df_detalhe_val[col_prev].apply(lambda x: f"R$ {x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if pd.notnull(x) else "R$ 0,00")
                        cols_show_val.append(col_prev)
                            
                        st.dataframe(df_detalhe_val[cols_show_val].dropna(how="all").reset_index(drop=True), use_container_width=True)
            else:
                st.warning("Coluna de valor financeiro não encontrada na base de Produtos.")
            
        else:
            st.warning("Nenhum dado de Produto encontrado para os filtros selecionados.")
            
    with aba4:
        st.subheader("Análise Geográfica")
        st.markdown("### 🗺️ Mapa por Regiões Territoriais")
        st.write("Visualize a distribuição da CONAB agregada por **Região Territorial**. Clique em uma região colorida para detalhar as cidades e produtos.")
        
        def get_regioes_mapping():
            caminho = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "região_territorial.json")
            try:
                with open(caminho, 'r', encoding='utf-8') as f:
                    regioes_json = json.load(f)
                
                # Inverte o dicionario {Regiao: [mun1, mun2]} para {Mun_Norm: Regiao}
                mapping = {}
                for regiao, cidades in regioes_json.items():
                    for cid in cidades:
                        norm = unicodedata.normalize('NFKD', cid).encode('ASCII', 'ignore').decode('utf-8').upper()
                        mapping[norm] = regiao
                return mapping
            except Exception as e:
                return None

        geojson_data = load_geojson()
        regioes_map = get_regioes_mapping()
        
        if geojson_data and regioes_map:
            df_mapa_base = df_prod_f.copy()
            
            # Normaliza municipio para buscar a região
            df_mapa_base["Mun_Norm"] = df_mapa_base["Município"].apply(lambda x: unicodedata.normalize('NFKD', str(x)).encode('ASCII', 'ignore').decode('utf-8').upper())
            
            # Atribui a Região
            df_mapa_base["Regiao_Territorial"] = df_mapa_base["Mun_Norm"].map(regioes_map).fillna("Desconhecida")
            
            # Agrupa métricas POR REGIÃO
            map_df = df_mapa_base.groupby("Regiao_Territorial").agg(
                Qtd_Lotes=("Regiao_Territorial", "count"),
                Qtd_Cidades=("Município", "nunique"),
                Qtd_Produtos_Distintos=(col_prod_nome, "nunique")
            ).reset_index()
            
            # --- CÁLCULO DO VALOR FINANCEIRO POR REGIÃO ---
            col_exec = next((c for c in df_forn_f.columns if "executado" in c.lower() and "valor" in c.lower()), None)
            if col_exec and not df_forn_f.empty:
                df_forn_mapa = df_forn_f.copy()
                df_forn_mapa["Mun_Norm"] = df_forn_mapa["Município"].apply(lambda x: unicodedata.normalize('NFKD', str(x)).encode('ASCII', 'ignore').decode('utf-8').upper() if pd.notna(x) else "")
                df_forn_mapa["Regiao_Territorial"] = df_forn_mapa["Mun_Norm"].map(regioes_map).fillna("Desconhecida")
                
                def limpa_moeda_mapa(val):
                    if pd.isna(val): return 0.0
                    if isinstance(val, (int, float)): return float(val)
                    s = str(val).upper().replace("R$", "").replace(" ", "").strip()
                    if s in ["", "NAN", "N/A", "NONE"]: return 0.0
                    if "," in s and "." in s: s = s.replace(".", "").replace(",", ".")
                    elif "," in s: s = s.replace(",", ".")
                    try: return float(s)
                    except: return 0.0
                    
                df_forn_mapa[col_exec] = df_forn_mapa[col_exec].apply(limpa_moeda_mapa)
                df_fin_regiao = df_forn_mapa.groupby("Regiao_Territorial")[col_exec].sum().reset_index(name="Valor_Total")
                map_df = pd.merge(map_df, df_fin_regiao, on="Regiao_Territorial", how="left").fillna(0)
            else:
                map_df["Valor_Total"] = 0.0
            
            # Cria um df de lookup estendido para o Altair repassar os dados da região para todos os polígonos das cidades
            lookup_df = pd.DataFrame(list(regioes_map.keys()), columns=["Mun_Norm"])
            lookup_df["Regiao_Territorial"] = lookup_df["Mun_Norm"].map(regioes_map)
            
            # Faz o merge para colar os números da região em todas as cidades daquela região
            lookup_df = pd.merge(lookup_df, map_df, on="Regiao_Territorial", how="left").fillna(0)
            
            geo_source = alt.InlineData(values=geojson_data, format=alt.DataFormat(property='features', type='json'))
            
            # 1. Camada Base: Pinta TODO o estado da Bahia de cinza
            base_map = alt.Chart(geo_source).mark_geoshape(
                fill='lightgray', stroke='white', strokeWidth=0.2
            )
            
            click = alt.selection_point(name="region_click", fields=['properties.name_norm'])
            
            # 2. Camada Quente (Cores por bloco da Região)
            # Dica visual: Retirando as bordas internas das cidades para criar um bloco territorial contínuo
            heat_map = alt.Chart(geo_source).mark_geoshape(
                strokeWidth=0.0 # Remove a linha delimitadora interna
            ).encode(
                color=alt.Color('Qtd_Cidades:Q', scale=alt.Scale(scheme='teals'), title='Cidades Atendidas na Região', legend=alt.Legend(orient='bottom')),
                opacity=alt.condition(click, alt.value(1.0), alt.value(0.3)),
                tooltip=[
                    alt.Tooltip('Regiao_Territorial:N', title='Região Territorial'),
                    alt.Tooltip('Qtd_Cidades:Q', title='Qtd Cidades Atendidas'),
                    alt.Tooltip('Qtd_Produtos_Distintos:Q', title='Qtd Produtos Diferentes'),
                    alt.Tooltip('Valor_Total:Q', title='Valor Associado (R$)', format=",.2f")
                ]
            ).transform_lookup(
                lookup='properties.name_norm',
                from_=alt.LookupData(lookup_df, 'Mun_Norm', ['Regiao_Territorial', 'Qtd_Cidades', 'Qtd_Produtos_Distintos', 'Qtd_Lotes', 'Valor_Total'])
            ).add_params(click)
            
            col_mapa, col_lista = st.columns([2, 1])
            
            with col_mapa:
                map_layer = (base_map + heat_map).project(type='mercator').properties(height=500)
                event_map = st.altair_chart(map_layer, use_container_width=True, on_select="rerun")
            
            with col_lista:
                st.markdown("#### Lista de Regiões")
                df_lista = map_df.sort_values(by="Regiao_Territorial").reset_index(drop=True)
                df_lista.index = df_lista.index + 1
                df_lista = df_lista[["Regiao_Territorial", "Qtd_Cidades"]].rename(columns={"Regiao_Territorial": "Região", "Qtd_Cidades": "Cidades"})
                event_list = st.dataframe(df_lista, use_container_width=True, height=500, on_select="rerun", selection_mode="single-row")
                
            st.markdown("---")
            st.markdown("#### Tabela de Detalhamento")
            
            regiao_clicada = None
            if event_list and len(event_list.selection.get("rows", [])) > 0:
                row_idx = event_list.selection["rows"][0]
                regiao_clicada = df_lista.iloc[row_idx]["Região"]
            elif event_map and len(event_map.selection.get("region_click", [])) > 0:
                selecionado_norm = list(event_map.selection["region_click"][0].values())[0]
                regiao_clicada = regioes_map.get(selecionado_norm)
                
            if regiao_clicada:
                st.success(f"📍 **{regiao_clicada}**")
                
                df_regiao_prod = df_mapa_base[df_mapa_base["Regiao_Territorial"] == regiao_clicada]
                df_regiao_forn = df_forn_mapa[df_forn_mapa["Regiao_Territorial"] == regiao_clicada] if 'df_forn_mapa' in locals() else pd.DataFrame()
                
                tab1, tab2 = st.tabs(["🍎 Produtos", "🏙️ Cidades"])
                
                with tab1:
                    if not df_regiao_prod.empty:
                        prod_incidencia = df_regiao_prod[col_prod_nome].value_counts().reset_index()
                        prod_incidencia.columns = ["Produto", "Nº de Incidências"]
                        prod_incidencia = prod_incidencia[prod_incidencia["Nº de Incidências"] > 0]
                        
                        def limpa_moeda_generico(val):
                            if pd.isna(val): return 0.0
                            if isinstance(val, (int, float)): return float(val)
                            s = str(val).upper().replace("R$", "").replace(" ", "").strip()
                            if s in ["", "NAN", "N/A", "NONE"]: return 0.0
                            if "," in s and "." in s: s = s.replace(".", "").replace(",", ".")
                            elif "," in s: s = s.replace(",", ".")
                            try: return float(s)
                            except: return 0.0
                            
                        col_valor_prod = next((c for c in df_regiao_prod.columns if "valor" in c.lower() and ("total" in c.lower() or "executado" in c.lower() or "aquisição" in c.lower())), None)
                        
                        if col_valor_prod:
                            df_regiao_prod_temp = df_regiao_prod.copy()
                            df_regiao_prod_temp[col_valor_prod] = df_regiao_prod_temp[col_valor_prod].apply(limpa_moeda_generico)
                            prod_valor = df_regiao_prod_temp.groupby(col_prod_nome)[col_valor_prod].sum().reset_index()
                            prod_valor.columns = ["Produto", "Valor Total (R$)"]
                            prod_resumo = pd.merge(prod_incidencia, prod_valor, on="Produto", how="left").fillna(0)
                        else:
                            col_prod_forn = next((c for c in df_regiao_forn.columns if "produto" in c.lower() and "quantidade" not in c.lower()), None) if not df_regiao_forn.empty else None
                            if col_prod_forn and col_exec:
                                prod_valor = df_regiao_forn.groupby(col_prod_forn)[col_exec].sum().reset_index()
                                prod_valor.columns = ["Produto", "Valor Total (R$)"]
                                prod_resumo = pd.merge(prod_incidencia, prod_valor, on="Produto", how="left").fillna(0)
                            else:
                                prod_resumo = prod_incidencia
                                prod_resumo["Valor Total (R$)"] = 0.0
                                
                        st.dataframe(prod_resumo, hide_index=True, use_container_width=True)
                    else:
                        st.write("Sem dados de produtos.")
                        
                with tab2:
                    if not df_regiao_prod.empty:
                        cid_prods = df_regiao_prod.groupby("Município")[col_prod_nome].nunique().reset_index()
                        cid_prods.columns = ["Município", "Nº de Produtos Diferentes"]
                        cid_prods = cid_prods[cid_prods["Nº de Produtos Diferentes"] > 0]
                        
                        col_valor_prod = next((c for c in df_regiao_prod.columns if "valor" in c.lower() and ("total" in c.lower() or "executado" in c.lower() or "aquisição" in c.lower())), None)
                        
                        if col_valor_prod:
                            df_regiao_prod_temp = df_regiao_prod.copy()
                            df_regiao_prod_temp[col_valor_prod] = df_regiao_prod_temp[col_valor_prod].apply(limpa_moeda_generico)
                            cid_valor = df_regiao_prod_temp.groupby("Município")[col_valor_prod].sum().reset_index()
                            cid_valor.columns = ["Município", "Valor Total (R$)"]
                            cid_resumo = pd.merge(cid_prods, cid_valor, on="Município", how="left").fillna(0)
                        else:
                            if col_exec and not df_regiao_forn.empty:
                                cid_valor = df_regiao_forn.groupby("Município")[col_exec].sum().reset_index()
                                cid_valor.columns = ["Município", "Valor Total (R$)"]
                                cid_resumo = pd.merge(cid_prods, cid_valor, on="Município", how="left").fillna(0)
                            else:
                                cid_resumo = cid_prods
                                cid_resumo["Valor Total (R$)"] = 0.0
                                
                        st.dataframe(cid_resumo, hide_index=True, use_container_width=True)
                    else:
                        st.write("Sem dados de cidades.")
            else:
                st.info("👈 Clique em uma região do mapa ou na lista ao lado para visualizar a tabela de Cidades e Produtos.")
        else:
            st.warning("Erro: Não foi possível carregar o mapa geográfico ou o arquivo 'região_territorial.json'. Verifique a pasta 'data'.")
            
        st.markdown("---")
if __name__ == '__main__':
    main()
