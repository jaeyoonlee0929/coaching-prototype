import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import pdfplumber
import openai
import os
import time

# --- 페이지 설정 ---
st.set_page_config(
    page_title="AI 리더십 코칭 - SK",
    page_icon="🏆",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- [중요] API Key 로드 (JYL) ---
try:
    OPENAI_API_KEY = st.secrets["JYL"]
except FileNotFoundError:
    # 로컬 개발 환경용 Fallback (필요시 삭제)
    OPENAI_API_KEY = None
    # st.error("API Key 설정 파일을 찾을 수 없습니다. (.streamlit/secrets.toml)")
    # st.stop()
except KeyError:
    st.error("Secrets에 'JYL' 키가 설정되지 않았습니다.")
    st.stop()

# --- 기본 데모 데이터 (구조 보강) ---
DEMO_DATA = {
    "leadership": {
        "summary": 4.8,
        "details": [
            {"category": "SKMS 확신", "self": 4.8, "group": 4.3},
            {"category": "패기/솔선수범", "self": 4.8, "group": 4.4},
            {"category": "Integrity", "self": 4.8, "group": 4.5},
            {"category": "경영환경 이해", "self": 4.8, "group": 4.5},
            {"category": "팀 목표 수립", "self": 4.8, "group": 4.5},
            {"category": "변화 주도", "self": 4.8, "group": 4.4},
            {"category": "도전적 목표", "self": 4.8, "group": 4.4},
            {"category": "팀워크 발휘", "self": 4.8, "group": 4.3},
            {"category": "과감한 실행", "self": 4.8, "group": 4.4},
            {"category": "자율환경 조성", "self": 5.0, "group": 4.4},
            {"category": "소통", "self": 4.8, "group": 4.4},
            {"category": "구성원 육성", "self": 4.8, "group": 4.3},
        ],
        "comments": {
            "boss": [
                "팀원들과 소통하면서 성장할 수 있는 팀장",
                "조직의 발전을 위해 방향성을 제시할 수 있는 팀장", 
                "개선점: 팀장으로서 Leading 및 적극적 의견 제시 필요"
            ],
            "members": [
                "이미지: 희생, 헌신, 배려, 책임감",
                "강점: 세심함, 신입 매니저 교육, 다각도 해결방안",
                "개선점: 신임 팀장으로서의 경험치 부족",
                "기대: 지금처럼만 해주시면 너무 감사함"
            ]
        }
    },
    "oei": {
        "summary": 4.6,
        "stages": [
            {"stage": "Input", "score": 4.6},
            {"stage": "Process", "score": 4.5},
            {"stage": "Output", "score": 4.7},
        ],
        "gaps": [
            {"category": "변화 공감/지지", "self": 3.0, "team": 4.8, "type": "Underestimation"},
            {"category": "상호 협력", "self": 3.0, "team": 4.5, "type": "Underestimation"},
            {"category": "R&C 확보", "self": 3.0, "team": 4.3, "type": "Underestimation"},
            {"category": "명확한 목표", "self": 5.0, "team": 4.8, "type": "Alignment"},
            {"category": "신속한 상황 인식", "self": 5.0, "team": 4.5, "type": "Overestimation"},
        ],
        "comments": {
            "strength": ["개인 역량 존중", "자율적 분위기", "각자 일을 열심히 함", "소통과 배려"],
            "weakness": ["개인주의가 이기주의로 보일 위험", "적극적 소통 부족"]
        }
    }
}

# --- PDF 텍스트 추출 함수 ---
def extract_text_from_pdf(file):
    text = ""
    try:
        with pdfplumber.open(file) as pdf:
            for page in pdf.pages:
                extracted = page.extract_text()
                if extracted:
                    text += extracted + "\n"
        return text
    except Exception as e:
        st.error(f"PDF를 읽는 중 오류가 발생했습니다: {e}")
        return None

# --- 데이터 파싱 및 구조화 (시뮬레이션) ---
def analyze_report_data(l_text, o_text):
    progress_text = "데이터 분석 중입니다..."
    my_bar = st.progress(0, text=progress_text)

    for percent_complete in range(100):
        time.sleep(0.01) # 분석 시뮬레이션
        my_bar.progress(percent_complete + 1, text=progress_text)
    
    my_bar.empty()
    return DEMO_DATA

# --- 사이드바 UI ---
with st.sidebar:
    st.image("https://upload.wikimedia.org/wikipedia/commons/thumb/5/52/SK_logo.svg/1200px-SK_logo.svg.png", width=60)
    st.title("📂 리포트 업로드")
    
    st.info("본인의 진단 리포트(PDF)를 업로드해주세요. (개인정보 미저장)")
    
    leadership_file = st.file_uploader("1. 리더십 진단 보고서", type="pdf")
    oei_file = st.file_uploader("2. 조직효과성(OEI) 보고서", type="pdf")
    
    st.markdown("---")
    if st.button("🔄 분석 결과 초기화"):
        st.session_state.clear()
        st.rerun()

# --- 메인 로직 ---

# Session State 초기화
if "analyzed_data" not in st.session_state:
    st.session_state.analyzed_data = None
if "messages" not in st.session_state:
    st.session_state.messages = []

# 파일 업로드 처리
if leadership_file and oei_file and st.session_state.analyzed_data is None:
    l_text = extract_text_from_pdf(leadership_file)
    o_text = extract_text_from_pdf(oei_file)
    
    if l_text and o_text:
        data = analyze_report_data(l_text, o_text)
        st.session_state.analyzed_data = data
        
        # 코칭 챗봇 초기 메시지
        if not st.session_state.messages:
            gaps = [g for g in data['oei']['gaps'] if abs(g['self'] - g['team']) >= 0.5]
            main_issue = gaps[0]['category'] if gaps else "소통"
            
            welcome_msg = f"""반갑습니다, 팀장님. 분석이 완료되었습니다.
            
데이터를 보니 **'{main_issue}'** 항목에서 리더님과 구성원의 인식 차이가 발견되었습니다.
이 결과에 대해 어떻게 생각하시나요? 편하게 말씀해 주시면 대화를 이어가겠습니다."""
            
            st.session_state.messages.append({"role": "assistant", "content": welcome_msg})

# --- 화면 렌더링 ---

if st.session_state.analyzed_data is None:
    st.title("🏆 AI 리더십 코칭")
    st.markdown("""
    ### 환영합니다!
    이 앱은 리더십 진단 결과를 바탕으로 **개인 맞춤형 인사이트**와 **AI 코칭**을 제공합니다.
    
    **사용 방법:**
    1. 왼쪽 사이드바에서 **리더십 진단** 및 **OEI 보고서** PDF를 업로드하세요.
    2. AI가 데이터를 분석하여 대시보드를 생성합니다.
    3. **AI 코치**와 대화하며 Action Plan을 수립해보세요.
    """)
    st.warning("👈 왼쪽 사이드바를 열어 파일을 업로드해주세요.")

else:
    data = st.session_state.analyzed_data
    
    st.title("📊 진단 결과 분석")
    
    # 탭 재구성
    tabs = st.tabs(["종합 대시보드", "리더십 진단 심층분석", "조직효과성 진단 심층분석", "🤖 AI 코칭"])
    
    # [TAB 1] 종합 대시보드
    with tabs[0]:
        st.subheader("Overview")
        col1, col2 = st.columns(2)
        col1.metric("리더십 종합 점수", f"{data['leadership']['summary']} / 5.0", "+0.4 (그룹평균 대비)")
        col2.metric("조직효과성 (Output)", f"{data['oei']['summary']} / 5.0", "상위 20%")
        
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("##### 리더십 역량 밸런스")
            df_radar = pd.DataFrame(data['leadership']['details'])
            fig = go.Figure()
            fig.add_trace(go.Scatterpolar(r=df_radar['self'], theta=df_radar['category'], fill='toself', name='본인'))
            fig.add_trace(go.Scatterpolar(r=df_radar['group'], theta=df_radar['category'], fill='toself', name='그룹평균', opacity=0.5))
            fig.update_layout(polar=dict(radialaxis=dict(visible=True, range=[0, 5])), margin=dict(t=20, b=20), height=350)
            st.plotly_chart(fig, use_container_width=True)
            
        with c2:
            st.markdown("##### 조직 효과성 흐름 (I-P-O)")
            df_oei = pd.DataFrame(data['oei']['stages'])
            fig_bar = go.Figure([go.Bar(x=df_oei['stage'], y=df_oei['score'], marker_color=['#60a5fa', '#3b82f6', '#2563eb'])])
            fig_bar.update_yaxes(range=[0, 5.5])
            fig_bar.update_layout(margin=dict(t=20, b=20), height=350)
            st.plotly_chart(fig_bar, use_container_width=True)

    # [TAB 2] 리더십 진단 심층분석
    with tabs[1]:
        st.subheader("리더십 상세 분석")
        
        # 1. 항목별 점수차 (Gap Analysis)
        st.markdown("##### 1. 항목별 점수 및 인식 차이 (Self - Group)")
        df_detail = pd.DataFrame(data['leadership']['details'])
        df_detail['Gap'] = df_detail['self'] - df_detail['group']
        df_detail['Status'] = df_detail['Gap'].apply(lambda x: 'Over' if x > 0.5 else ('Under' if x < -0.5 else 'Fit'))
        
        # 차트로 시각화 (막대)
        fig_diff = go.Figure()
        fig_diff.add_trace(go.Bar(
            x=df_detail['category'], 
            y=df_detail['self'], 
            name='본인', 
            marker_color='#2563eb'
        ))
        fig_diff.add_trace(go.Bar(
            x=df_detail['category'], 
            y=df_detail['group'], 
            name='구성원', 
            marker_color='#94a3b8'
        ))
        fig_diff.update_layout(barmode='group', height=400, margin=dict(t=20, b=50))
        st.plotly_chart(fig_diff, use_container_width=True)

        # 2. 주관식 분석
        st.markdown("---")
        st.markdown("##### 2. 주관식 코멘트 분석")
        lc1, lc2 = st.columns(2)
        with lc1:
            st.info("**상사의 기대사항**")
            for comment in data['leadership']['comments']['boss']:
                st.write(f"- {comment}")
        with lc2:
            st.success("**구성원의 목소리**")
            for comment in data['leadership']['comments']['members']:
                st.write(f"- {comment}")

    # [TAB 3] 조직효과성 진단 심층분석
    with tabs[2]:
        st.subheader("조직 효과성(OEI) 상세 분석")
        
        # 1. Gap Analysis
        st.markdown("##### 1. 인식 차이 (Blind Spot & Hidden Strength)")
        st.caption("점수 차이가 0.5점 이상 나는 항목을 통해 인식의 맹점을 확인하세요.")
        
        gap_data = data['oei']['gaps']
        if gap_data:
            gap_df = pd.DataFrame(gap_data)
            def color_type(val):
                if val == 'Underestimation': return 'color: green; font-weight: bold' # 숨겨진 강점
                if val == 'Overestimation': return 'color: red; font-weight: bold'   # 맹점
                return ''
            
            st.dataframe(
                gap_df[['category', 'self', 'team', 'type']].style.applymap(color_type, subset=['type']),
                use_container_width=True,
                column_config={
                    "category": "항목",
                    "self": "본인 점수",
                    "team": "팀원 점수",
                    "type": "유형"
                }
            )
        else:
            st.write("특이한 인식 차이가 발견되지 않았습니다.")

        # 2. 주관식 분석
        st.markdown("---")
        st.markdown("##### 2. 팀 강점 및 보완점")
        oc1, oc2 = st.columns(2)
        with oc1:
            st.success("**팀 강점 (Strength)**")
            for s in data['oei']['comments']['strength']:
                st.write(f"💪 {s}")
        with oc2:
            st.error("**보완 필요점 (Weakness)**")
            for w in data['oei']['comments']['weakness']:
                st.write(f"⚠️ {w}")

    # [TAB 4] AI 코칭
    with tabs[3]:
        st.subheader("💬 AI 리더십 코치")
        st.markdown("분석된 데이터를 바탕으로 **Action Plan**을 수립하는 코칭 대화입니다.")
        
        chat_container = st.container()
        
        with chat_container:
            for msg in st.session_state.messages:
                with st.chat_message(msg["role"]):
                    st.write(msg["content"])
        
        if prompt := st.chat_input("답변을 입력하세요..."):
            if not OPENAI_API_KEY:
                st.error("API Key가 설정되지 않아 코칭을 진행할 수 없습니다.")
            else:
                st.chat_message("user").write(prompt)
                st.session_state.messages.append({"role": "user", "content": prompt})
                
                try:
                    client = openai.OpenAI(api_key=OPENAI_API_KEY)
                    
                    # 프롬프트 강화: 각 탭의 분석 내용 반영
                    system_instruction = f"""
                    너는 SK그룹의 리더십 코치야. 
                    사용자의 진단 데이터: {data}
                    
                    특히 다음 사항에 집중해:
                    1. 리더십 진단에서 본인({data['leadership']['summary']})과 그룹 간의 인식 차이.
                    2. OEI 진단에서의 맹점: {data['oei']['gaps']}
                    3. 구성원의 우려사항: {data['oei']['comments']['weakness']}
                    
                    GROW 모델로 코칭하고, 따뜻하지만 정곡을 찌르는 질문을 해줘.
                    """
                    
                    messages_payload = [{"role": "system", "content": system_instruction}] + st.session_state.messages
                    
                    with st.chat_message("assistant"):
                        stream = client.chat.completions.create(
                            model="gpt-5-nano",
                            messages=messages_payload,
                            stream=True
                        )
                        response = st.write_stream(stream)
                    
                    st.session_state.messages.append({"role": "assistant", "content": response})
                    
                except Exception as e:
                    st.error(f"오류가 발생했습니다: {e}")
