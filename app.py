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

def parse_columns(df):
    """
    컬럼명을 분석하여 구성원 응답, 동료 응답, 텍스트 데이터 등을 분류합니다.
    - 구성원 응답: "역량명_24년" (동료라는 단어 없음)
    - 동료 응답: "역량명_동료_24년"
    """
    member_scores = {} # {year: [col1, col2...]}
    peer_scores = {}   # {year: [col1, col2...]}
    text_cols = {}     # {year: [col1, col2...]}
    meta_cols = []
    
    # 정규식 패턴
    # 1. 동료 응답 패턴: "역량명_동료_22년"
    peer_pattern = re.compile(r"^(.*)_동료_(\d{2}년)$")
    # 2. 구성원 응답 패턴: "역량명_22년" (동료라는 단어가 없어야 함)
    member_pattern = re.compile(r"^(.*)_(\d{2}년)$")
    
    for col in df.columns:
        # 먼저 동료 패턴인지 확인
        peer_match = peer_pattern.match(col)
        if peer_match:
            year = peer_match.group(2)
            if pd.api.types.is_numeric_dtype(df[col]):
                if year not in peer_scores: peer_scores[year] = []
                peer_scores[year].append(col)
            continue
            
        # 구성원 패턴 확인
        member_match = member_pattern.match(col)
        if member_match:
            year = member_match.group(2)
            if pd.api.types.is_numeric_dtype(df[col]):
                if year not in member_scores: member_scores[year] = []
                member_scores[year].append(col)
            else:
                # 텍스트 데이터 (주관식 등)
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
    
    # 연도 정렬 (22년 -> 23년 -> 24년)
    sorted_years = sorted(member_map.keys())
    latest_year = sorted_years[-1]
    
    # 역량 리스트 (최신 연도 구성원 응답 기준)
    # 컬럼명에서 "_24년" 제거한 순수 역량명
    competencies = [col.replace(f"_{latest_year}", "") for col in member_map[latest_year]]
    
    # 연도별 점수 Dict (구성원 기준)
    yearly_scores = {} 
    for year in sorted_years:
        scores = {}
        for col in member_map[year]:
            # 동료 데이터가 섞여 들어오지 않도록 한번 더 체크
            if "_동료_" in col: continue
            
            comp_name = col.replace(f"_{year}", "")
            scores[comp_name] = leader_data[col]
        yearly_scores[year] = scores

    # --- UI 탭 구성 ---
    st.title(f"📊 {selected_leader_name} 님 리더십 진단 분석 (3개년)")
    
    tab1, tab2, tab3 = st.tabs(["📈 종합 대시보드", "📝 주관식 심층분석", "🤖 AI 코칭"])
    
    # [TAB 1] 종합 대시보드
    with tab1:
        st.subheader("Overview (구성원 응답 기준)")
        
        # 1-1. 상단 지표
        # 연도별 평균 계산 (구성원 점수만)
        avg_scores = {y: pd.Series(yearly_scores[y]).mean() for y in sorted_years}
        
        col1, col2, col3 = st.columns(3)
        
        # 종합 점수 (최신)
        curr_score = avg_scores[latest_year]
        prev_year = sorted_years[-2] if len(sorted_years) > 1 else None
        prev_score = avg_scores[prev_year] if prev_year else 0
        delta = curr_score - prev_score if prev_year else 0
        
        col1.metric(f"{latest_year} 종합 점수", f"{curr_score:.2f}", f"{delta:+.2f} ({prev_year} 대비)")
        
        # 강/약점 (최신 구성원 응답 기준)
        latest_series = pd.Series(yearly_scores[latest_year])
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
            fig_line = px.line(trend_df, x="Year", y="Score", markers=True, range_y=[0, 5.5])
            fig_line.update_traces(line_color='#2563eb', line_width=3)
            st.plotly_chart(fig_line, use_container_width=True)
            
        with c2:
            st.markdown(f"##### 🕸️ 역량별 변화 비교 ({latest_year} vs 과거)")
            fig_radar = go.Figure()
            colors = ['#cbd5e1', '#94a3b8', '#2563eb'] # 연한색 -> 진한색
            
            for i, year in enumerate(sorted_years):
                # 해당 연도의 점수 리스트 생성 (순서 보장)
                vals = [yearly_scores[year].get(comp, 0) for comp in competencies]
                vals += [vals[0]] # Close the loop
                comps_closed = competencies + [competencies[0]]
                
                fig_radar.add_trace(go.Scatterpolar(
                    r=vals,
                    theta=comps_closed,
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
        
        if "messages" not in st.session_state:
            st.session_state.messages = []
            welcome = f"{selected_leader_name} 임원님, 반갑습니다.\n\n"
            welcome += f"최근({latest_year}) 구성원 평가 기준 종합 점수는 **{curr_score:.2f}점**입니다. "
            if delta > 0: welcome += "전년 대비 상승했습니다. 📈"
            elif delta < 0: welcome += "전년 대비 다소 하락했습니다. 📉"
            
            st.session_state.messages.append({"role": "assistant", "content": welcome})
            
        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]):
                st.write(msg["content"])
        
        if prompt := st.chat_input("질문 입력..."):
            st.session_state.messages.append({"role": "user", "content": prompt})
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
                    
                    with st.chat_message("assistant"):
                        stream = client.chat.completions.create(model="gpt-4o", messages=msgs, stream=True)
                        res = st.write_stream(stream)
                    st.session_state.messages.append({"role": "assistant", "content": res})
                except Exception as e:
                    st.error(f"오류: {e}")
            else:
                st.warning("API Key 미설정")
