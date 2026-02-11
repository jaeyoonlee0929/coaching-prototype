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

# --- 1. 리더십 진단 파싱 로직 (거리 제한 방식) ---
def parse_leadership_report(text):
    data = {
        "summary": 0.0,
        "details": [],
        "comments": {"boss": [], "members": []}
    }
    
    # 공백 제거 (검색 정확도 향상)
    clean_text = re.sub(r'\s+', '', text)
    
    # [항목 매핑] PDF 내 실제 텍스트(공백제거) : 화면 표시 이름
    # 보내주신 캡처본 기준 정확한 명칭
    items_map = [
        ("SKMS에대한확신", "SKMS 확신"),
        ("패기/솔선수범", "패기/솔선수범"),
        ("Integrity", "Integrity"),
        ("경영환경이해", "경영환경 이해"),
        ("팀목표방향수립", "팀 목표 수립"),      # 수정됨
        ("변화주도", "변화 주도"),
        ("도전적목표설정", "도전적 목표"),      # 수정됨
        ("팀워크발휘", "팀워크 발휘"),
        ("과감하고빠른실행", "과감한 실행"),    # 수정됨
        ("자율적업무환경조성", "자율환경 조성"),
        ("소통", "소통"),
        ("구성원육성", "구성원 육성")
    ]

    scores = []
    
    for pdf_key, label in items_map:
        # 정규표현식 설명:
        # 1. pdf_key (항목명) 찾음
        # 2. .{0,150}? : 그 뒤에 오는 문자열이 0~150자 이내 (너무 멀리 있는 숫자는 무시)
        # 3. ([0-5]\.\d) : 0.0 ~ 5.9 사이의 소수점 숫자 (본인 점수)
        # 4. .{0,50}? : 그 뒤 50자 이내
        # 5. ([0-5]\.\d) : 그룹 점수
        pattern = re.compile(rf"{re.escape(pdf_key)}.{0,150}?([0-5]\.\d).{0,50}?([0-5]\.\d)", re.DOTALL)
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
                # 숫자가 아닌 경우 0 처리
                data["details"].append({"category": label, "self": 0.0, "group": 0.0})
        else:
            # 매칭 실패 시 0 처리 (순서 유지)
            data["details"].append({"category": label, "self": 0.0, "group": 0.0})
            
    # 종합 점수 (평균)
    if scores:
        data["summary"] = round(sum(scores) / len(scores), 1)
    
    # --- 주관식 코멘트 추출 ---
    # 상사 응답
    if "상사 응답" in text:
        try:
            # "상사 응답" 키워드 위치 찾기 (본문)
            matches = [m.start() for m in re.finditer("상사 응답", text)]
            if matches:
                start = matches[-1] # 보통 마지막이 본문
                end = text.find("구성원 응답", start)
                if end == -1: end = len(text)
                
                block = text[start:end]
                lines = re.findall(r"[·-]\s*(.*)", block)
                data["comments"]["boss"] = [l.strip() for l in lines if len(l.strip()) > 5]
        except: pass

    # 구성원 응답
    if "구성원 응답" in text:
        try:
            matches = [m.start() for m in re.finditer("구성원 응답", text)]
            if matches:
                # 주관식 섹션은 파일 뒷부분에 위치
                start = matches[-1]
                end = text.find("Review Questions", start)
                if end == -1: end = len(text)
                
                block = text[start:end]
                lines = re.findall(r"[·-]\s*(.*)", block)
                
                clean_lines = []
                for l in lines:
                    l = l.strip()
                    # 노이즈 필터링
                    if len(l) > 2 and "SK" not in l and not l.endswith("?") and "PAGE" not in l:
                        clean_lines.append(l)
                
                # 상사 응답과 중복 제거
                boss_set = set(data["comments"]["boss"])
                data["comments"]["members"] = [c for c in clean_lines if c not in boss_set]
        except: pass

    return data

# --- 2. OEI 진단 파싱 로직 (Snapshot 기반) ---
def parse_oei_report(text):
    data = {
        "summary": 0.0,
        "stages": [],
        "gaps": [],
        "comments": {"strength": [], "weakness": []}
    }
    
    clean_text = re.sub(r'\s+', '', text)
    
    # 1. 종합 점수 추출
    # 패턴: 【조직 효과성 점수 4.6점】
    match_total = re.search(r"조직효과성점수([0-5]\.\d)", clean_text)
    if match_total:
        data["summary"] = float(match_total.group(1))
    
    # 2. I-P-O 단계별 점수 추출
    # "Snapshot" 섹션 근처에서 찾기
    if "Snapshot" in clean_text:
        # Snapshot 이후 텍스트
        snapshot_section = clean_text.split("Snapshot")[-1]
        
        # Input...숫자...Process...숫자...Output...숫자 패턴 찾기
        # 중간에 텍스트가 섞여있어도 순서는 항상 Input -> Process -> Output
        ipo_pattern = re.search(r"Input.*?([0-5]\.\d).*?Process.*?([0-5]\.\d).*?Output.*?([0-5]\.\d)", snapshot_section)
        
        if ipo_pattern:
            data["stages"] = [
                {"stage": "Input", "score": float(ipo_pattern.group(1))},
                {"stage": "Process", "score": float(ipo_pattern.group(2))},
                {"stage": "Output", "score": float(ipo_pattern.group(3))}
            ]
        else:
            # 패턴 매칭 실패 시 개별 검색 (Fallback)
            m_in = re.search(r"Input.*?([0-5]\.\d)", snapshot_section)
            m_pr = re.search(r"Process.*?([0-5]\.\d)", snapshot_section)
            m_ou = re.search(r"Output.*?([0-5]\.\d)", snapshot_section)
            
            if m_in and m_pr and m_ou:
                data["stages"] = [
                    {"stage": "Input", "score": float(m_in.group(1))},
                    {"stage": "Process", "score": float(m_pr.group(1))},
                    {"stage": "Output", "score": float(m_ou.group(1))}
                ]

    # 3. Gap 분석 (상세 항목)
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
        # 거리 제한을 둔 정규표현식 사용
        pattern = re.compile(rf"{re.escape(item)}.{0,100}?([0-5]\.\d).{0,50}?([0-5]\.\d)", re.DOTALL)
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
        p1 = text.split(q_strength)[-1]
        p2 = p1.split(q_weakness)[0] if q_weakness in p1 else p1
        lines = re.findall(r"[·-]\s*(.*)", p2)
        data["comments"]["strength"] = [l.strip() for l in lines if len(l) > 2 and not l.strip().endswith('?')][:5]

    if q_weakness in text:
        p1 = text.split(q_weakness)[-1]
        p2 = p1.split("장애요인")[0] if "장애요인" in p1 else p1
        lines = re.findall(r"[·-]\s*(.*)", p2)
        data["comments"]["weakness"] = [l.strip() for l in lines if len(l) > 2 and not l.strip().endswith('?')][:5]

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
    
    # [디버깅용] 파일 내용 확인 (필요시 주석 해제)
    # if leadership_file:
    #     st.text_area("Debug: Leadership Raw Text", extract_text_from_pdf(leadership_file)[:500])

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
                welcome += f"\n\n분석 결과, **'{issue}'** 항목에서 본인과 구성원의 인식 차이가 큽니다. 이에 대해 이야기를 나눠볼까요?"
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
        c1.metric("리더십 종합 점수 (Self)", f"{data['leadership']['summary']} / 5.0")
        c2.metric("조직효과성 종합 점수", f"{data['oei']['summary']} / 5.0")
        
        c3, c4 = st.columns(2)
        with c3:
            st.markdown("##### 리더십 역량 (Radar)")
            df_l = pd.DataFrame(data['leadership']['details'])
            if not df_l.empty:
                # 0점 제외하고 그리기
                df_l_valid = df_l[df_l['self'] > 0]
                if not df_l_valid.empty:
                    fig = go.Figure()
                    fig.add_trace(go.Scatterpolar(r=df_l_valid['self'], theta=df_l_valid['category'], fill='toself', name='본인'))
                    fig.add_trace(go.Scatterpolar(r=df_l_valid['group'], theta=df_l_valid['category'], fill='toself', name='구성원'))
                    fig.update_layout(polar=dict(radialaxis=dict(visible=True, range=[0, 5])), margin=dict(t=30, b=30), height=350)
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.warning("유효한 리더십 상세 데이터를 찾지 못했습니다. 리포트 형식을 확인해주세요.")
            else:
                st.warning("리더십 상세 데이터를 찾지 못했습니다.")
        
        with c4:
            st.markdown("##### 조직 효과성 흐름 (I-P-O)")
            df_o = pd.DataFrame(data['oei']['stages'])
            if not df_o.empty:
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
            df_l_valid = df_l[df_l['self'] > 0]
            if not df_l_valid.empty:
                fig3 = go.Figure()
                fig3.add_trace(go.Bar(x=df_l_valid['category'], y=df_l_valid['self'], name='본인'))
                fig3.add_trace(go.Bar(x=df_l_valid['category'], y=df_l_valid['group'], name='구성원'))
                fig3.update_layout(barmode='group', height=400)
                st.plotly_chart(fig3, use_container_width=True)
            else:
                st.info("데이터 추출 실패")
        
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
