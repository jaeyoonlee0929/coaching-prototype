import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import pdfplumber
import openai
import re
import time

# --- 페이지 설정 ---
st.set_page_config(
    page_title="AI 리더십 코칭 - SK",
    page_icon="🏆",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- [중요] API Key 로드 (JYL) ---
# .streamlit/secrets.toml 파일에 [JYL] 섹션이 있어야 함
try:
    OPENAI_API_KEY = st.secrets["JYL"]
except (FileNotFoundError, KeyError):
    OPENAI_API_KEY = None

# --- PDF 텍스트 추출 함수 ---
def extract_text_from_pdf(file):
    full_text = ""
    try:
        with pdfplumber.open(file) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    full_text += text + "\n"
        return full_text
    except Exception as e:
        st.error(f"PDF 읽기 오류: {e}")
        return ""

# --- 텍스트 전처리 함수 ---
def normalize_text(text):
    # 줄바꿈을 공백으로 변경하고, 다중 공백을 하나로 축소
    # 다만, 주관식 파싱을 위해 줄바꿈은 보존하는 버전도 필요할 수 있음
    # 여기서는 '검색용' 텍스트를 만듭니다.
    return re.sub(r'\s+', ' ', text).strip()

# --- 1. 리더십 진단 파싱 로직 ---
def parse_leadership_report(text):
    data = {
        "summary": 0.0,
        "details": [],
        "comments": {"boss": [], "members": []}
    }
    
    # 검색을 위해 공백 제거된 버전 생성 (항목명 매칭용)
    # 예: "SKMS에 대한 확신" -> "SKMS에대한확신"
    clean_text = re.sub(r'\s+', '', text)
    
    # [항목 매핑] PDF 내 텍스트(공백제거) : 표시할 이름
    items_map = {
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
    
    # 점수 추출: 항목명 뒤에 나오는 5.0 이하의 숫자(x.x) 패턴 찾기
    for pdf_key, label in items_map.items():
        # 패턴: 항목명 ... (0~5점 사이 숫자) ... (0~5점 사이 숫자)
        # 예: SKMS에대한확신 ... 4.8 ... 4.3
        # 주의: 2025, 14페이지 같은 숫자를 피하기 위해 [0-5]\.\d 패턴 사용
        pattern = re.compile(rf"{re.escape(pdf_key)}.*?([0-5]\.\d).*?([0-5]\.\d)", re.DOTALL)
        match = pattern.search(clean_text)
        
        if match:
            try:
                self_val = float(match.group(1))
                group_val = float(match.group(2))
                
                data["details"].append({
                    "category": label,
                    "self": self_val,
                    "group": group_val
                })
                scores.append(self_val)
            except ValueError:
                continue
    
    if scores:
        data["summary"] = round(sum(scores) / len(scores), 1)
    
    # --- 주관식 코멘트 추출 (원본 텍스트 기반) ---
    # 상사 응답
    if "상사 응답" in text:
        try:
            # "상사 응답" ~ "구성원 응답" 사이의 텍스트
            start = text.find("상사 응답")
            end = text.find("구성원 응답")
            section = text[start:end]
            
            # '·' (가운뎃점)으로 시작하는 문장만 추출
            lines = re.findall(r"[·]\s*(.*)", section)
            # 질문 텍스트("~모습은?", "~사항은?") 제외 필터링
            data["comments"]["boss"] = [l.strip() for l in lines if not l.strip().endswith('?')]
        except: pass

    # 구성원 응답
    if "구성원 응답" in text:
        try:
            # "구성원 응답" 이후 텍스트
            start = text.find("구성원 응답")
            section = text[start:]
            
            # '·' 로 시작하는 문장 추출
            lines = re.findall(r"[·]\s*(.*)", section)
            # 질문 및 페이지 번호 등 노이즈 제거
            clean_lines = []
            for l in lines:
                l = l.strip()
                if l.endswith('?') or "SK" in l or len(l) < 2:
                    continue
                clean_lines.append(l)
            
            # 상사 응답과 중복 제거
            data["comments"]["members"] = [c for c in clean_lines if c not in data["comments"]["boss"]]
        except: pass

    return data

# --- 2. OEI 진단 파싱 로직 ---
def parse_oei_report(text):
    data = {
        "summary": 0.0,
        "stages": [],
        "gaps": [],
        "comments": {"strength": [], "weakness": []}
    }
    
    clean_text = re.sub(r'\s+', '', text)
    
    # 1. Summary (Input, Process, Output)
    # Output 점수 추출
    # 패턴: Output ... 숫자
    match_out = re.search(r"Output.*?([0-5]\.\d)", clean_text)
    if match_out:
        data["summary"] = float(match_out.group(1))
        
    # Input, Process도 추출 시도
    for stage in ["Input", "Process", "Output"]:
        match = re.search(rf"{stage}.*?([0-5]\.\d)", clean_text)
        if match:
            data["stages"].append({"stage": stage, "score": float(match.group(1))})

    # 2. Gap 분석 (상세 항목)
    oei_items = [
        "명확한목표와업무방향", "목표달성을위한우선순위설정", "변화공감/지지",
        "자율적업무환경조성", "업무장애요인개선", "일하는방식의원칙·체계", "일과삶의균형",
        "조직목표인식", "개인역할/책임인식", "역량수준", "역량개발노력", "동기수준", "윤리의식", "상호존중",
        "경영층의관심", "R&C확보", "공정한평가", "성장기회",
        "SUPEX지향", "틀을깨는시도추구", "유연한사고", "적극적문제해결", "신속한상황인식",
        "의사결정참여", "자유로운의견제시", "상호협력", "정보공유", "다양성/포용성",
        "조직간협업", "협력적네트워크구축",
        "목표달성", "적시성", "혁신성", "지속가능성",
        "긍정적정서", "일에대한가치", "성취감", "개인성장", "미래기대"
    ]
    
    for item in oei_items:
        # OEI 리포트 순서: 항목명 ... 본인점수 ... 본인팀점수 ... (신임리더평균) ... (Percentile)
        # 예: 명확한목표와... 5.0 ... 4.8
        pattern = re.compile(rf"{re.escape(item)}.*?([0-5]\.\d).*?([0-5]\.\d)", re.DOTALL)
        match = pattern.search(clean_text)
        
        if match:
            try:
                self_val = float(match.group(1))
                team_val = float(match.group(2))
                
                # Gap 계산
                gap = team_val - self_val
                gap_type = "Alignment"
                if gap >= 0.5: gap_type = "Underestimation" # 숨겨진 강점
                if gap <= -0.5: gap_type = "Overestimation" # 맹점
                
                # 이름 복원 (가독성 위해)
                display_name = item
                
                if gap_type != "Alignment":
                    data["gaps"].append({
                        "category": display_name,
                        "self": self_val,
                        "team": team_val,
                        "type": gap_type
                    })
            except ValueError:
                continue

    # 3. 주관식 (강점/보완점) - 원본 텍스트 사용
    # 질문 텍스트 패턴 정의
    q_strength = "강점은 무엇입니까"
    q_weakness = "보완해야 할 점은 무엇입니까"
    q_obstacle = "장애요인"
    
    # 강점 추출
    if q_strength in text:
        start = text.find(q_strength)
        end = text.find(q_weakness) if q_weakness in text else len(text)
        block = text[start:end]
        # · 로 시작하는 줄 추출
        lines = re.findall(r"[·]\s*(.*)", block)
        data["comments"]["strength"] = [l.strip() for l in lines if not l.strip().endswith('?')]

    # 보완점 추출
    if q_weakness in text:
        start = text.find(q_weakness)
        end = text.find(q_obstacle) if q_obstacle in text else len(text)
        block = text[start:end]
        lines = re.findall(r"[·]\s*(.*)", block)
        data["comments"]["weakness"] = [l.strip() for l in lines if not l.strip().endswith('?')]

    return data

# --- 통합 분석 함수 ---
def analyze_reports(l_file, o_file):
    with st.spinner('PDF 데이터를 정밀 분석 중입니다...'):
        l_text = extract_text_from_pdf(l_file)
        o_text = extract_text_from_pdf(o_file)
        
        if not l_text or not o_text:
            return None
            
        l_data = parse_leadership_report(l_text)
        o_data = parse_oei_report(o_text)
        
        # 데이터가 너무 없으면(파싱 실패) None 반환
        if not l_data['details'] and not o_data['stages']:
            st.error("리포트 형식을 인식하지 못했습니다. 올바른 PDF 파일인지 확인해주세요.")
            return None
            
        return {"leadership": l_data, "oei": o_data}

# --- 사이드바 ---
with st.sidebar:
    st.title("📂 리포트 업로드")
    
    if not OPENAI_API_KEY:
        st.warning("⚠️ OpenAI API Key가 설정되지 않았습니다. AI 코칭 기능을 사용할 수 없습니다.")
        
    leadership_file = st.file_uploader("1. 리더십 진단 보고서 (PDF)", type="pdf")
    oei_file = st.file_uploader("2. 조직효과성(OEI) 보고서 (PDF)", type="pdf")
    
    st.divider()
    if st.button("🔄 초기화"):
        st.session_state.clear()
        st.rerun()

# --- 메인 로직 ---

if "analyzed_data" not in st.session_state:
    st.session_state.analyzed_data = None
if "messages" not in st.session_state:
    st.session_state.messages = []

# 파일 업로드 및 분석 실행
if leadership_file and oei_file and st.session_state.analyzed_data is None:
    result = analyze_reports(leadership_file, oei_file)
    if result:
        st.session_state.analyzed_data = result
        
        # 코칭 메시지 초기화
        if not st.session_state.messages:
            gaps = result['oei']['gaps']
            welcome_text = "반갑습니다, 팀장님. 리포트 분석이 완료되었습니다."
            
            if gaps:
                # 가장 큰 Gap 찾기
                max_gap_item = max(gaps, key=lambda x: abs(x['self'] - x['team']))
                issue = max_gap_item['category']
                type_desc = "과소평가(숨겨진 강점)" if max_gap_item['type'] == 'Underestimation' else "과대평가(인식의 맹점)"
                
                welcome_text += f"\n\n분석 결과, **'{issue}'** 항목에서 본인과 구성원의 인식 차이({type_desc})가 가장 두드러집니다.\n\n이 결과에 대해 어떻게 생각하시나요?"
            else:
                welcome_text += "\n\n리더님과 구성원의 인식이 전반적으로 잘 일치합니다. 현재 팀 운영에서 가장 고민되는 부분은 무엇인가요?"
                
            st.session_state.messages.append({"role": "assistant", "content": welcome_text})

# --- 화면 렌더링 ---

if st.session_state.analyzed_data is None:
    st.title("🏆 AI 리더십 코칭")
    st.info("왼쪽 사이드바에서 두 개의 진단 보고서(PDF)를 업로드해주세요.")
else:
    data = st.session_state.analyzed_data
    
    st.title("📊 진단 결과 분석")
    
    tabs = st.tabs(["종합 대시보드", "리더십 진단 심층분석", "조직효과성 진단 심층분석", "🤖 AI 코칭"])
    
    # [Tab 1] 종합 대시보드
    with tabs[0]:
        st.subheader("Overview")
        c1, c2 = st.columns(2)
        c1.metric("리더십 종합 점수 (Self)", f"{data['leadership']['summary']} / 5.0")
        c2.metric("조직효과성 (Output)", f"{data['oei']['summary']} / 5.0")
        
        c3, c4 = st.columns(2)
        with c3:
            st.markdown("##### 리더십 역량 (Radar)")
            df_l = pd.DataFrame(data['leadership']['details'])
            if not df_l.empty:
                fig = go.Figure()
                fig.add_trace(go.Scatterpolar(r=df_l['self'], theta=df_l['category'], fill='toself', name='본인'))
                fig.add_trace(go.Scatterpolar(r=df_l['group'], theta=df_l['category'], fill='toself', name='구성원'))
                fig.update_layout(polar=dict(radialaxis=dict(visible=True, range=[0, 5])), height=350, margin=dict(t=30, b=30))
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.warning("리더십 상세 데이터를 추출하지 못했습니다.")
        
        with c4:
            st.markdown("##### 조직 효과성 (I-P-O)")
            df_o = pd.DataFrame(data['oei']['stages'])
            if not df_o.empty:
                fig2 = go.Figure([go.Bar(x=df_o['stage'], y=df_o['score'], marker_color=['#60a5fa', '#3b82f6', '#2563eb'])])
                fig2.update_yaxes(range=[0, 5.5])
                fig2.update_layout(height=350, margin=dict(t=30, b=30))
                st.plotly_chart(fig2, use_container_width=True)
            else:
                st.warning("OEI 단계별 점수를 추출하지 못했습니다.")

    # [Tab 2] 리더십 심층분석
    with tabs[1]:
        st.subheader("리더십 역량 상세")
        df_l = pd.DataFrame(data['leadership']['details'])
        if not df_l.empty:
            # 점수 차이(Gap) 계산
            df_l['gap'] = df_l['self'] - df_l['group']
            
            fig3 = go.Figure()
            fig3.add_trace(go.Bar(x=df_l['category'], y=df_l['self'], name='본인'))
            fig3.add_trace(go.Bar(x=df_l['category'], y=df_l['group'], name='구성원'))
            fig3.update_layout(barmode='group', height=400)
            st.plotly_chart(fig3, use_container_width=True)
        
        st.divider()
        col_a, col_b = st.columns(2)
        with col_a:
            st.info("🗣️ 상사의 기대사항")
            if data['leadership']['comments']['boss']:
                for c in data['leadership']['comments']['boss']: st.write(f"- {c}")
            else: st.write("(추출된 데이터 없음)")
            
        with col_b:
            st.success("🗣️ 구성원의 목소리")
            if data['leadership']['comments']['members']:
                for c in data['leadership']['comments']['members']: st.write(f"- {c}")
            else: st.write("(추출된 데이터 없음)")

    # [Tab 3] OEI 심층분석
    with tabs[2]:
        st.subheader("인식 차이 (Blind Spot) 분석")
        gap_df = pd.DataFrame(data['oei']['gaps'])
        if not gap_df.empty:
            def highlight_type(val):
                color = 'green' if val == 'Underestimation' else 'red'
                return f'color: {color}; font-weight: bold'
            
            st.dataframe(
                gap_df[['category', 'self', 'team', 'type']].style.applymap(highlight_type, subset=['type']),
                use_container_width=True,
                column_config={
                    "category": "진단 항목",
                    "self": "본인 점수",
                    "team": "팀원 점수",
                    "type": "유형 (과소/과대평가)"
                }
            )
        else:
            st.info("💡 본인과 팀원 간의 유의미한 점수 차이(0.5점 이상)가 발견되지 않았습니다.")
            
        st.divider()
        c_str, c_weak = st.columns(2)
        with c_str:
            st.success("💪 우리 팀 강점")
            if data['oei']['comments']['strength']:
                for c in data['oei']['comments']['strength']: st.write(f"• {c}")
            else: st.write("(데이터 없음)")
            
        with c_weak:
            st.error("⚠️ 보완 필요점")
            if data['oei']['comments']['weakness']:
                for c in data['oei']['comments']['weakness']: st.write(f"• {c}")
            else: st.write("(데이터 없음)")

    # [Tab 4] AI 코칭
    with tabs[3]:
        st.subheader("💬 AI 코칭 대화")
        
        # 채팅 히스토리 표시
        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]):
                st.write(msg["content"])
        
        # 사용자 입력 처리
        if prompt := st.chat_input("답변을 입력해주세요..."):
            # 1. 사용자 메시지 추가
            st.session_state.messages.append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.write(prompt)
            
            # 2. AI 응답 생성
            if OPENAI_API_KEY:
                try:
                    client = openai.OpenAI(api_key=OPENAI_API_KEY)
                    
                    # 시스템 프롬프트 구성
                    system_msg = f"""
                    당신은 SK그룹의 리더십 전문 코치입니다.
                    사용자의 진단 데이터: {data}
                    
                    [코칭 목표]
                    사용자가 자신의 리더십 스타일과 팀 상황을 객관적으로 인식하고, 구체적인 개선 행동(Action Plan)을 수립하도록 돕습니다.
                    
                    [대화 가이드]
                    1. 인식 차이 항목({data['oei']['gaps']})과 구성원 보완점({data['oei']['comments']['weakness']})을 근거로 질문하세요.
                    2. GROW 모델(Goal -> Reality -> Options -> Will) 단계에 맞춰 대화를 진행하세요.
                    3. 한 번에 하나의 질문만 짧게 던지세요.
                    4. 상대방의 말에 공감한 뒤 질문하세요.
                    """
                    
                    # 메시지 컨텍스트 구성
                    api_messages = [{"role": "system", "content": system_msg}]
                    for m in st.session_state.messages:
                        api_messages.append({"role": m["role"], "content": m["content"]})
                    
                    with st.chat_message("assistant"):
                        stream = client.chat.completions.create(
                            model="gpt-4o", 
                            messages=api_messages,
                            stream=True
                        )
                        response = st.write_stream(stream)
                    
                    st.session_state.messages.append({"role": "assistant", "content": response})
                    
                except Exception as e:
                    st.error(f"AI 연결 오류: {e}")
            else:
                st.warning("API Key가 설정되지 않아 AI가 응답할 수 없습니다. 관리자에게 문의해주세요.")
