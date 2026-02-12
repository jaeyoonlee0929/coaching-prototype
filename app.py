import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import openai
import re

# --- 페이지 설정 ---
st.set_page_config(
    page_title="Executive Leadership Coach",
    page_icon="👑",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- API Key 설정 ---
try:
    OPENAI_API_KEY = st.secrets["JYL"]
except (FileNotFoundError, KeyError):
    OPENAI_API_KEY = None

# --- 역량 그룹 정의 ---
COMPETENCY_GROUPS = {
    "SKMS에 대한 확신과 열정": ["SKMS에 대한 확신", "구성원/이해관계자 행복 추구", "패기/솔선수범", "Integrity"],
    "혁신적 전략 수립": ["전략적 Insight", "담당 조직 변화 Design", "비전 공유/지속적 변화 추진"],
    "과감한 돌파와 실행": ["SUPEX 목표 설정", "내·외부 폭넓은 협업", "신속한 실행 및 성과 창출"],
    "VWBE 문화구축": ["구성원 VWBE환경 조성 활동 지원", "신뢰 기반의 협력 촉진", "패기 인재 인정/육성"]
}

# --- 데이터 로드 및 전처리 ---
@st.cache_data
def load_data(file):
    try:
        if file.name.endswith('.csv'):
            df = pd.read_csv(file)
        else:
            df = pd.read_excel(file)
        return df
    except Exception as e:
        st.error(f"파일 로드 오류: {e}")
        return None

def normalize_text(text):
    return re.sub(r'[\s\·\.\,\-\_]', '', str(text)).lower()

def parse_columns(df):
    """
    컬럼명을 분석하여 점수(Numeric)와 주관식(Text)을 구분하고,
    대상(구성원/동료)과 연도를 분류합니다.
    """
    member_scores = {} 
    peer_scores = {}   
    member_texts = {}  # 구성원 주관식
    peer_texts = {}    # 동료 주관식
    meta_cols = []
    
    peer_pattern = re.compile(r"^(.*)_동료_(\d{2}년)$")
    member_pattern = re.compile(r"^(.*)_(\d{2}년)$")
    
    for col in df.columns:
        # 1. 동료 데이터 확인
        peer_match = peer_pattern.match(col)
        if peer_match:
            year = peer_match.group(2)
            if pd.api.types.is_numeric_dtype(df[col]):
                if year not in peer_scores: peer_scores[year] = []
                peer_scores[year].append(col)
            else:
                if year not in peer_texts: peer_texts[year] = []
                peer_texts[year].append(col)
            continue
            
        # 2. 구성원 데이터 확인
        member_match = member_pattern.match(col)
        if member_match:
            year = member_match.group(2)
            if pd.api.types.is_numeric_dtype(df[col]):
                if year not in member_scores: member_scores[year] = []
                member_scores[year].append(col)
            else:
                if year not in member_texts: member_texts[year] = []
                member_texts[year].append(col)
        else:
            meta_cols.append(col)
            
    return meta_cols, member_scores, peer_scores, member_texts, peer_texts

def custom_metric(label, value, delta=None, delta_color="normal", show_arrow=False):
    """HTML 커스텀 메트릭"""
    delta_html = ""
    if delta:
        try:
            match = re.search(r"([+-]?\d+\.?\d*)", str(delta))
            if match:
                delta_val = float(match.group(1))
                text_color = "#666"
                arrow_char = ""
                
                if delta_val > 0:
                    if delta_color == "normal": text_color = "#09ab3b"
                    elif delta_color == "inverse": text_color = "#ff2b2b"
                    arrow_char = "↑" if show_arrow else ""
                elif delta_val < 0:
                    if delta_color == "normal": text_color = "#ff2b2b"
                    elif delta_color == "inverse": text_color = "#09ab3b"
                    arrow_char = "↓" if show_arrow else ""
                
                delta_str = f"{arrow_char} {delta}" if show_arrow else f"{delta}"
                delta_html = f'<span style="color: {text_color}; font-size: 1rem; margin-left: 8px; font-weight: 600;">{delta_str}</span>'
        except:
            delta_html = f'<span style="color: #666; font-size: 1rem; margin-left: 8px;">{delta}</span>'

    html_code = f"""
    <div style="display: flex; flex-direction: column; margin-bottom: 1.5rem;">
        <span style="font-size: 1rem; font-weight: 500; margin-bottom: 4px; opacity: 0.8;">{label}</span>
        <div style="display: flex; align-items: baseline;">
            <span style="font-size: 2.2rem; font-weight: 700;">{value}</span>
            {delta_html}
        </div>
    </div>
    """
    st.markdown(html_code, unsafe_allow_html=True)

# --- 사이드바 ---
with st.sidebar:
    st.title("👑 임원 리더십 코칭")
    st.info("리더십 진단 결과(Excel)를 업로드하세요.")
    uploaded_file = st.file_uploader("엑셀 파일 업로드", type=["xlsx", "csv"])
    
    selected_leader = None
    df = None
    
    if uploaded_file:
        df = load_data(uploaded_file)
        if df is not None:
            name_col = next((c for c in df.columns if "이름" in c or "Name" in c), df.columns[1])
            leader_list = df[name_col].unique().tolist()
            selected_leader_name = st.selectbox("대상 임원 선택", leader_list)
            leader_data = df[df[name_col] == selected_leader_name].iloc[0]
            
            if not OPENAI_API_KEY:
                st.warning("⚠️ API Key 미설정 (AI 기능 제한)")

# --- 메인 로직 ---
if df is not None and selected_leader_name:
    # 1. 컬럼 파싱
    meta_cols, member_map, peer_map, member_text_map, peer_text_map = parse_columns(df)
    sorted_years = sorted(member_map.keys())
    latest_year = sorted_years[-1]
    
    # 2. 역량 매핑 & 점수 추출
    raw_competencies = [col.replace(f"_{latest_year}", "") for col in member_map[latest_year]]
    norm_comp_map = {normalize_text(c): c for c in raw_competencies}
    
    grouped_scores = {}
    detailed_scores = {} 

    for year in sorted_years:
        year_group_data = {}
        year_detail_data = {}
        
        for col in member_map[year]:
            if "_동료_" in col: continue
            comp_name = col.replace(f"_{year}", "")
            val = leader_data[col]
            if pd.notna(val) and val > 0:
                year_detail_data[comp_name] = val
            else:
                year_detail_data[comp_name] = 0
        detailed_scores[year] = year_detail_data
        
        for group_name, sub_items in COMPETENCY_GROUPS.items():
            scores = []
            for item in sub_items:
                norm_item = normalize_text(item)
                target_col = None
                if item in year_detail_data: target_col = item
                elif norm_item in norm_comp_map and norm_comp_map[norm_item] in year_detail_data:
                    target_col = norm_comp_map[norm_item]
                
                if target_col:
                    val = year_detail_data[target_col]
                    if val > 0: scores.append(val)
            
            if scores: year_group_data[group_name] = sum(scores) / len(scores)
            else: year_group_data[group_name] = 0.0
        
        grouped_scores[year] = year_group_data

    # Common Stats
    avg_scores = {}
    for y in sorted_years:
        vals = [v for v in detailed_scores[y].values() if v > 0]
        avg_scores[y] = sum(vals) / len(vals) if vals else 0

    curr_score = avg_scores[latest_year]
    prev_year = sorted_years[-2] if len(sorted_years) > 1 else None
    delta_total = (curr_score - avg_scores[prev_year]) if prev_year else 0
    
    latest_series = pd.Series(detailed_scores[latest_year])
    latest_series = latest_series[latest_series > 0]
    
    if not latest_series.empty:
        top_comp = latest_series.idxmax()
        bot_comp = latest_series.idxmin()
    else:
        top_comp, bot_comp = "-", "-"

    def get_delta_str(comp_name):
        if not prev_year: return None
        prev = detailed_scores[prev_year].get(comp_name, 0)
        curr = detailed_scores[latest_year].get(comp_name, 0)
        if prev > 0 and curr > 0:
            return f"{curr - prev:+.1f}"
        return None

    # --- UI ---
    st.title(f"📊 {selected_leader_name} 님 리더십 진단 분석 (3개년)")
    
    tab1, tab2, tab3 = st.tabs(["📈 종합 대시보드", "📝 주관식 심층분석", "🤖 AI 코칭"])
    
    # [TAB 1] Overview
    with tab1:
        st.subheader("Overview (구성원 응답 기준)")
        m1, m2, m3 = st.columns(3)
        with m1:
            d_str = f"{delta_total:+.2f} ({prev_year} 대비)" if prev_year else None
            custom_metric(f"{latest_year} 종합 점수", f"{curr_score:.2f}", d_str, show_arrow=True)
        with m2:
            d_top = get_delta_str(top_comp)
            val_top = f"{latest_series[top_comp]:.1f}" if top_comp != "-" else "-"
            custom_metric("최고 강점", top_comp, f"{val_top} ({d_top})" if d_top else val_top, delta_color="normal", show_arrow=False)
        with m3:
            d_bot = get_delta_str(bot_comp)
            val_bot = f"{latest_series[bot_comp]:.1f}" if bot_comp != "-" else "-"
            custom_metric("보완 필요", bot_comp, f"{val_bot} ({d_bot})" if d_bot else val_bot, delta_color="normal", show_arrow=False)
        
        st.divider()
        c1, c2 = st.columns([1, 1])
        with c1:
            st.markdown("##### 📅 리더십 종합 점수 추이")
            trend_df = pd.DataFrame({"Year": sorted_years, "Score": [avg_scores[y] for y in sorted_years]})
            fig_line = px.line(trend_df, x="Year", y="Score", markers=True, range_y=[0, 5.5], text="Score")
            fig_line.update_traces(line_color='#2563eb', line_width=3, textposition="top center", texttemplate='%{text:.2f}')
            st.plotly_chart(fig_line, use_container_width=True)
        with c2:
            st.markdown(f"##### 🕸️ 리더십 영역별 변화 ({latest_year})")
            fig_radar = go.Figure()
            colors = ['#cbd5e1', '#94a3b8', '#2563eb'] 
            cats = list(COMPETENCY_GROUPS.keys())
            for i, year in enumerate(sorted_years):
                vals = [grouped_scores[year].get(cat, 0) for cat in cats]
                vals += [vals[0]]
                fig_radar.add_trace(go.Scatterpolar(r=vals, theta=cats+[cats[0]], fill='toself' if year==latest_year else 'none', name=year, line_color=colors[i] if i<3 else 'black'))
            fig_radar.update_layout(polar=dict(radialaxis=dict(visible=True, range=[0, 5])), showlegend=True)
            st.plotly_chart(fig_radar, use_container_width=True)

    # [TAB 2] 주관식 심층분석
    with tab2:
        st.subheader("📝 주관식 피드백 심층 분석")
        
        # 데이터 수집
        data_context = ""
        
        data_context += "### [1] 구성원 주관식 응답 (3개년)\n"
        for year in sorted_years:
            data_context += f"<{year}년 구성원>\n"
            if year in member_text_map:
                for col in member_text_map[year]:
                    val = leader_data[col]
                    if pd.notna(val) and str(val).strip() not in ["0", "-", ""]:
                        clean_col = col.replace(f"_{year}", "")
                        data_context += f"- {clean_col}: {val}\n"
        
        data_context += "\n### [2] 동료 임원 주관식 응답 (3개년)\n"
        for year in sorted_years:
            data_context += f"<{year}년 동료>\n"
            if year in peer_text_map:
                for col in peer_text_map[year]:
                    val = leader_data[col]
                    if pd.notna(val) and str(val).strip() not in ["0", "-", ""]:
                        clean_col = col.replace(f"_동료_{year}", "")
                        data_context += f"- {clean_col}: {val}\n"
        
        data_context += "\n### [3] 객관식 점수 변화 추이\n"
        data_context += f"- 종합 점수 변화: {avg_scores}\n"
        data_context += f"- {latest_year}년 최고 강점: {top_comp}, 보완 필요: {bot_comp}\n"

        if st.button("🤖 AI 심층 분석 실행"):
            if not OPENAI_API_KEY:
                st.error("API Key가 필요합니다.")
            else:
                with st.spinner("AI가 3년치 데이터와 정성/정량 데이터를 통합 분석 중입니다..."):
                    try:
                        client = openai.OpenAI(api_key=OPENAI_API_KEY)
                        prompt = f"""
                        당신은 대기업 임원 리더십 평가 전문가입니다. 
                        제공된 3년치 '객관식 점수'와 '주관식 코멘트(구성원/동료)'를 통합 분석하여 아래 3가지 항목으로 심층 리포트를 작성해주세요.

                        1. **3개년 주관식 키워드 주요 변화**
                           - 연도별로 주관식에서 자주 등장하는 긍정/부정 키워드가 어떻게 달라졌는지 분석하세요.
                           - 예: "22년에는 '추진력'이 강조되었으나, 24년에는 '소통 부재'가 키워드로 부상함"

                        2. **변화 원인 추적 (정량+정성 통합)**
                           - 객관식 점수의 상승/하락 원인을 주관식 코멘트에서 찾아 연결하세요.
                           - 예: "전략적 Insight 점수가 하락한 원인은, 구성원 코멘트에서 '구체적 비전 공유 부족'이 반복 언급된 것과 연관됨"

                        3. **구성원 vs 동료 인식 비교**
                           - 동일한 리더십에 대해 구성원과 동료 임원이 바라보는 시각 차이(Gap)를 분석하세요.
                           - 예: "동료들은 '협업 능력'을 높게 평가하나, 구성원들은 '팀 내 소통'을 아쉬워하는 경향이 있음"

                        [분석 대상 데이터]
                        {data_context}
                        """
                        
                        res = client.chat.completions.create(
                            model="gpt-4o",
                            messages=[{"role": "user", "content": prompt}]
                        )
                        analysis = res.choices[0].message.content
                        st.success("분석 완료")
                        st.markdown(analysis)
                        st.session_state['qualitative_analysis'] = analysis 
                    except Exception as e:
                        st.error(f"오류 발생: {e}")
        
        with st.expander("원본 데이터 보기"):
            st.text(data_context)

    # [TAB 3] AI 코칭
    with tab3:
        st.subheader("💬 AI 리더십 코칭")
        chat_container = st.container()
        
        if "messages" not in st.session_state:
            st.session_state.messages = []
            welcome = f"{selected_leader_name} 임원님, 반갑습니다. 3년치 리더십 분석을 완료했습니다.\n\n"
            welcome += f"최근({latest_year}) 종합 점수는 **{curr_score:.2f}점**입니다. "
            if delta_total > 0: welcome += "전년 대비 상승세입니다. 📈\n\n"
            elif delta_total < 0: welcome += "전년 대비 하락세가 관찰됩니다. 📉\n\n"
            
            welcome += "현재 가장 고민되시는 리더십 이슈는 무엇인가요? 편하게 말씀해 주시면 대화를 시작하겠습니다.\n\n"
            welcome += """---
            💡 **추가 제안 (클릭하여 복사 후 질문해주세요)**
            * 📚 **이론 학습:** 현재 약점과 관련된 최신 리더십 이론 추천
            * 🎬 **영상 추천:** 리더십 개발을 위한 TED 강연 추천
            * 🗓️ **W/S 제안:** 조직문화 개선을 위한 워크숍 아젠다 제안
            (원하시는 내용을 질문해 주시면 상세히 안내해 드립니다)
            """
            st.session_state.messages.append({"role": "assistant", "content": welcome})
            
        with chat_container:
            for msg in st.session_state.messages:
                with st.chat_message(msg["role"]):
                    st.write(msg["content"])
        
        if prompt := st.chat_input("질문 입력..."):
            st.session_state.messages.append({"role": "user", "content": prompt})
            with chat_container:
                with st.chat_message("user"):
                    st.write(prompt)
            
            if OPENAI_API_KEY:
                try:
                    client = openai.OpenAI(api_key=OPENAI_API_KEY)
                    qual_context = st.session_state.get('qualitative_analysis', "주관식 분석 결과 없음")
                    
                    sys_msg = f"""
                    당신은 임원 전용 리더십 코치입니다. 대상: {selected_leader_name}
                    [데이터] 점수: {avg_scores}, 강점: {top_comp}, 약점: {bot_comp}
                    [주관식 분석] {qual_context}
                    
                    [가이드]
                    1. **전문가 페르소나:** 깊이 있는 통찰 제공.
                    2. **추가 제안:** 필요 시 이론/영상/워크숍 추천.
                    3. **Next Step:** 답변 끝에 항상 코칭 질문(GROW 등)을 던져 대화를 이어나갈 것. (문구: 해당 질문에 답을 해주시면 다음 단계로 이어나가 보겠습니다)
                    """
                    
                    msgs = [{"role": "system", "content": sys_msg}] + st.session_state.messages
                    
                    with chat_container:
                        with st.chat_message("assistant"):
                            stream = client.chat.completions.create(model="gpt-4o", messages=msgs, stream=True)
                            res = st.write_stream(stream)
                    st.session_state.messages.append({"role": "assistant", "content": res})
                except Exception as e:
                    st.error(f"오류: {e}")
            else:
                st.warning("API Key 미설정")

# --- 데이터가 없을 때 (초기 랜딩 화면) ---
else:
    # 빈 화면을 채워줄 안내 페이지
    st.title("👑 Executive Leadership AI Coach")
    st.markdown("---")
    
    col1, col2 = st.columns([1, 1])
    
    with col1:
        st.markdown("""
        ### 📊 플랫폼 소개
        본 플랫폼은 임원 리더십 진단 결과(3개년)를 기반으로 다각적인 통찰과 **맞춤형 AI 코칭**을 제공하는 시스템입니다.
        
        * **정량 데이터 시각화:** 3년치 점수 흐름 및 영역별 밸런스 분석
        * **주관식 심층 분석:** AI를 통한 구성원/동료의 코멘트 핵심 요약
        * **AI 코치와의 대화:** 발견된 리더십 Gap을 극복하기 위한 1:1 코칭
        """)
        
    with col2:
        st.info("""
        ### 🚀 시작하는 방법
        1. 좌측 사이드바 메뉴에서 **[엑셀 파일 업로드]** 버튼을 클릭하세요.
        2. 리더십 진단 결과가 포함된 **엑셀 파일(.xlsx)**을 업로드합니다.
        3. 업로드가 완료되면, 분석 대상이 되는 **임원 이름을 선택**하세요.
        """)
        
    st.markdown("---")
    st.markdown("""
    #### 💡 데이터 형식 안내 (Excel)
    정확한 분석을 위해 엑셀 파일은 아래와 같은 컬럼명 패턴을 유지해야 합니다.
    - **구성원 응답 (점수/주관식):** `[역량명/문항명]_24년` (예: 전략적 Insight_24년)
    - **동료 응답 (점수/주관식):** `[역량명/문항명]_동료_24년` (예: 소통_동료_23년)
    """)
