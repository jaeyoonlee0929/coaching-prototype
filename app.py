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

# --- 역량 그룹 정의 (사용자 요청 기준) ---
COMPETENCY_GROUPS = {
    "SKMS에 대한 확신과 열정": [
        "SKMS에 대한 확신",
        "구성원/이해관계자 행복 추구",
        "패기/솔선수범",
        "Integrity"
    ],
    "혁신적 전략 수립": [
        "전략적 Insight",
        "담당 조직 변화 Design",
        "비전 공유/지속적 변화 추진"
    ],
    "과감한 돌파와 실행": [
        "SUPEX 목표 설정",
        "내·외부 폭넓은 협업", 
        "신속한 실행 및 성과 창출"
    ],
    "VWBE 문화구축": [
        "구성원 VWBE환경 조성 활동 지원",
        "신뢰 기반의 협력 촉진",
        "패기 인재 인정/육성"
    ]
}

# --- 데이터 로드 및 전처리 함수 ---
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
    """텍스트 매칭을 위해 공백과 특수문자를 제거하는 헬퍼 함수"""
    return re.sub(r'[\s\·\.\,\-\_]', '', str(text)).lower()

def parse_columns(df):
    """
    컬럼명을 분석하여 구성원 응답, 동료 응답, 텍스트 데이터 등을 분류합니다.
    """
    member_scores = {} # {year: [col1, col2...]}
    peer_scores = {}   # {year: [col1, col2...]}
    text_cols = {}     # {year: [col1, col2...]}
    meta_cols = []
    
    peer_pattern = re.compile(r"^(.*)_동료_(\d{2}년)$")
    member_pattern = re.compile(r"^(.*)_(\d{2}년)$")
    
    for col in df.columns:
        peer_match = peer_pattern.match(col)
        if peer_match:
            year = peer_match.group(2)
            if pd.api.types.is_numeric_dtype(df[col]):
                if year not in peer_scores: peer_scores[year] = []
                peer_scores[year].append(col)
            continue
            
        member_match = member_pattern.match(col)
        if member_match:
            year = member_match.group(2)
            if pd.api.types.is_numeric_dtype(df[col]):
                if year not in member_scores: member_scores[year] = []
                member_scores[year].append(col)
            else:
                if year not in text_cols: text_cols[year] = []
                text_cols[year].append(col)
        else:
            meta_cols.append(col)
            
    return meta_cols, member_scores, peer_scores, text_cols

# --- [MODIFIED] 커스텀 메트릭 함수 (화살표 옵션 추가, 가독성 개선) ---
def custom_metric(label, value, delta=None, delta_color="normal", show_arrow=False):
    """
    HTML/CSS를 사용하여 지표를 표시합니다.
    show_arrow=True일 경우 화살표를 표시하고, False일 경우 색상만 적용합니다.
    """
    delta_html = ""
    if delta:
        try:
            match = re.search(r"([+-]?\d+\.?\d*)", str(delta))
            if match:
                delta_val = float(match.group(1))
                
                # 색상 결정
                text_color = "#666" # 기본 회색
                arrow_char = ""
                
                if delta_val > 0:
                    if delta_color == "normal": text_color = "#009933" # 초록
                    elif delta_color == "inverse": text_color = "#cc0000" # 빨강
                    arrow_char = "↑" if show_arrow else ""
                elif delta_val < 0:
                    if delta_color == "normal": text_color = "#cc0000" # 빨강
                    elif delta_color == "inverse": text_color = "#009933" # 초록
                    arrow_char = "↓" if show_arrow else ""
                
                # 델타 값 포맷팅
                delta_str = f"{arrow_char} {delta}" if show_arrow else f"{delta}"
                delta_html = f'<span style="color: {text_color}; font-size: 1rem; margin-left: 8px; font-weight: 600;">{delta_str}</span>'
        except:
            delta_html = f'<span style="color: #666; font-size: 1rem; margin-left: 8px;">{delta}</span>'

    html_code = f"""
    <div style="display: flex; flex-direction: column; margin-bottom: 1.5rem;">
        <span style="font-size: 1rem; color: #555; font-weight: 500; margin-bottom: 4px;">{label}</span>
        <div style="display: flex; align-items: baseline;">
            <span style="font-size: 2.2rem; font-weight: 700; color: #262730;">{value}</span>
            {delta_html}
        </div>
    </div>
    """
    st.markdown(html_code, unsafe_allow_html=True)

# --- 사이드바: 업로드 및 대상자 선택 ---
with st.sidebar:
    st.title("👑 임원 리더십 코칭")
    st.info("3개년 리더십 진단 결과(Excel)를 업로드하세요.")
    
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
    meta_cols, member_map, peer_map, text_map = parse_columns(df)
    sorted_years = sorted(member_map.keys())
    latest_year = sorted_years[-1]
    
    # 2. 역량 매핑 및 데이터 추출
    raw_competencies = [col.replace(f"_{latest_year}", "") for col in member_map[latest_year]]
    norm_comp_map = {normalize_text(c): c for c in raw_competencies}
    
    grouped_scores = {}
    detailed_scores = {} 

    for year in sorted_years:
        year_group_data = {}
        year_detail_data = {}
        
        # 상세 점수 추출
        for col in member_map[year]:
            if "_동료_" in col: continue
            comp_name = col.replace(f"_{year}", "")
            val = leader_data[col]
            if pd.notna(val) and val > 0:
                year_detail_data[comp_name] = val
            else:
                year_detail_data[comp_name] = 0
        detailed_scores[year] = year_detail_data
        
        # 그룹별 평균 계산
        for group_name, sub_items in COMPETENCY_GROUPS.items():
            scores = []
            for item in sub_items:
                norm_item = normalize_text(item)
                target_col = None
                if item in year_detail_data:
                    target_col = item
                elif norm_item in norm_comp_map and norm_comp_map[norm_item] in year_detail_data:
                    target_col = norm_comp_map[norm_item]
                
                if target_col:
                    val = year_detail_data[target_col]
                    if val > 0:
                        scores.append(val)
            
            if scores:
                year_group_data[group_name] = sum(scores) / len(scores)
            else:
                year_group_data[group_name] = 0.0
        
        grouped_scores[year] = year_group_data

    # Common calculations
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

    # 개별 역량 Delta 계산 함수
    def get_delta_str(comp_name):
        if not prev_year: return None
        prev = detailed_scores[prev_year].get(comp_name, 0)
        curr = detailed_scores[latest_year].get(comp_name, 0)
        if prev > 0 and curr > 0:
            return f"{curr - prev:+.1f}"
        return None

    # --- UI 탭 구성 ---
    st.title(f"📊 {selected_leader_name} 님 리더십 진단 분석 (3개년)")
    
    tab1, tab2, tab3 = st.tabs(["📈 종합 대시보드", "📝 주관식 심층분석", "🤖 AI 코칭"])
    
    # [TAB 1] 종합 대시보드
    with tab1:
        st.subheader("Overview (구성원 응답 기준)")
        
        m1, m2, m3 = st.columns(3)
        
        with m1:
            delta_str = f"{delta_total:+.2f} ({prev_year} 대비)" if prev_year else None
            # 종합 점수: 화살표 표시 (show_arrow=True)
            custom_metric(f"{latest_year} 종합 점수", f"{curr_score:.2f}", delta_str, show_arrow=True)
            
        with m2:
            d_top = get_delta_str(top_comp)
            val_top = f"{latest_series[top_comp]:.1f}" if top_comp != "-" else "-"
            # 최고 강점: 화살표 없이 색상만 (show_arrow=False)
            custom_metric("최고 강점", top_comp, f"{val_top} ({d_top})" if d_top else val_top, delta_color="normal", show_arrow=False)
            
        with m3:
            d_bot = get_delta_str(bot_comp)
            val_bot = f"{latest_series[bot_comp]:.1f}" if bot_comp != "-" else "-"
            # 보완 필요: 화살표 없이 색상만 (show_arrow=False)
            custom_metric("보완 필요", bot_comp, f"{val_bot} ({d_bot})" if d_bot else val_bot, delta_color="normal", show_arrow=False)
        
        st.divider()
        
        # 차트 영역
        c1, c2 = st.columns([1, 1])
        
        with c1:
            st.markdown("##### 📅 3개년 종합 점수 추이")
            trend_df = pd.DataFrame({
                "Year": sorted_years,
                "Score": [avg_scores[y] for y in sorted_years]
            })
            fig_line = px.line(trend_df, x="Year", y="Score", markers=True, range_y=[0, 5.5], text="Score")
            fig_line.update_traces(line_color='#2563eb', line_width=3, textposition="top center", texttemplate='%{text:.2f}')
            st.plotly_chart(fig_line, use_container_width=True)
            
        with c2:
            st.markdown(f"##### 🕸️ 리더십 영역별 변화 ({latest_year})")
            fig_radar = go.Figure()
            colors = ['#cbd5e1', '#94a3b8', '#2563eb'] 
            
            categories = list(COMPETENCY_GROUPS.keys())
            
            for i, year in enumerate(sorted_years):
                vals = [grouped_scores[year].get(cat, 0) for cat in categories]
                vals += [vals[0]]
                cats_closed = categories + [categories[0]]
                
                fig_radar.add_trace(go.Scatterpolar(
                    r=vals,
                    theta=cats_closed,
                    fill='toself' if year == latest_year else 'none',
                    name=year,
                    line_color=colors[i] if i < 3 else 'black'
                ))
            
            fig_radar.update_layout(polar=dict(radialaxis=dict(visible=True, range=[0, 5])), showlegend=True)
            st.plotly_chart(fig_radar, use_container_width=True)

    # [TAB 2] 주관식 심층분석
    with tab2:
        st.subheader("📝 주관식 피드백 분석")
        
        comments_text = ""
        for year in reversed(sorted_years):
            if year in text_map:
                comments_text += f"\n[{year} 피드백]\n"
                for col in text_map[year]:
                    val = leader_data[col]
                    if pd.notna(val) and str(val).strip() not in ["0", "-", ""]:
                        clean_col = col.replace(f"_{year}", "")
                        comments_text += f"- {clean_col}: {val}\n"
        
        if not comments_text.strip():
            st.warning("분석할 주관식 데이터가 없습니다.")
        else:
            if st.button("🤖 AI 심층 분석 실행"):
                if not OPENAI_API_KEY:
                    st.error("API Key가 필요합니다.")
                else:
                    with st.spinner("AI 분석 중..."):
                        try:
                            client = openai.OpenAI(api_key=OPENAI_API_KEY)
                            prompt = f"""
                            당신은 임원 리더십 코치입니다. 3년치 주관식 데이터를 분석하여 요약해주세요.
                            
                            1. **핵심 강점 (Top 3)**
                            2. **주요 보완점 및 Risk**
                            3. **연도별 변화 흐름**
                            
                            [데이터]
                            {comments_text}
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
                            st.error(f"오류: {e}")
            
            with st.expander("원본 데이터 보기"):
                st.text(comments_text)

    # [TAB 3] AI 코칭
    with tab3:
        st.subheader("💬 AI 리더십 코칭")
        
        chat_container = st.container()
        
        if "messages" not in st.session_state:
            st.session_state.messages = []
            
            welcome = f"{selected_leader_name} 임원님, 반갑습니다. 3년치 리더십 데이터 분석을 완료했습니다.\n\n"
            welcome += f"최근({latest_year}) 구성원 평가 기준 종합 점수는 **{curr_score:.2f}점**입니다. "
            if delta_total > 0: welcome += "전년 대비 상승했습니다. 📈\n\n"
            elif delta_total < 0: welcome += "전년 대비 다소 하락했습니다. 📉\n\n"
            
            welcome += "현재 가장 고민되시는 리더십 이슈는 무엇인가요? 편하게 말씀해 주시면 대화를 시작하겠습니다.\n\n"
            
            welcome += """---
            💡 **추가로 논의할 수 있는 주제들** (아래 내용을 복사해서 질문하시면 심도 있게 다뤄드립니다)
            * 📚 **이론 학습:** 현재 나의 약점과 관련된 최신 리더십 이론이나 아티클을 추천해 주세요.
            * 🎬 **영상 추천:** 리더십 개발에 도움이 될 만한 TED 강연이나 교육 영상을 추천해 주세요.
            * 🗓️ **W/S 제안:** 팀원들과 소통을 강화하기 위한 워크숍 아젠다를 제안해 주세요.
            (질문 중 원하는 내용을 복사 붙여넣기 하시면 추가로 진행하겠습니다)
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
                    qual_context = st.session_state.get('qualitative_analysis', "")
                    
                    sys_msg = f"""
                    당신은 대기업 임원 전용 전문 리더십 코치(Executive Coach)입니다.
                    대상: {selected_leader_name} 임원
                    
                    [정량 데이터]
                    - 3년치 점수 추이: {avg_scores}
                    - 최신 강점: {top_comp}, 약점: {bot_comp}
                    
                    [정성 피드백 요약]
                    {qual_context}
                    
                    [대화 및 응답 가이드]
                    1. **전문가 페르소나:** 실제 코칭 세션처럼 정중하고 깊이 있는 통찰을 제공하세요. 단순한 답변보다는 사용자의 생각을 확장시키는 질문을 던지세요.
                    2. **추가 제안 (옵션):** 사용자가 특정 약점이나 개발 포인트에 대해 고민할 때만, 관련된 이론 학습, 영상 추천, 워크숍 일정 등을 제안하세요. (매번 할 필요 없음)
                    3. **Next Step 질문 (필수):** 답변의 마지막에는 항상 코칭 기법(GROW, 질문법 등)을 활용하여 상황에 맞는 심화 질문을 던지세요.
                       - 문구 예시: (해당 질문에 답을 해주시면 다음 단계로 이어나가 보겠습니다)
                       - 주의: 구체적으로 어떤 코칭 모델을 썼는지는 밝히지 마세요.
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
