import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import pdfplumber
import openai
import os
import time
import re

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
    OPENAI_API_KEY = None
except KeyError:
    st.error("Secrets에 'JYL' 키가 설정되지 않았습니다.")
    st.stop()

# --- 기본 데모 데이터 (파싱 실패 시 Fallback) ---
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
            "boss": ["(데이터 추출 실패) - 데모 데이터입니다."],
            "members": ["(데이터 추출 실패) - 데모 데이터입니다."]
        }
    },
    "oei": {
        "summary": 4.6,
        "stages": [
            {"stage": "Input", "score": 4.6},
            {"stage": "Process", "score": 4.5},
            {"stage": "Output", "score": 4.7},
        ],
        "gaps": [],
        "comments": {
            "strength": ["(데이터 추출 실패)"],
            "weakness": ["(데이터 추출 실패)"]
        }
    }
}

# --- 1. PDF 텍스트 추출 ---
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
        st.error(f"PDF 읽기 오류: {e}")
        return ""

# --- 2. 리더십 진단 파싱 로직 ---
def parse_leadership_text(text):
    data = {"summary": 0.0, "details": [], "comments": {"boss": [], "members": []}}
    
    # 텍스트 정규화 (공백 제거 등으로 매칭 확률 높임)
    clean_text = text.replace(" ", "")
    
    # 카테고리 매핑 (PDF 내 실제 텍스트 -> 표시할 이름)
    # 정규표현식으로 찾기 위해 공백을 제거한 키워드를 사용
    categories = {
        "SKMS에대한확신": "SKMS 확신",
        "패기/솔선수범": "패기/솔선수범",
        "Integrity": "Integrity",
        "경영환경이해": "경영환경 이해",
        "팀목표방향수립": "팀 목표 수립",
        "변화주도": "변화 주도",
        "도전적목표설정": "도전적 목표",
        "팀워크발휘": "팀워크 발휘",
        "과감하고빠른실행": "과감한 실행",
        "자율적업무환경조성": "자율환경 조성",
        "소통": "소통",
        "구성원육성": "구성원 육성"
    }
    
    scores = []
    # 점수 추출 (패턴: 카테고리...숫자.숫자...숫자.숫자)
    # 예: SKMS에대한확신 ... 4.8 ... 4.3
    for key, label in categories.items():
        # 카테고리 뒤에 나오는 x.x 형태의 숫자 2개를 찾음 (본인, 그룹)
        # PDF 순서상 본인이 먼저 나오고 그룹이 나중에 나온다고 가정
        pattern = re.compile(rf"{re.escape(key)}.*?(\d\.\d).*?(\d\.\d)", re.DOTALL)
        match = pattern.search(clean_text)
        
        if match:
            self_score = float(match.group(1))
            group_score = float(match.group(2))
            data["details"].append({"category": label, "self": self_score, "group": group_score})
            scores.append(self_score)
    
    # 데이터가 없으면 None 반환 (데모 데이터 사용 유도)
    if not data["details"]:
        return None
        
    data["summary"] = round(sum(scores) / len(scores), 1)

    # 주관식 코멘트 추출 (섹션 헤더 기준 분리)
    # 원본 텍스트 사용 (공백 유지)
    if "상사 응답" in text and "구성원 응답" in text:
        try:
            boss_part = text.split("상사 응답")[1].split("구성원 응답")[0]
            # 점(·)으로 시작하는 문장 추출
            boss_comments = [line.strip() for line in boss_part.split('\n') if "·" in line or len(line.strip()) > 10]
            data["comments"]["boss"] = boss_comments[:3]
        except: pass
        
    if "구성원 응답" in text:
        try:
            # 뒷부분 전체 혹은 다음 섹션 전까지
            member_part = text.split("구성원 응답")[1]
            if "Review Questions" in member_part:
                member_part = member_part.split("Review Questions")[0]
            
            member_comments = [line.strip() for line in member_part.split('\n') if "·" in line or len(line.strip()) > 10]
            data["comments"]["members"] = member_comments[:4]
        except: pass

    return data

# --- 3. OEI 진단 파싱 로직 ---
def parse_oei_text(text):
    data = {"summary": 0.0, "stages": [], "gaps": [], "comments": {"strength": [], "weakness": []}}
    
    # Summary Scores (Input, Process, Output)
    # 보통 Snapshot 페이지에 Input x.x Process x.x Output x.x 형태로 나옴
    stages = ["Input", "Process", "Output"]
    summary_scores = {}
    
    for stage in stages:
        # Input ... 4.6 찾기
        match = re.search(rf"{stage}.*?(\d\.\d)", text)
        if match:
            summary_scores[stage] = float(match.group(1))
        else:
            summary_scores[stage] = 0.0
            
    data["stages"] = [
        {"stage": "Input", "score": summary_scores.get("Input", 0)},
        {"stage": "Process", "score": summary_scores.get("Process", 0)},
        {"stage": "Output", "score": summary_scores.get("Output", 0)}
    ]
    data["summary"] = summary_scores.get("Output", 0.0)

    # Gap Analysis를 위한 세부 항목 파싱
    # 항목명 ... 본인점수 ... 팀점수
    # 주요 OEI 항목 리스트 (일부 예시)
    oei_items = [
        "명확한 목표와 업무 방향", "목표 달성을 위한 우선순위 설정", "변화 공감/지지",
        "자율적 업무 환경 조성", "업무 장애요인 개선", "일하는 방식의 원칙", "일과 삶의 균형",
        "조직 목표 인식", "개인 역할/책임 인식", "상호 존중", "경영층의 관심", "R&C 확보",
        "SUPEX 지향", "틀을 깨는 시도 추구", "유연한 사고", "적극적 문제 해결", "신속한 상황 인식",
        "상호 협력", "정보 공유", "다양성/포용성"
    ]
    
    clean_text = text.replace(" ", "")
    
    for item in oei_items:
        clean_item = item.replace(" ", "")
        # 본인점수(x.x) ... 팀점수(x.x)
        pattern = re.compile(rf"{re.escape(clean_item)}.*?(\d\.\d).*?(\d\.\d)", re.DOTALL)
        match = pattern.search(clean_text)
        
        if match:
            self_score = float(match.group(1))
            team_score = float(match.group(2))
            
            diff = team_score - self_score
            gap_type = "Alignment"
            
            # 차이가 0.5 이상인 경우만 기록
            if diff >= 0.5: gap_type = "Underestimation" # 나는 낮게, 팀은 높게 (숨겨진 강점)
            if diff <= -0.5: gap_type = "Overestimation" # 나는 높게, 팀은 낮게 (맹점)
            
            if gap_type != "Alignment":
                data["gaps"].append({
                    "category": item,
                    "self": self_score,
                    "team": team_score,
                    "type": gap_type
                })
    
    # 주관식 코멘트 (강점, 보완점)
    if "강점은 무엇입니까" in text:
        try:
            part = text.split("강점은 무엇입니까")[1].split("보완해야 할 점")[0]
            lines = [l.strip() for l in part.split('\n') if len(l.strip()) > 2]
            data["comments"]["strength"] = lines[:3]
        except: pass
        
    if "보완해야 할 점은 무엇입니까" in text:
        try:
            part = text.split("보완해야 할 점은 무엇입니까")[1]
            if "장애요인" in part:
                part = part.split("장애요인")[0]
            lines = [l.strip() for l in part.split('\n') if len(l.strip()) > 2]
            data["comments"]["weakness"] = lines[:3]
        except: pass

    return data

# --- 데이터 통합 분석 함수 ---
def analyze_report_data(l_text, o_text):
    progress_text = "PDF 데이터를 정밀 분석 중입니다..."
    my_bar = st.progress(0, text=progress_text)

    # 1. 리더십 데이터 파싱
    leadership_data = parse_leadership_text(l_text)
    my_bar.progress(50, text="리더십 역량 점수 추출 완료")
    
    # 2. OEI 데이터 파싱
    oei_data = parse_oei_text(o_text)
    my_bar.progress(90, text="조직 효과성 및 Gap 분석 완료")
    
    time.sleep(0.5)
    my_bar.empty()
    
    # 파싱 실패 시 데모 데이터 반환
    if not leadership_data:
        st.toast("리더십 리포트 파싱 실패. 데모 데이터를 표시합니다.", icon="⚠️")
        return DEMO_DATA
        
    return {
        "leadership": leadership_data,
        "oei": oei_data
    }

# --- 사이드바 UI ---
with st.sidebar:
    st.image("https://upload.wikimedia.org/wikipedia/commons/thumb/5/52/SK_logo.svg/1200px-SK_logo.svg.png", width=60)
    st.title("📂 리포트 업로드")
    
    st.info("본인의 진단 리포트(PDF)를 업로드해주세요.")
    
    leadership_file = st.file_uploader("1. 리더십 진단 보고서", type="pdf")
    oei_file = st.file_uploader("2. 조직효과성(OEI) 보고서", type="pdf")
    
    st.markdown("---")
    if st.button("🔄 분석 결과 초기화"):
        st.session_state.clear()
        st.rerun()

# --- 메인 로직 ---

if "analyzed_data" not in st.session_state:
    st.session_state.analyzed_data = None
if "messages" not in st.session_state:
    st.session_state.messages = []

# 파일 업로드 시 분석 수행
if leadership_file and oei_file and st.session_state.analyzed_data is None:
    l_text = extract_text_from_pdf(leadership_file)
    o_text = extract_text_from_pdf(oei_file)
    
    if l_text and o_text:
        data = analyze_report_data(l_text, o_text)
        st.session_state.analyzed_data = data
        
        # 코칭 챗봇 초기 메시지
        if not st.session_state.messages:
            gaps = data['oei']['gaps']
            if gaps:
                main_issue = gaps[0]['category']
                gap_type = "과소평가" if gaps[0]['type'] == 'Underestimation' else "과대평가"
                welcome_msg = f"""반갑습니다, 팀장님. 리포트 분석이 완료되었습니다.
                
분석 결과, **'{main_issue}'** 항목에서 본인과 구성원의 인식 차이({gap_type})가 가장 크게 나타났습니다.
이 결과에 대해 어떻게 생각하시나요?"""
            else:
                welcome_msg = "반갑습니다. 분석 결과, 리더님과 구성원의 인식이 전반적으로 잘 일치하고 있습니다. 가장 고민되시는 점은 무엇인가요?"
                
            st.session_state.messages.append({"role": "assistant", "content": welcome_msg})

# --- 화면 렌더링 ---

if st.session_state.analyzed_data is None:
    st.title("🏆 AI 리더십 코칭")
    st.markdown("리포트를 업로드하면 실제 데이터를 분석하여 대시보드를 생성합니다.")
    st.warning("👈 왼쪽 사이드바에서 파일을 업로드해주세요.")

else:
    data = st.session_state.analyzed_data
    
    st.title("📊 진단 결과 분석")
    
    tabs = st.tabs(["종합 대시보드", "리더십 진단 심층분석", "조직효과성 진단 심층분석", "🤖 AI 코칭"])
    
    # [TAB 1] 종합 대시보드
    with tabs[0]:
        st.subheader("Overview")
        col1, col2 = st.columns(2)
        col1.metric("리더십 종합 점수 (Self)", f"{data['leadership']['summary']} / 5.0")
        col2.metric("조직효과성 (Output)", f"{data['oei']['summary']} / 5.0")
        
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("##### 리더십 역량 밸런스")
            df_radar = pd.DataFrame(data['leadership']['details'])
            if not df_radar.empty:
                fig = go.Figure()
                fig.add_trace(go.Scatterpolar(r=df_radar['self'], theta=df_radar['category'], fill='toself', name='본인'))
                fig.add_trace(go.Scatterpolar(r=df_radar['group'], theta=df_radar['category'], fill='toself', name='그룹평균', opacity=0.5))
                fig.update_layout(polar=dict(radialaxis=dict(visible=True, range=[0, 5])), margin=dict(t=20, b=20), height=350)
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.write("리더십 상세 데이터가 없습니다.")
            
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
        
        df_detail = pd.DataFrame(data['leadership']['details'])
        if not df_detail.empty:
            st.markdown("##### 1. 항목별 점수 및 인식 차이 (Self - Group)")
            fig_diff = go.Figure()
            fig_diff.add_trace(go.Bar(x=df_detail['category'], y=df_detail['self'], name='본인', marker_color='#2563eb'))
            fig_diff.add_trace(go.Bar(x=df_detail['category'], y=df_detail['group'], name='구성원', marker_color='#94a3b8'))
            fig_diff.update_layout(barmode='group', height=400, margin=dict(t=20, b=50))
            st.plotly_chart(fig_diff, use_container_width=True)
        
        st.markdown("---")
        st.markdown("##### 2. 주관식 코멘트 분석")
        lc1, lc2 = st.columns(2)
        with lc1:
            st.info("**상사의 기대사항**")
            for c in data['leadership']['comments'].get('boss', []): st.write(f"- {c}")
        with lc2:
            st.success("**구성원의 목소리**")
            for c in data['leadership']['comments'].get('members', []): st.write(f"- {c}")

    # [TAB 3] 조직효과성 진단 심층분석
    with tabs[2]:
        st.subheader("조직 효과성(OEI) 상세 분석")
        
        st.markdown("##### 1. 인식 차이 (Blind Spot)")
        gap_data = data['oei'].get('gaps', [])
        if gap_data:
            gap_df = pd.DataFrame(gap_data)
            def color_type(val):
                if val == 'Underestimation': return 'color: green; font-weight: bold'
                if val == 'Overestimation': return 'color: red; font-weight: bold'
                return ''
            
            st.dataframe(
                gap_df[['category', 'self', 'team', 'type']].style.applymap(color_type, subset=['type']),
                use_container_width=True
            )
        else:
            st.info("특이한 인식 차이가 발견되지 않았습니다. (데이터가 없거나 일치함)")

        st.markdown("---")
        st.markdown("##### 2. 팀 강점 및 보완점")
        oc1, oc2 = st.columns(2)
        with oc1:
            st.success("**팀 강점**")
            for c in data['oei']['comments'].get('strength', []): st.write(f"💪 {c}")
        with oc2:
            st.error("**보완 필요점**")
            for c in data['oei']['comments'].get('weakness', []): st.write(f"⚠️ {c}")

    # [TAB 4] AI 코칭
    with tabs[3]:
        st.subheader("💬 AI 리더십 코치")
        
        chat_container = st.container()
        with chat_container:
            for msg in st.session_state.messages:
                with st.chat_message(msg["role"]):
                    st.write(msg["content"])
        
        if prompt := st.chat_input("답변을 입력하세요..."):
            if not OPENAI_API_KEY:
                st.error("API Key가 설정되지 않았습니다.")
            else:
                st.chat_message("user").write(prompt)
                st.session_state.messages.append({"role": "user", "content": prompt})
                
                try:
                    client = openai.OpenAI(api_key=OPENAI_API_KEY)
                    system_instruction = f"""
                    너는 SK그룹의 리더십 코치야. 사용자의 진단 데이터: {data}
                    GROW 모델로 코칭하고, 인식 차이({data['oei']['gaps']})와 보완점({data['oei']['comments'].get('weakness')})을 해결하는 질문을 던져줘.
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
                    st.error(f"오류: {e}")
