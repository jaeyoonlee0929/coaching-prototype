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
    컬럼명을 분석하여 역량(Competency), 연도(Year), 메타정보(Meta)를 분류합니다.
    가정: 점수 컬럼은 '역량명_00년' 형식을 따릅니다.
    """
    score_cols = {} # {year: [col1, col2...]}
    text_cols = {}  # {year: [col1, col2...]}
    meta_cols = []
    
    # 2자리 연도(22, 23, 24) 등을 찾기 위한 정규식
    # 예: "전략적 Insight_24년" -> Group1: 전략적 Insight, Group2: 24
    pattern = re.compile(r"^(.*)_(\d{2}년)$")
    
    for col in df.columns:
        match = pattern.match(col)
        if match:
            item_name = match.group(1)
            year = match.group(2)
            
            # 데이터 타입 확인 (수치형 vs 문자형)
            if pd.api.types.is_numeric_dtype(df[col]):
                if year not in score_cols: score_cols[year] = []
                score_cols[year].append(col)
            else:
                if year not in text_cols: text_cols[year] = []
                text_cols[year].append(col)
        else:
            meta_cols.append(col)
            
    return meta_cols, score_cols, text_cols

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
            # 이름 컬럼 찾기 (이름, 성명, Name 등)
            name_col = next((c for c in df.columns if "이름" in c or "Name" in c), df.columns[1])
            
            # 리더 선택
            leader_list = df[name_col].unique().tolist()
            selected_leader_name = st.selectbox("대상 임원 선택", leader_list)
            
            # 선택된 리더의 데이터만 필터링 (Series 형태)
            leader_data = df[df[name_col] == selected_leader_name].iloc[0]
            
            # API Key 경고
            if not OPENAI_API_KEY:
                st.warning("⚠️ API Key 미설정 (AI 기능 제한)")

# --- 메인 로직 ---
if df is not None and selected_leader_name:
    # 1. 컬럼 파싱
    meta_cols, score_map, text_map = parse_columns(df)
    
    # 연도 정렬 (22년 -> 23년 -> 24년)
    sorted_years = sorted(score_map.keys())
    
    # 2. 데이터 구조화
    # 역량 리스트 추출 (가장 최근 연도 기준)
    latest_year = sorted_years[-1]
    competencies = [col.replace(f"_{latest_year}", "") for col in score_map[latest_year]]
    
    # 연도별 점수 Dict 생성
    yearly_scores = {} # {22년: {역량: 점수, ...}, ...}
    
    for year in sorted_years:
        scores = {}
        for col in score_map[year]:
            comp_name = col.replace(f"_{year}", "")
            scores[comp_name] = leader_data[col]
        yearly_scores[year] = scores

    # --- UI 탭 구성 ---
    st.title(f"📊 {selected_leader_name} 님 리더십 진단 분석 (3개년)")
    
    tab1, tab2, tab3 = st.tabs(["📈 종합 대시보드", "📝 주관식 심층분석", "🤖 AI 코칭"])
    
    # [TAB 1] 종합 대시보드
    with tab1:
        # 1-1. 상단 지표 (최근 연도 종합 점수 및 전년 대비 증감)
        st.subheader("Overview")
        
        # 연도별 평균 점수 계산
        avg_scores = {y: pd.Series(yearly_scores[y]).mean() for y in sorted_years}
        
        col1, col2, col3 = st.columns(3)
        current_score = avg_scores[latest_year]
        prev_year = sorted_years[-2] if len(sorted_years) > 1 else None
        prev_score = avg_scores[prev_year] if prev_year else 0
        delta = current_score - prev_score if prev_year else 0
        
        col1.metric(f"{latest_year} 종합 점수", f"{current_score:.2f}", f"{delta:+.2f} ({prev_year} 대비)")
        
        # 최고/최저 역량
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
            st.markdown("##### 🕸️ 역량별 변화 비교 (Radar Chart)")
            # Radar Chart 데이터 구성
            fig_radar = go.Figure()
            
            # 색상 팔레트 (과거 -> 현재: 연한색 -> 진한색)
            colors = ['#cbd5e1', '#94a3b8', '#2563eb'] # Light Gray, Gray, Blue
            
            for i, year in enumerate(sorted_years):
                vals = [yearly_scores[year].get(comp, 0) for comp in competencies]
                # Radar 차트 닫기 위해 첫 번째 값 추가
                vals += [vals[0]]
                comps_closed = competencies + [competencies[0]]
                
                fig_radar.add_trace(go.Scatterpolar(
                    r=vals,
                    theta=comps_closed,
                    fill='toself' if year == latest_year else 'none',
                    name=year,
                    line_color=colors[i] if i < 3 else 'black'
                ))
            
            fig_radar.update_layout(
                polar=dict(radialaxis=dict(visible=True, range=[0, 5])),
                showlegend=True
            )
            st.plotly_chart(fig_radar, use_container_width=True)

    # [TAB 2] 주관식 심층분석
    with tab2:
        st.subheader("📝 주관식 피드백 분석")
        
        # 주관식 데이터 수집
        comments_text = ""
        for year in reversed(sorted_years): # 최신순
            if year in text_map:
                comments_text += f"\n[{year} 피드백]\n"
                for col in text_map[year]:
                    val = leader_data[col]
                    if pd.notna(val) and str(val).strip() != "0":
                        clean_col_name = col.replace(f"_{year}", "")
                        comments_text += f"- {clean_col_name}: {val}\n"
        
        if not comments_text.strip():
            st.warning("주관식 응답 데이터가 없습니다.")
        else:
            # AI 분석 요청 버튼
            if st.button("🤖 AI 심층 분석 실행"):
                if not OPENAI_API_KEY:
                    st.error("API Key가 필요합니다.")
                else:
                    with st.spinner("AI가 3년치 피드백을 분석하여 인사이트를 도출하고 있습니다..."):
                        try:
                            client = openai.OpenAI(api_key=OPENAI_API_KEY)
                            prompt = f"""
                            당신은 임원 리더십 평가 전문가입니다. 
                            아래는 특정 임원에 대한 3년치 주관식 다면평가 피드백입니다.
                            이 내용을 정밀 분석하여 다음 3가지 항목으로 요약해 주세요.
                            
                            1. **핵심 강점 (Top 3)**: 구체적인 행동 예시와 함께.
                            2. **주요 보완점 및 Risk**: 반복적으로 언급되거나 치명적인 약점.
                            3. **변화 추이**: 과거 대비 개선된 점이나 새롭게 대두된 이슈.
                            
                            [피드백 데이터]
                            {comments_text}
                            """
                            
                            response = client.chat.completions.create(
                                model="gpt-4o",
                                messages=[{"role": "system", "content": "핵심만 명확하게 요약하세요."},
                                          {"role": "user", "content": prompt}]
                            )
                            analysis_result = response.choices[0].message.content
                            st.success("분석 완료!")
                            st.markdown(analysis_result)
                            
                            # 세션에 저장 (코칭 탭에서 쓰기 위해)
                            st.session_state['qualitative_analysis'] = analysis_result
                            
                        except Exception as e:
                            st.error(f"분석 중 오류 발생: {e}")
            
            # 원본 데이터 보기 (Expander)
            with st.expander("원본 피드백 전체 보기"):
                st.text(comments_text)

    # [TAB 3] AI 코칭
    with tab3:
        st.subheader("💬 AI 리더십 코칭")
        
        # 채팅 기록 초기화
        if "messages" not in st.session_state:
            st.session_state.messages = []
            # 초기 인사 메시지 생성
            welcome_msg = f"{selected_leader_name} 임원님, 반갑습니다. 3년치 리더십 데이터를 모두 파악했습니다.\n\n"
            
            # 데이터 기반 오프닝 멘트 생성
            if delta > 0:
                welcome_msg += f"작년 대비 종합 점수가 {delta:.2f}점 상승하며 긍정적인 변화를 보이고 계시군요. "
            elif delta < 0:
                welcome_msg += f"작년 대비 종합 점수가 다소 하락({delta:.2f}점)하여 점검이 필요한 시점입니다. "
            
            welcome_msg += f"특히 **'{top_comp}'** 역량은 매우 탁월하지만, **'{bot_comp}'** 역량은 보완이 필요해 보입니다.\n\n어떤 부분부터 이야기를 나누시겠습니까?"
            st.session_state.messages.append({"role": "assistant", "content": welcome_msg})

        # 채팅 UI
        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]):
                st.write(msg["content"])
        
        if prompt := st.chat_input("코치에게 질문하기..."):
            st.session_state.messages.append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.write(prompt)
            
            if OPENAI_API_KEY:
                try:
                    client = openai.OpenAI(api_key=OPENAI_API_KEY)
                    
                    # 주관식 분석 결과가 있다면 컨텍스트에 추가
                    qual_context = st.session_state.get('qualitative_analysis', "주관식 분석 결과 없음")
                    
                    system_prompt = f"""
                    당신은 대기업 임원 전용 리더십 코치(Executive Coach)입니다.
                    사용자 정보: {selected_leader_name} 임원
                    
                    [정량 데이터]
                    - 3년치 점수 추이: {avg_scores}
                    - 최신 강점: {top_comp}, 약점: {bot_comp}
                    
                    [정성 피드백 요약]
                    {qual_context}
                    
                    [코칭 가이드]
                    1. 임원급에 맞는 품격 있고 직관적인 언어를 사용하세요.
                    2. 단순히 점수를 나열하지 말고, '비즈니스 임팩트' 관점에서 해석해 주세요.
                    3. 약점에 대해서는 방어기제를 건드리지 말고, '더 큰 리더로 성장하기 위한 제언' 형태로 전달하세요.
                    4. GROW 모델을 자연스럽게 적용하여 실행 계획을 이끌어내세요.
                    """
                    
                    msgs = [{"role": "system", "content": system_prompt}] + st.session_state.messages
                    
                    with st.chat_message("assistant"):
                        stream = client.chat.completions.create(model="gpt-4o", messages=msgs, stream=True)
                        response = st.write_stream(stream)
                    
                    st.session_state.messages.append({"role": "assistant", "content": response})
                    
                except Exception as e:
                    st.error(f"오류: {e}")
            else:
                st.warning("API Key 미설정")
