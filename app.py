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

# --- 1. 리더십 진단 파싱 로직 (수정됨) ---
def parse_leadership_report(text):
    data = {
        "summary": 0.0,
        "details": [],
        "comments": {"boss": [], "members": []}
    }
    
    # 공백 제거 텍스트 (검색용)
    clean_text = re.sub(r'\s+', '', text)
    
    # 1. 항목별 점수 추출 ('문항별 점수' 섹션 타겟팅)
    # 문항별 점수 섹션은 보통 12~13페이지에 걸쳐 있음.
    # [수정] '문항별점수' 키워드 이후의 *모든* 텍스트를 합쳐서 검색 대상(target_section)으로 설정
    # 기존에는 [-1]로 마지막 부분만 가져와서 앞 페이지 데이터가 누락됨
    if "문항별점수" in clean_text:
        target_section = "".join(clean_text.split("문항별점수")[1:])
    else:
        target_section = clean_text

    # 항목 매핑 (Regex 패턴 : 표시 이름)
    items_map = {
        r"SKMS.*?확신": "SKMS 확신",
        r"패기.*?솔선수범": "패기/솔선수범",
        r"Integrity": "Integrity",
        r"경영환경.*?이해": "경영환경 이해",
        r"팀.*?목표.*?수립": "팀 목표 수립",
        r"변화.*?주도": "변화 주도",
        r"도전적.*?목표": "도전적 목표",
        r"팀워크.*?발휘": "팀워크 발휘",
        r"과감.*?실행": "과감한 실행",
        r"자율.*?환경.*?조성": "자율환경 조성",
        r"소통": "소통",
        r"구성원.*?육성": "구성원 육성"
    }

    scores = []
    
    for pattern_str, label in items_map.items():
        # 패턴: 항목명 ... 본인점수(x.x) ... 그룹점수(x.x)
        regex = re.compile(rf"{pattern_str}.*?([0-5]\.\d).*?([0-5]\.\d)", re.DOTALL)
        match = regex.search(target_section)
        
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
    
    # 종합 점수 (평균)
    if scores:
        data["summary"] = round(sum(scores) / len(scores), 1)
    
    # 2. 주관식 코멘트 추출
    if "상사 응답" in text:
        try:
            start = text.find("상사 응답")
            end = text.find("구성원 응답")
            block = text[start:end]
            lines = re.findall(r"[·]\s*(.*)", block)
            data["comments"]["boss"] = [l.strip() for l in lines if len(l.strip()) > 5]
        except: pass

    if "구성원 응답" in text:
        try:
            start = text.find("구성원 응답")
            end = text.find("Review Questions") if "Review Questions" in text else len(text)
            block = text[start:end]
            lines = re.findall(r"[·]\s*(.*)", block)
            clean_lines = []
            for l in lines:
                l = l.strip()
                if len(l) > 2 and "SK" not in l and not l.endswith("?"):
                    clean_lines.append(l)
            boss_comments = set(data["comments"]["boss"])
            data["comments"]["members"] = [c for c in clean_lines if c not in boss_comments]
        except: pass

    return data

# --- 2. OEI 진단 파싱 로직 (수정됨) ---
def parse_oei_report(text):
    data = {
        "summary": 0.0,
        "stages": [],
        "gaps": [],
        "comments": {"strength": [], "weakness": []}
    }
    
    clean_text = re.sub(r'\s+', '', text)
    
    # 1. 종합 점수 추출 (Output 점수가 아님)
    # 리포트 7페이지 상단: 【조직 효과성 점수 4.6점】
    # [수정] 정규표현식 유연하게 변경 (중간 문자 허용)
    match_total = re.search(r"조직효과성점수.*?([0-5]\.\d)", clean_text)
    if match_total:
        data["summary"] = float(match_total.group(1))
    
    # 2. I-P-O 단계별 점수 추출
    # [수정] Snapshot 섹션을 우선적으로 찾아서 그 안의 Input/Process/Output 점수를 추출
    # 이렇게 해야 뒤에 나오는 표 안의 'Input' 텍스트와 혼동하지 않음
    target_section = clean_text
    if "Snapshot" in clean_text:
        target_section = clean_text.split("Snapshot")[-1]
    elif "진단결과요약" in clean_text:
        target_section = clean_text.split("진단결과요약")[-1]
        
    # Input 점수
    m_input = re.search(r"Input.*?([0-5]\.\d)", target_section)
    if m_input:
        data["stages"].append({"stage": "Input", "score": float(m_input.group(1))})
        
    # Process 점수
    m_process = re.search(r"Process.*?([0-5]\.\d)", target_section)
    if m_process:
        data["stages"].append({"stage": "Process", "score": float(m_process.group(1))})
        
    # Output 점수
    m_output = re.search(r"Output.*?([0-5]\.\d)", target_section)
    if m_output:
        data["stages"].append({"stage": "Output", "score": float(m_output.group(1))})

    # 만약 위에서 못 찾았다면 전체 텍스트에서 시도 (Fallback)
    if not data["stages"]:
        for stage in ["Input", "Process", "Output"]:
            match = re.search(rf"{stage}.*?([0-5]\.\d)", clean_text)
            if match:
                data["stages"].append({"stage": stage, "score": float(match.group(1))})

    # 3. Gap 분석 (기존 로직 유지)
    oei_items = [
        "명확한목표와업무방향", "목표달성을위한우선순위설정", "변화공감/지지",
        "자율적업무환경조성", "업무장애요인개선", "일하는방식의원칙", "일과삶의균형",
        "조직목표인식", "개인역할", "역량수준", "역량개발노력", "동기수준", "윤리의식", "상호존중",
        "경영층의관심", "R&C확보", "공정한평가", "성장기회",
        "SUPEX지향", "틀을깨는시도", "유연한사고", "적극적문제해결", "신속한상황인식",
        "의사결정참여", "자유로운의견제시", "상호협력", "정보공유", "다양성",
        "조직간협업", "협력적네트워크",
        "목표달성", "적시성", "혁신성", "지속가능성",
        "긍정적정서", "일에대한가치", "성취감", "개인성장", "미래기대"
    ]
    
    for item in oei_items:
        pattern = re.compile(rf"{re.escape(item)}.*?([0-5]\.\d).*?([0-5]\.\d)", re.DOTALL)
        match = pattern.search(clean_text)
        
        if match:
            try:
                self_val = float(match.group(1))
                team_val = float(match.group(2))
                gap = team_val - self_val
                
                gap_type = "Alignment"
                if gap >= 0.5: gap_type = "Underestimation"
                if gap <= -0.5: gap_type = "Overestimation"
                
                if gap_type != "Alignment":
                    disp = item.replace("R&C", "R&C ").replace("목표", " 목표")
                    data["gaps"].append({
                        "category": disp,
                        "self": self_val,
                        "team": team_val,
                        "type": gap_type
                    })
            except: continue

    # 4. 주관식 (강점/보완점)
    q_strength = "강점은 무엇입니까"
    q_weakness = "보완해야 할 점은 무엇입니까"
    
    if q_strength in text:
        start = text.find(q_strength)
        end = text.find(q_weakness) if q_weakness in text else len(text)
        lines = re.findall(r"[·]\s*(.*)", text[start:end])
        data["comments"]["strength"] = [l.strip() for l in lines if len(l) > 2][:5]

    if q_weakness in text:
        start = text.find(q_weakness)
        end = text.find("장애요인") if "장애요인" in text else len(text)
        lines = re.findall(r"[·]\s*(.*)", text[start:end])
        data["comments"]["weakness"] = [l.strip() for l in lines if len(l) > 2][:5]

    return data

# --- 통합 분석 함수 ---
def analyze_reports(l_file, o_file):
    with st.spinner('리포트를 분석 중입니다...'):
        l_text = extract_text_from_pdf(l_file)
        o_text = extract_text_from_pdf(o_file)
        
        if not l_text or not o_text:
            return None
            
        l_data = parse_leadership_report(l_text)
        o_data = parse_oei_report(o_text)
        
        return {"leadership": l_data, "oei": o_data}

# --- 사이드바 ---
with st.sidebar:
    st.title("📂 리포트 업로드")
    
    if not OPENAI_API_KEY:
        st.warning("⚠️ OpenAI API Key 미설정 (코칭 불가)")
        
    leadership_file = st.file_uploader("1. 리더십 진단 보고서", type="pdf")
    oei_file = st.file_uploader("2. 조직효과성(OEI) 보고서", type="pdf")
    
    st.divider()
    if st.button("🔄 초기화"):
        st.session_state.clear()
        st.rerun()

# --- 메인 로직 ---

if "analyzed_data" not in st.session_state:
    st.session_state.analyzed_data = None
if "messages" not in st.session_state:
    st.session_state.messages = []

# 파일 업로드 및 분석
if leadership_file and oei_file and st.session_state.analyzed_data is None:
    result = analyze_reports(leadership_file, oei_file)
    if result:
        st.session_state.analyzed_data = result
        
        # 코칭 메시지 초기화
        if not st.session_state.messages:
            gaps = result['oei']['gaps']
            welcome = "반갑습니다. 리포트 분석이 완료되었습니다."
            if gaps:
                top_gap = max(gaps, key=lambda x: abs(x['self'] - x['team']))
                issue = top_gap['category']
                welcome += f"\n\n**'{issue}'** 항목에서 인식 차이가 큽니다. 이에 대해 이야기를 나눠볼까요?"
            st.session_state.messages.append({"role": "assistant", "content": welcome})

# --- 화면 렌더링 ---

if st.session_state.analyzed_data is None:
    st.title("🏆 AI 리더십 코칭")
    st.info("왼쪽에서 리포트 파일을 업로드해주세요.")
else:
    data = st.session_state.analyzed_data
    
    st.title("📊 진단 결과 분석")
    
    tabs = st.tabs(["종합 대시보드", "리더십 심층분석", "조직효과성 심층분석", "AI 코칭"])
    
    # [Tab 1] 종합 대시보드
    with tabs[0]:
        st.subheader("Overview")
        c1, c2 = st.columns(2)
        # 리더십 점수: summary (평균값)
        c1.metric("리더십 종합 점수 (Self)", f"{data['leadership']['summary']} / 5.0")
        # OEI 점수: Overall Score (Output이 아님)
        c2.metric("조직효과성 종합 점수", f"{data['oei']['summary']} / 5.0")
        
        c3, c4 = st.columns(2)
        with c3:
            st.markdown("##### 리더십 역량 (Radar)")
            df_l = pd.DataFrame(data['leadership']['details'])
            if not df_l.empty:
                fig = go.Figure()
                fig.add_trace(go.Scatterpolar(r=df_l['self'], theta=df_l['category'], fill='toself', name='본인'))
                fig.add_trace(go.Scatterpolar(r=df_l['group'], theta=df_l['category'], fill='toself', name='구성원'))
                fig.update_layout(polar=dict(radialaxis=dict(visible=True, range=[0, 5])), margin=dict(t=30, b=30), height=350)
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.warning("리더십 상세 데이터를 찾지 못했습니다.")
        
        with c4:
            st.markdown("##### 조직 효과성 흐름 (I-P-O)")
            # I-P-O 차트
            df_o = pd.DataFrame(data['oei']['stages'])
            if not df_o.empty:
                # 순서 보장 (Input -> Process -> Output)
                order_map = {'Input': 0, 'Process': 1, 'Output': 2}
                df_o['order'] = df_o['stage'].map(order_map)
                df_o = df_o.sort_values('order')
                
                fig2 = go.Figure([go.Bar(x=df_o['stage'], y=df_o['score'], marker_color=['#60a5fa', '#3b82f6', '#2563eb'])])
                fig2.update_yaxes(range=[0, 5.5])
                fig2.update_layout(margin=dict(t=30, b=30), height=350)
                st.plotly_chart(fig2, use_container_width=True)
            else:
                st.warning("OEI 단계별 점수를 찾지 못했습니다.")

    # [Tab 2] 리더십 심층분석
    with tabs[1]:
        st.subheader("리더십 역량 상세")
        df_l = pd.DataFrame(data['leadership']['details'])
        if not df_l.empty:
            fig3 = go.Figure()
            fig3.add_trace(go.Bar(x=df_l['category'], y=df_l['self'], name='본인'))
            fig3.add_trace(go.Bar(x=df_l['category'], y=df_l['group'], name='구성원'))
            fig3.update_layout(barmode='group', height=400)
            st.plotly_chart(fig3, use_container_width=True)
        
        st.divider()
        col_a, col_b = st.columns(2)
        with col_a:
            st.info("🗣️ 상사의 기대사항")
            for c in data['leadership']['comments']['boss']: st.write(f"- {c}")
        with col_b:
            st.success("🗣️ 구성원의 목소리")
            for c in data['leadership']['comments']['members']: st.write(f"- {c}")

    # [Tab 3] OEI 심층분석
    with tabs[2]:
        st.subheader("인식 차이 (Blind Spot)")
        gap_df = pd.DataFrame(data['oei']['gaps'])
        if not gap_df.empty:
            def style_gap(val):
                color = 'green' if val == 'Underestimation' else 'red'
                return f'color: {color}; font-weight: bold'
            st.dataframe(gap_df.style.applymap(style_gap, subset=['type']), use_container_width=True)
        else:
            st.info("특이한 인식 차이가 발견되지 않았습니다.")
            
        st.divider()
        c_str, c_weak = st.columns(2)
        with c_str:
            st.success("💪 팀 강점")
            for c in data['oei']['comments']['strength']: st.write(f"• {c}")
        with c_weak:
            st.error("⚠️ 보완 필요점")
            for c in data['oei']['comments']['weakness']: st.write(f"• {c}")

    # [Tab 4] AI 코칭
    with tabs[3]:
        st.subheader("💬 AI 코칭")
        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]):
                st.write(msg["content"])
        
        if prompt := st.chat_input("답변 입력..."):
            st.session_state.messages.append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.write(prompt)
            
            if OPENAI_API_KEY:
                try:
                    client = openai.OpenAI(api_key=OPENAI_API_KEY)
                    sys_msg = f"""
                    당신은 SK그룹 리더십 코치입니다. 진단 데이터: {data}
                    GROW 모델로 코칭하고, 인식 차이와 보완점을 해결하는 질문을 던지세요.
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
