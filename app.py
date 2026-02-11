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
        "내·외부 폭넓은 협업", # 엑셀 데이터 매칭을 위해 유연하게 처리 예정
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
        # 동료 응답 확인
        peer_match = peer_pattern.match(col)
        if peer_match:
            year = peer_match.group(2)
            if pd.api.types.is_numeric_dtype(df[col]):
                if year not in peer_scores: peer_scores[year] = []
                peer_scores[year].append(col)
            continue
            
        # 구성원 응답 확인
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
    # 실제 엑셀에 있는 역량명 리스트 (최신 연도 기준)
    raw_competencies = [col.replace(f"_{latest_year}", "") for col in member_map[latest_year]]
    
    # 그룹별 점수 계산을 위한 매핑 생성
    # normalized_target -> actual_excel_name
    norm_comp_map = {normalize_text(c): c for c in raw_competencies}
    
    # 연도별/그룹별 점수 계산
    grouped_scores = {} # {year: {GroupA: 4.5, GroupB: 3.2 ...}}
    detailed_scores = {} # {year: {CompA: 4.5 ...}} (기존 상세 점수)

    for year in sorted_years:
        year_group_data = {}
        year_detail_data = {}
        
        # 상세 점수 추출
        for col in member_map[year]:
            if "_동료_" in col: continue
            comp_name = col.replace(f"_{year}", "")
            year_detail_data[comp_name] = leader_data[col]
        detailed_scores[year] = year_detail_data
        
        # 그룹별 평균 계산
        for group_name, sub_items in COMPETENCY_GROUPS.items():
            scores = []
            for item in sub_items:
                # 엑셀의 실제 컬럼명 찾기 (유연한 매칭)
                norm_item = normalize_text(item)
                
                # 직접 매칭 시도
                target_col = None
                if item in year_detail_data:
                    target_col = item
                elif norm_item in norm_comp_map and norm_comp_map[norm_item] in year_detail_data:
                    target_col = norm_comp_map[norm_item]
                
                if target_col:
                    val = year_detail_data[target_col]
                    if pd.notna(val):
                        scores.append(val)
            
            if scores:
                year_group_data[group_name] = sum(scores) / len(scores)
            else:
                year_group_data[group_name] = 0.0
        
        grouped_scores[year] = year_group_data

    # --- UI 탭 구성 ---
    st.title(f"📊 {selected_leader_name} 님 리더십 진단 분석 (3개년)")
    
    tab1, tab2, tab3 = st.tabs(["📈 종합 대시보드", "📝 주관식 심층분석", "🤖 AI 코칭"])
    
    # [TAB 1] 종합 대시보드
    with tab1:
        st.subheader("Overview (구성원 응답 기준)")
        
        # 1-1. 상단 지표
        avg_scores = {y: pd.Series(detailed_scores[y]).mean() for y in sorted_years}
        
        col1, col2, col3 = st.columns(3)
        
        curr_score = avg_scores[latest_year]
        prev_year = sorted_years[-2] if len(sorted_years) > 1 else None
        prev_score = avg_scores[prev_year] if prev_year else 0
        delta = curr_score - prev_score if prev_year else 0
        
        col1.metric(f"{latest_year} 종합 점수", f"{curr_score:.2f}", f"{delta:+.2f} ({prev_year} 대비)")
        
        # 강/약점 (최신 구성원 응답 기준)
        latest_series = pd.Series(detailed_scores[latest_year])
        top_comp = latest_series.idxmax()
        bot_comp = latest_series.idxmin()
        
        col2.metric("최고 강점 역량", top_comp, f"{latest_series[top_comp]:.1f}")
        col3.metric("보완 필요 역량", bot_comp, f"{latest_series[bot_comp]:.1f}", delta_color="inverse")
        
        st.divider()
        
        # 1-2. 차트 영역
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
            colors = ['#cbd5e1', '#94a3b8', '#2563eb'] # 연한색 -> 진한색
            
            # 그룹 카테고리 순서 정의
            categories = list(COMPETENCY_GROUPS.keys())
            
            for i, year in enumerate(sorted_years):
                vals = [grouped_scores[year].get(cat, 0) for cat in categories]
                vals += [vals[0]] # Close loop
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
                    # 값이 있고, 0이나 빈칸이 아닌 경우만
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
        
        # 채팅 히스토리 표시 영역
        chat_container = st.container()
        
        # 채팅 기록 초기화
        if "messages" not in st.session_state:
            st.session_state.messages = []
            welcome = f"{selected_leader_name} 임원님, 반갑습니다.\n\n"
            welcome += f"최근({latest_year}) 구성원 평가 기준 종합 점수는 **{curr_score:.2f}점**입니다. "
            if delta > 0: welcome += "전년 대비 상승했습니다. 📈"
            elif delta < 0: welcome += "전년 대비 다소 하락했습니다. 📉"
            
            st.session_state.messages.append({"role": "assistant", "content": welcome})
            
        with chat_container:
            for msg in st.session_state.messages:
                with st.chat_message(msg["role"]):
                    st.write(msg["content"])
        
        # 입력창 (항상 하단에 위치)
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
                    당신은 임원 전용 코치입니다.
                    대상: {selected_leader_name}
                    정량 데이터(구성원 기준): {avg_scores}
                    강점: {top_comp}, 약점: {bot_comp}
                    주관식 분석: {qual_context}
                    
                    GROW 모델로 코칭하고, 임원의 언어를 사용하세요.
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
