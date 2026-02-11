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
# 로컬에서는 .streamlit/secrets.toml 파일에서,
# 배포 환경(Streamlit Cloud)에서는 Settings > Secrets 에서 불러옵니다.
try:
    OPENAI_API_KEY = st.secrets["JYL"]
except FileNotFoundError:
    st.error("API Key 설정 파일을 찾을 수 없습니다. (.streamlit/secrets.toml)")
    st.stop()
except KeyError:
    st.error("Secrets에 'JYL' 키가 설정되지 않았습니다.")
    st.stop()

# --- 기본 데모 데이터 (파싱 실패 시 Fallback용) ---
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
        ]
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
        ],
        "comments": {
            "strength": ["개인 역량 존중", "자율적 분위기", "각자 일을 열심히 함", "소통과 배려"],
            "weakness": ["개인주의 우려", "적극적 소통 필요"]
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
    """
    실제로는 여기서 텍스트 내의 패턴(Regex)을 찾아 점수를 추출해야 합니다.
    현재 프로토타입에서는 파일이 업로드 되면 분석하는 척(Progress Bar) 하고,
    데모 데이터를 반환하여 화면을 구성합니다.
    """
    progress_text = "데이터 분석 중입니다. 잠시만 기다려주세요."
    my_bar = st.progress(0, text=progress_text)

    for percent_complete in range(100):
        time.sleep(0.01) # 분석 시뮬레이션
        my_bar.progress(percent_complete + 1, text=progress_text)
    
    my_bar.empty()
    
    # [TODO] 여기에 실제 파싱 로직을 구현하여 DEMO_DATA 구조에 맞춰 값을 채워넣으면 됩니다.
    # 현재는 데모 데이터를 그대로 반환합니다.
    return DEMO_DATA

# --- 사이드바 UI ---
with st.sidebar:
    st.image("https://upload.wikimedia.org/wikipedia/commons/thumb/5/52/SK_logo.svg/1200px-SK_logo.svg.png", width=60)
    st.title("📂 리포트 업로드")
    
    st.info("대상자 분들은 본인의 진단 리포트(PDF)를 아래에 업로드해주세요. 개인 정보는 저장되지 않습니다.")
    
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

# 파일이 업로드 되었고, 아직 분석 전이라면 분석 실행
if leadership_file and oei_file and st.session_state.analyzed_data is None:
    l_text = extract_text_from_pdf(leadership_file)
    o_text = extract_text_from_pdf(oei_file)
    
    if l_text and o_text:
        data = analyze_report_data(l_text, o_text)
        st.session_state.analyzed_data = data
        
        # 코칭 챗봇 초기 메시지 (분석 결과 기반)
        if not st.session_state.messages:
            gaps = [g for g in data['oei']['gaps'] if abs(g['self'] - g['team']) >= 0.5]
            main_issue = gaps[0]['category'] if gaps else "소통"
            gap_type = gaps[0]['type'] if gaps else "Alignment"
            
            context_msg = "팀장님은 스스로를 낮게 평가했지만 팀원들은 높게 평가했습니다." if gap_type == "Underestimation" else "팀원들의 생각보다 본인의 평가가 높습니다."

            welcome_msg = f"""반갑습니다, 팀장님. 업로드해주신 리포트 분석이 완료되었습니다. 
            
데이터를 보니 **'{main_issue}'** 항목에서 리더님과 구성원의 인식 차이가 발견되었습니다. ({context_msg})
            
이 결과에 대해 어떻게 생각하시나요? 편하게 말씀해 주시면 대화를 이어가겠습니다."""
            
            st.session_state.messages.append({"role": "assistant", "content": welcome_msg})

# --- 화면 렌더링 ---

if st.session_state.analyzed_data is None:
    # [초기 화면]
    st.title("🏆 AI 리더십 코칭 (Beta)")
    st.markdown("""
    ### 환영합니다!
    이 앱은 리더십 진단 결과를 바탕으로 **개인 맞춤형 인사이트**와 **AI 코칭**을 제공합니다.
    
    **사용 방법:**
    1. 왼쪽 사이드바에서 **리더십 진단 보고서**와 **OEI 보고서** PDF를 업로드하세요.
    2. AI가 자동으로 데이터를 추출하여 대시보드를 생성합니다.
    3. **AI 코치**와 대화하며 나만의 Action Plan을 수립해보세요.
    """)
    
    st.warning("👈 왼쪽 사이드바를 열어 파일을 업로드해주세요.")

else:
    # [분석 완료 대시보드 화면]
    data = st.session_state.analyzed_data
    
    st.title("📊 진단 결과 & AI 코칭")
    
    tab1, tab2, tab3 = st.tabs(["종합 대시보드", "인식 차이 분석", "🤖 AI 코칭"])
    
    # Tab 1: 종합 대시보드
    with tab1:
        col1, col2, col3 = st.columns(3)
        col1.metric("리더십 점수 (Self)", f"{data['leadership']['summary']}점", "+0.4 (그룹평균 대비)")
        col2.metric("조직효과성 (Output)", f"{data['oei']['summary']}점", "상위 20%")
        col3.metric("팀 강점 키워드", data['oei']['comments']['strength'][0])
        
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("리더십 역량 (Radar Chart)")
            df_radar = pd.DataFrame(data['leadership']['details'])
            fig = go.Figure()
            fig.add_trace(go.Scatterpolar(
                r=df_radar['self'], theta=df_radar['category'], fill='toself', name='본인', line_color='#2563eb'
            ))
            fig.add_trace(go.Scatterpolar(
                r=df_radar['group'], theta=df_radar['category'], fill='toself', name='그룹평균', line_color='#94a3b8', opacity=0.5
            ))
            fig.update_layout(polar=dict(radialaxis=dict(visible=True, range=[0, 5])), margin=dict(t=20, b=20))
            st.plotly_chart(fig, use_container_width=True)
            
        with c2:
            st.subheader("조직 효과성 (I-P-O)")
            df_oei = pd.DataFrame(data['oei']['stages'])
            fig_bar = go.Figure([go.Bar(x=df_oei['stage'], y=df_oei['score'], marker_color=['#60a5fa', '#3b82f6', '#2563eb'])])
            fig_bar.update_yaxes(range=[0, 5.5])
            fig_bar.update_layout(margin=dict(t=20, b=20))
            st.plotly_chart(fig_bar, use_container_width=True)

    # Tab 2: Gap 분석
    with tab2:
        st.subheader("👁️ 리더와 구성원의 인식 차이 (Blind Spot)")
        st.info("점수 차이가 **0.5점 이상** 나는 항목들입니다. 이 차이가 발생하는 원인을 파악하는 것이 코칭의 핵심입니다.")
        
        gap_data = data['oei']['gaps']
        if gap_data:
            gap_df = pd.DataFrame(gap_data)
            # 스타일링: Type에 따라 색상 변경
            def color_type(val):
                color = 'green' if val == 'Underestimation' else 'orange' if val == 'Overestimation' else 'black'
                return f'color: {color}; font-weight: bold'
            
            st.dataframe(gap_df.style.applymap(color_type, subset=['type']), use_container_width=True)
        else:
            st.write("특이한 인식 차이가 발견되지 않았습니다.")
            
        st.markdown("---")
        k1, k2 = st.columns(2)
        k1.success(f"**팀원들이 말하는 강점:** {', '.join(data['oei']['comments']['strength'])}")
        k2.warning(f"**팀원들의 우려사항:** {', '.join(data['oei']['comments']['weakness'])}")

    # Tab 3: AI 코칭 (Chatbot)
    with tab3:
        st.subheader("💬 AI 리더십 코치")
        st.markdown("분석된 데이터를 바탕으로 **실제 코칭 대화**를 진행합니다. 솔직하게 답변해 보세요.")
        
        # 채팅 히스토리 출력
        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]):
                st.write(msg["content"])
        
        # 사용자 입력 처리
        if prompt := st.chat_input("답변을 입력하세요..."):
            # 1. 사용자 메시지 표시
            st.chat_message("user").write(prompt)
            st.session_state.messages.append({"role": "user", "content": prompt})
            
            # 2. OpenAI API 호출 (심어둔 키 사용)
            try:
                client = openai.OpenAI(api_key=OPENAI_API_KEY)
                
                # 시스템 프롬프트: 분석 데이터를 컨텍스트로 주입
                system_instruction = f"""
                너는 10년차 전문 리더십 코치야. 사용자의 진단 데이터는 다음과 같아: {data}
                
                특히 '{data['oei']['gaps']}'의 인식 차이와 '{data['oei']['comments']['weakness']}'의 우려사항을 중점적으로 다뤄줘.
                
                [코칭 가이드]
                1. 사용자의 답변에 공감해주고, 구체적인 행동(Action Plan)을 이끌어내기 위한 질문을 던져.
                2. 한 번에 길게 설명하지 말고, 대화하듯이 짧게(3~4문장) 질문해.
                3. GROW 모델(Goal, Reality, Options, Will) 순서로 대화를 이끌어.
                4. 말투는 정중하면서도 따뜻하게("~하군요", "~어떠신가요?") 해줘.
                """
                
                messages_payload = [{"role": "system", "content": system_instruction}] + st.session_state.messages
                
                with st.chat_message("assistant"):
                    stream = client.chat.completions.create(
                        model="gpt-4o",  # 또는 gpt-3.5-turbo
                        messages=messages_payload,
                        stream=True
                    )
                    response = st.write_stream(stream)
                
                st.session_state.messages.append({"role": "assistant", "content": response})
                
            except Exception as e:
                st.error(f"오류가 발생했습니다: {e}")