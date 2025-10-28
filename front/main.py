import os
import json
import requests
import streamlit as st
import streamlit.components.v1 as components
from datetime import datetime

# ─────────────────────────────────────────────────────────────
# 기본 설정
# ─────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Insurance AI",
    layout="wide",
    initial_sidebar_state="collapsed",
    page_icon="🛡️"
)

API_BASE = st.secrets.get("API_BASE") or os.getenv("API_BASE") or "http://localhost:8000"

# 보험사별 브랜드 컬러
INSURERS = {
    "현대해상": {"color": "#00AAD2", "icon": "🏢"},
    "DB손해보험": {"color": "#E31E24", "icon": "🏦"},
    "삼성화재": {"color": "#1428A0", "icon": "🏛️"}
}

ss = st.session_state

# 세션 상태 초기화
if "messages_by_insurer" not in ss:
    ss["messages_by_insurer"] = {}
if "insurer" not in ss:
    ss["insurer"] = "현대해상"
if ss["insurer"] not in ss["messages_by_insurer"]:
    ss["messages_by_insurer"][ss["insurer"]] = []
if "top_k" not in ss:
    ss["top_k"] = 5
if "temperature" not in ss:
    ss["temperature"] = 0.30
if "max_tokens" not in ss:
    ss["max_tokens"] = 512
if "auto_pdf" not in ss:
    ss["auto_pdf"] = True
if "show_settings" not in ss:
    ss["show_settings"] = False
if "current_page" not in ss:
    ss["current_page"] = "Home"

def _msgs():
    return ss["messages_by_insurer"][ss["insurer"]]

# ─────────────────────────────────────────────────────────────
# 개선된 CSS 스타일
# ─────────────────────────────────────────────────────────────
def inject_css(css: str):
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)

inject_css("""
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@300;400;500;700;900&display=swap');

:root {
    --primary-blue: #1E88E5;
    --primary-dark: #1565C0;
    --primary-light: #42A5F5;
    --secondary-blue: #0D47A1;
    --accent-blue: #03A9F4;
    --bg-light: #E3F2FD;
    --bg-card: #FFFFFF;
    --text-primary: #0D47A1;
    --text-secondary: #1976D2;
    --border-light: #90CAF9;
    --shadow-sm: 0 2px 4px rgba(30, 136, 229, 0.1);
    --shadow-md: 0 4px 8px rgba(30, 136, 229, 0.15);
    --shadow-lg: 0 8px 16px rgba(30, 136, 229, 0.2);
}

/* Streamlit Deploy 버튼 숨기기 */
[data-testid="stToolbar"] {
    display: none !important;
}

/* 전체 배경 */
.stApp {
    background: linear-gradient(180deg, #E3F2FD 0%, #FFFFFF 100%);
}

/* 전체 레이아웃 */
.block-container {
    max-width: 1400px;
    padding: 0rem 2rem 3rem 2rem;
    font-family: 'Noto Sans KR', sans-serif;
}

/* 상단 네비게이션 바 스타일 */
.nav-title-button button {
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
    color: white !important;
    font-size: 1.5rem !important;
    font-weight: 900 !important;
    padding: 0.5rem 1rem !important;
}

.nav-title-button button:hover {
    background: rgba(255, 255, 255, 0.1) !important;
    transform: none !important;
}

/* 사이드바 제거 */
section[data-testid="stSidebar"] {
    display: none;
}

/* 히어로 헤더 개선 */
.hero-header {
    background: linear-gradient(135deg, #1E88E5 0%, #1565C0 100%);
    padding: 3rem 2rem;
    border-radius: 16px;
    margin-bottom: 2rem;
    box-shadow: var(--shadow-lg);
    position: relative;
    overflow: hidden;
}

.hero-header::before {
    content: '';
    position: absolute;
    top: -50%;
    right: -20%;
    width: 400px;
    height: 400px;
    background: rgba(255, 255, 255, 0.1);
    border-radius: 50%;
}

.hero-title {
    color: white;
    font-size: 2.5rem;
    font-weight: 900;
    margin: 0;
    letter-spacing: -0.5px;
    position: relative;
    z-index: 1;
    text-shadow: 0 2px 4px rgba(0,0,0,0.1);
}

.hero-subtitle {
    color: rgba(255, 255, 255, 0.95);
    font-size: 1.1rem;
    font-weight: 400;
    margin-top: 0.75rem;
    position: relative;
    z-index: 1;
}

/* 채팅 메시지 개선 */
div[data-testid="stChatMessage"] {
    border: none;
    border-radius: 16px;
    padding: 1.25rem 1.5rem;
    margin: 1rem 0;
    box-shadow: var(--shadow-sm);
    background: var(--bg-card);
    transition: all 0.2s ease;
}

div[data-testid="stChatMessage"]:hover {
    box-shadow: var(--shadow-md);
}

/* 참조 문서 카드 */
.reference-card {
    background: linear-gradient(135deg, #E3F2FD 0%, #BBDEFB 100%);
    border-left: 4px solid #1E88E5;
    border-radius: 12px;
    padding: 1rem 1.25rem;
    margin: 0.75rem 0;
    box-shadow: var(--shadow-sm);
}

.reference-title {
    font-weight: 700;
    color: #0D47A1;
    margin-bottom: 0.5rem;
}

.reference-score {
    display: inline-block;
    background: #42A5F5;
    color: #FFFFFF;
    padding: 0.2rem 0.6rem;
    border-radius: 20px;
    font-size: 0.75rem;
    font-weight: 600;
    margin-left: 0.5rem;
}

.reference-snippet {
    color: #1565C0;
    font-size: 0.9rem;
    line-height: 1.6;
    margin-top: 0.5rem;
}

/* Expander 스타일링 */
.streamlit-expanderHeader {
    background: linear-gradient(135deg, #E3F2FD 0%, #BBDEFB 100%);
    border-radius: 12px;
    padding: 1rem 1.25rem;
    font-weight: 600;
    color: var(--text-primary);
    border: 1px solid #90CAF9;
}

.streamlit-expanderHeader:hover {
    background: linear-gradient(135deg, #BBDEFB 0%, #90CAF9 100%);
}

/* 버튼 스타일링 */
.stButton > button {
    background: linear-gradient(135deg, var(--primary-blue) 0%, var(--primary-dark) 100%);
    color: white;
    border: none;
    border-radius: 12px;
    padding: 0.75rem 2rem;
    font-weight: 600;
    font-size: 1rem;
    transition: all 0.3s ease;
    box-shadow: var(--shadow-sm);
}

.stButton > button:hover {
    transform: translateY(-2px);
    box-shadow: var(--shadow-md);
    background: linear-gradient(135deg, var(--primary-light) 0%, var(--primary-blue) 100%);
}

.stButton > button:active {
    transform: translateY(0px);
}

.stButton > button[kind="secondary"] {
    background: white;
    color: var(--primary-blue);
    border: 2px solid var(--primary-blue);
}

.stButton > button[kind="secondary"]:hover {
    background: var(--bg-light);
}

/* 입력 필드 개선 */
.stTextInput > div > div > input,
.stTextArea > div > div > textarea {
    border-radius: 12px;
    border: 2px solid var(--border-light);
    padding: 0.75rem 1rem;
    transition: all 0.3s ease;
}

.stTextInput > div > div > input:focus,
.stTextArea > div > div > textarea:focus {
    border-color: var(--primary-blue);
    box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.1);
}

/* 탭 스타일링 */
.stTabs [data-baseweb="tab-list"] {
    gap: 1rem;
    background: transparent;
    border-bottom: 2px solid var(--border-light);
}

.stTabs [data-baseweb="tab"] {
    height: 3.5rem;
    padding: 0 2rem;
    background: transparent;
    border-radius: 12px 12px 0 0;
    font-weight: 600;
    font-size: 1rem;
}

.stTabs [aria-selected="true"] {
    background: white;
    border-bottom: 3px solid var(--primary-blue);
}

/* 통계 카드 */
.stat-card {
    background: white;
    border-radius: 16px;
    padding: 1.5rem;
    box-shadow: var(--shadow-sm);
    border: 1px solid var(--border-light);
    text-align: center;
}

.stat-value {
    font-size: 2rem;
    font-weight: 900;
    color: var(--primary-blue);
    margin-bottom: 0.25rem;
}

.stat-label {
    font-size: 0.875rem;
    color: var(--text-secondary);
    font-weight: 500;
}

/* 알림 메시지 개선 */
.stAlert {
    border-radius: 12px;
    border: none;
    padding: 1rem 1.25rem;
    box-shadow: var(--shadow-sm);
}

div[data-testid="stNotificationContentInfo"] {
    background: linear-gradient(135deg, #E3F2FD 0%, #BBDEFB 100%);
    border-left: 4px solid var(--primary-blue);
}

div[data-testid="stNotificationContentSuccess"] {
    background: linear-gradient(135deg, #E8F5E9 0%, #C8E6C9 100%);
    border-left: 4px solid #4CAF50;
}

/* 뱃지 스타일 */
.badge {
    display: inline-block;
    padding: 0.25rem 0.75rem;
    border-radius: 20px;
    font-size: 0.75rem;
    font-weight: 600;
    background: #E3F2FD;
    color: var(--primary-blue);
}

.badge.success {
    background: #81C784;
    color: #FFFFFF;
}

.badge.warning {
    background: #FFB74D;
    color: #FFFFFF;
}

.badge.error {
    background: #E57373;
    color: #FFFFFF;
}

/* 보험사 선택 카드 */
.insurer-card {
    background: white;
    border: 2px solid var(--border-light);
    border-radius: 12px;
    padding: 1.5rem;
    margin: 1rem 0;
    cursor: pointer;
    transition: all 0.3s ease;
    box-shadow: var(--shadow-sm);
}

.insurer-card:hover {
    border-color: var(--primary-blue);
    box-shadow: var(--shadow-md);
    transform: translateY(-2px);
}

.insurer-card.selected {
    background: linear-gradient(135deg, #E3F2FD 0%, #BBDEFB 100%);
    border-color: var(--primary-blue);
    box-shadow: var(--shadow-md);
}

/* 홈 화면 카드 */
.home-feature-card {
    background: white;
    border-radius: 16px;
    padding: 2rem;
    box-shadow: var(--shadow-md);
    border: 2px solid var(--border-light);
    transition: all 0.3s ease;
    height: 100%;
}

.home-feature-card:hover {
    border-color: var(--primary-blue);
    transform: translateY(-4px);
    box-shadow: var(--shadow-lg);
}

.home-feature-icon {
    font-size: 3rem;
    margin-bottom: 1rem;
}

.home-feature-title {
    color: var(--text-primary);
    font-size: 1.5rem;
    font-weight: 700;
    margin-bottom: 0.75rem;
}

.home-feature-desc {
    color: var(--text-secondary);
    font-size: 1rem;
    line-height: 1.6;
}
""")

def _post(url, payload, timeout=(20, 180)):
    try:
        r = requests.post(url, json=payload, timeout=timeout)
        r.raise_for_status()
        return r, None
    except requests.RequestException as e:
        return None, str(e)

def _get(url, timeout=(10, 30)):
    try:
        r = requests.get(url, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None

def _normalize_references(resp_json: dict):
    refs = []
    if isinstance(resp_json.get("references"), list):
        for it in resp_json["references"]:
            fname = it.get("file_name") or it.get("doc_id") or it.get("title") or "문서"
            page = it.get("page") or it.get("page_no")
            score = it.get("score")
            snippet = it.get("content") or it.get("text") or it.get("snippet") or ""
            title = f"{fname} (p.{page})" if page else fname
            refs.append({"title": title, "snippet": snippet.strip(), "score": score})
        return refs

    ctx_text = resp_json.get("context") or ""
    if not ctx_text:
        return []
    blocks = [b for b in ctx_text.split("\n\n---\n\n") if b.strip()]
    for i, b in enumerate(blocks, 1):
        lines = b.splitlines()
        title = (lines[0] if lines else f"근거 {i}")[:160]
        snippet = b
        refs.append({"title": title, "snippet": snippet, "score": None})
    return refs

def render_answer_card(answer: str, sources: list[dict] | None = None):
    with st.chat_message("assistant"):
        st.markdown(answer)
        if sources:
            expander_title = f"🔍 **참조 문서 {len(sources)}개** - 클릭하여 자세히 보기"
            with st.expander(expander_title, expanded=True):
                for i, item in enumerate(sources, 1):
                    title = item.get("title") or "제목 없음"
                    score = item.get("score")
                    snippet = (item.get("snippet") or "").strip()
                    if len(snippet) > 600:
                        snippet = snippet[:600] + "…"
                    
                    score_badge = ""
                    if isinstance(score, (int, float)):
                        score_pct = int(score * 100)
                        score_badge = f'<span class="reference-score">{score_pct}% 관련</span>'
                    
                    ref_html = f"""
                    <div class="reference-card">
                        <div class="reference-title">📄 {i}. {title}{score_badge}</div>
                        <div class="reference-snippet">{snippet}</div>
                    </div>
                    """
                    st.markdown(ref_html, unsafe_allow_html=True)

def _download_pdf_via_browser(endpoint: str, payload: dict, filename: str = "report.pdf"):
    url = f"{API_BASE.rstrip('/')}{endpoint}"
    enriched = dict(payload)
    enriched["return_mode"] = "stream"

    components.html(
        f"""
        <script>
          (async () => {{
            const url = {json.dumps(url)};
            const body = {json.dumps(enriched, ensure_ascii=False)};
            try {{
              const res = await fetch(url, {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                credentials: 'include',
                body: JSON.stringify(body)
              }});
              const ctype = (res.headers.get('content-type') || '').toLowerCase();

              if (res.ok && ctype.includes('application/pdf')) {{
                const blob = await res.blob();
                const a = document.createElement('a');
                a.href = URL.createObjectURL(blob);
                a.download = {json.dumps(filename)};
                document.body.appendChild(a);
                a.click();
                setTimeout(() => {{ URL.revokeObjectURL(a.href); a.remove(); }}, 1500);
                return;
              }}

              const data = await res.json().catch(() => ({{}}));
              const abs = data.absolute_url;
              const rel = data.file_url || data.url;
              const dlUrl = abs || rel;
              if (!dlUrl) throw new Error(data.error || 'no download url');

              const res2 = await fetch(dlUrl, {{ credentials: 'include' }});
              if (!res2.ok) throw new Error('HTTP ' + res2.status + ' on file url');
              const blob2 = await res2.blob();
              const a2 = document.createElement('a');
              a2.href = URL.createObjectURL(blob2);
              a2.download = (data.filename || {json.dumps(filename)});
              document.body.appendChild(a2);
              a2.click();
              setTimeout(() => {{ URL.revokeObjectURL(a2.href); a2.remove(); }}, 1500);
            }} catch (err) {{
              const el = document.createElement('div');
              el.style.color = 'red';
              el.style.fontSize = '12px';
              el.innerText = 'PDF 생성/다운로드 실패: ' + err;
              document.body.appendChild(el);
            }}
          }})();
        </script>
        """,
        height=0,
    )

# ─────────────────────────────────────────────────────────────
# 상단 네비게이션 바
# ─────────────────────────────────────────────────────────────
nav_col1, nav_col2 = st.columns([2, 3])

with nav_col1:
    st.markdown('<div class="nav-title-button">', unsafe_allow_html=True)
    if st.button("🛡️ Insurance AI", key="nav_home", use_container_width=True):
        ss["current_page"] = "Home"
        st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)

with nav_col2:
    menu_cols = st.columns(4)

    with menu_cols[0]:
        if st.button("🏠 Home", key="menu_home", type="primary" if ss.current_page == "Home" else "secondary", use_container_width=True):
            ss["current_page"] = "Home"
            st.rerun()

    with menu_cols[1]:
        if st.button("💬 Q&A 상담", key="menu_qa", type="primary" if ss.current_page == "Q&A" else "secondary", use_container_width=True):
            ss["current_page"] = "Q&A"
            st.rerun()

    with menu_cols[2]:
        if st.button("📄 PDF 리포트", key="menu_pdf", type="primary" if ss.current_page == "PDF" else "secondary", use_container_width=True):
            ss["current_page"] = "PDF"
            st.rerun()

    with menu_cols[3]:
        if st.button("⚙️ 설정", key="menu_settings", type="primary" if ss.current_page == "Settings" else "secondary", use_container_width=True):
            ss["current_page"] = "Settings"
            st.rerun()

st.divider()

# ─────────────────────────────────────────────────────────────
# 페이지 렌더링
# ─────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────
# Home 페이지
# ─────────────────────────────────────────────────────────────
if ss.current_page == "Home":
    hero_html = f"""
    <div class="hero-header">
        <h1 class="hero-title">🛡️ Insurance AI</h1>
        <p class="hero-subtitle">AI 기반 보험 문서 검색 및 상담 시스템</p>
    </div>
    """
    st.markdown(hero_html, unsafe_allow_html=True)

    st.markdown("### 💼 보험사 선택")
    st.info("💡 보험사를 선택하면 바로 Q&A 상담을 시작할 수 있습니다.")
    ins_cols = st.columns(3)

    for idx, (name, info) in enumerate(INSURERS.items()):
        with ins_cols[idx]:
            is_selected = (ss.insurer == name)
            card_class = "insurer-card selected" if is_selected else "insurer-card"

            if st.button(
                f"{info['icon']} {name}",
                key=f"home_btn_{name}",
                use_container_width=True,
                type="primary" if is_selected else "secondary"
            ):
                ss.insurer = name
                if name not in ss["messages_by_insurer"]:
                    ss["messages_by_insurer"][name] = []
                # 보험사 선택 후 바로 Q&A 페이지로 이동
                ss["current_page"] = "Q&A"
                st.rerun()

    st.divider()

    st.markdown("### ✨ 주요 기능")

    feature_cols = st.columns(3)

    with feature_cols[0]:
        st.markdown("""
        <div class="home-feature-card">
            <div class="home-feature-icon">💬</div>
            <div class="home-feature-title">Q&A 상담</div>
            <div class="home-feature-desc">보험 관련 질문에 대해 AI가 관련 문서를 검색하여 정확한 답변을 제공합니다.</div>
        </div>
        """, unsafe_allow_html=True)

    with feature_cols[1]:
        st.markdown("""
        <div class="home-feature-card">
            <div class="home-feature-icon">📄</div>
            <div class="home-feature-title">PDF 리포트</div>
            <div class="home-feature-desc">상세한 보험 청구 리포트를 PDF 형식으로 생성하고 다운로드할 수 있습니다.</div>
        </div>
        """, unsafe_allow_html=True)

    with feature_cols[2]:
        st.markdown("""
        <div class="home-feature-card">
            <div class="home-feature-icon">🔍</div>
            <div class="home-feature-title">문서 검색</div>
            <div class="home-feature-desc">보험사별 문서를 신속하게 검색하고 필요한 정보를 찾을 수 있습니다.</div>
        </div>
        """, unsafe_allow_html=True)

    st.divider()

    st.markdown("### 📊 시스템 상태")

    status_cols = st.columns(4)

    hc = _get(f"{API_BASE.rstrip('/')}/health/")
    if isinstance(hc, dict):
        llm_ok = hc.get("llm_ok", True)
        db_ok = hc.get("db_ok", True)

        with status_cols[0]:
            llm_badge = "success" if llm_ok else "error"
            llm_text = "정상" if llm_ok else "오류"
            st.markdown(f'<div class="stat-card"><div class="stat-value"><span class="badge {llm_badge}">{"✓" if llm_ok else "✗"}</span></div><div class="stat-label">🤖 LLM: {llm_text}</div></div>', unsafe_allow_html=True)

        with status_cols[1]:
            db_badge = "success" if db_ok else "error"
            db_text = "정상" if db_ok else "오류"
            st.markdown(f'<div class="stat-card"><div class="stat-value"><span class="badge {db_badge}">{"✓" if db_ok else "✗"}</span></div><div class="stat-label">💾 DB: {db_text}</div></div>', unsafe_allow_html=True)

        with status_cols[2]:
            msg_count = len(_msgs())
            st.markdown(f'<div class="stat-card"><div class="stat-value">{msg_count}</div><div class="stat-label">💬 메시지 수</div></div>', unsafe_allow_html=True)

        with status_cols[3]:
            st.markdown(f'<div class="stat-card"><div class="stat-value">{ss.insurer[:2]}</div><div class="stat-label">🏢 선택 보험사</div></div>', unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────
# Settings 페이지
# ─────────────────────────────────────────────────────────────
elif ss.current_page == "Settings":
    st.markdown("## ⚙️ 설정")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("### 🔍 검색 설정")
        st.slider("📊 Top-K (근거 개수)", 1, 10, key="top_k")
        st.slider("🌡️ Temperature", 0.0, 1.0, key="temperature", step=0.1)
        st.slider("📝 Max Tokens", 128, 2048, key="max_tokens", step=128)

    with col2:
        st.markdown("### 📄 문서 설정")
        st.toggle("📄 답변 후 자동 PDF 저장", key="auto_pdf")

        st.markdown("### 💬 대화 관리")
        msg_count = len(_msgs())
        st.info(f"현재 대화 메시지 수: {msg_count}개")

        if st.button("🗑️ 대화 기록 삭제", use_container_width=True):
            ss["messages_by_insurer"][ss["insurer"]] = []
            st.success("대화 기록이 삭제되었습니다.")
            st.rerun()

# ─────────────────────────────────────────────────────────────
# Q&A 상담 페이지
# ─────────────────────────────────────────────────────────────
elif ss.current_page == "Q&A":
    insurer_info = INSURERS[ss.insurer]
    hero_html = f"""
    <div class="hero-header">
        <h1 class="hero-title">{insurer_info['icon']} {ss.insurer} 보험 상담</h1>
        <p class="hero-subtitle">AI 기반 보험 문서 검색 및 상담 시스템</p>
    </div>
    """
    st.markdown(hero_html, unsafe_allow_html=True)
    
    if len(_msgs()) == 0:
        st.info("💡 질문을 입력하여 보험 상담을 시작하세요. AI가 관련 문서를 검색하여 답변해드립니다.")
        
        st.markdown("#### 💭 예시 질문")
        example_cols = st.columns(2)
        examples = [
            "골절 치료비는 보험 청구가 가능한가요?",
            "입원 시 필요한 서류는 무엇인가요?",
            "교통사고 보험 처리 절차를 알려주세요",
            "암 진단 시 보장 범위는 어떻게 되나요?"
        ]
        for idx, example in enumerate(examples):
            with example_cols[idx % 2]:
                if st.button(f"📌 {example}", key=f"ex_{idx}", use_container_width=True):
                    ss["example_query"] = example
    
    for m in _msgs():
        with st.chat_message(m["role"]):
            st.markdown(m["content"])

    insurer_selected = bool(ss.insurer)
    default_query = ss.pop("example_query", "")
    user_text = st.chat_input(
        f"💬 {ss.insurer}에 대해 질문하세요...",
        disabled=not insurer_selected,
    ) or default_query

    if user_text:
        log = _msgs()
        log.append({"role": "user", "content": user_text})
        
        with st.chat_message("user"):
            st.markdown(user_text)

        with st.spinner("🔍 관련 문서를 검색하고 답변을 생성하고 있습니다..."):
            payload_ask = {
                "query": user_text,
                "policy_type": ss.insurer,
                "top_k": int(ss.top_k),
                "max_tokens": int(ss.max_tokens),
                "temperature": float(ss.temperature),
            }

            r, err = _post(f"{API_BASE.rstrip('/')}/qa/ask", payload_ask, timeout=(20, 180))
            if err or r is None:
                error_msg = f"❌ 요청 실패: {err or 'no response'}"
                log.append({"role": "assistant", "content": error_msg})
                st.error(error_msg)
                st.rerun()

            data = r.json()
            answer = data.get("answer") or "⚠️ 빈 응답입니다."
            refs = _normalize_references(data)

            render_answer_card(answer, refs)
            log.append({"role": "assistant", "content": answer})

            if ss.auto_pdf:
                detect_metas = [s["title"] for s in refs][: ss.top_k] if refs else []
                pdf_payload = {
                    "question": user_text,
                    "policy_type": ss.insurer,
                    "top_k": int(ss.top_k),
                    "max_tokens": int(ss.max_tokens),
                    "temperature": float(ss.temperature),
                    "detect_metas": detect_metas,
                }
                _download_pdf_via_browser("/qa/answer_pdf", pdf_payload, filename="insurance_report.pdf")
                st.success("✅ PDF 리포트가 자동으로 다운로드되었습니다.")

# ─────────────────────────────────────────────────────────────
# PDF 리포트 페이지
# ─────────────────────────────────────────────────────────────
elif ss.current_page == "PDF":
    insurer_info = INSURERS[ss.insurer]
    hero_html = f"""
    <div class="hero-header">
        <h1 class="hero-title">📄 {ss.insurer} PDF 리포트 생성</h1>
        <p class="hero-subtitle">상세한 보험 청구 리포트를 PDF 형식으로 생성하세요</p>
    </div>
    """
    st.markdown(hero_html, unsafe_allow_html=True)
    st.markdown("### 📋 상세 리포트 생성")
    st.info("💡 아래 폼을 작성하여 상세한 보험 청구 리포트 PDF를 생성할 수 있습니다.")

    with st.form("pdf_form"):
        col1, col2 = st.columns([2, 1])
        
        with col1:
            title = st.text_input("📌 제목", value="보험 청구 상담 결과", placeholder="리포트 제목을 입력하세요")
            summary = st.text_area("📝 사건 요약", placeholder="사고/발병 경위, 증상, 치료 정보 등을 입력하세요", height=150)
        
        with col2:
            likelihood = st.text_input("📊 청구 가능성", placeholder="예: 높음, 중간, 낮음")
            qr_url = st.text_input("🔗 QR 코드 URL (선택)", placeholder="https://example.com")

        col3, col4 = st.columns(2)
        
        with col3:
            required_docs = st.text_area(
                "📋 필요 서류", 
                value="진단서\n진료비 영수증\n입퇴원확인서",
                height=120
            )
        
        with col4:
            timeline = st.text_area(
                "📅 타임라인",
                placeholder="2025-01-02 최초 내원\n2025-01-05 입원\n2025-01-10 퇴원",
                height=120
            )

        meta = st.text_input("ℹ️ 메타 정보 (선택)", value=f"모델: gpt-4o-mini / Top-K: {ss.top_k}")
        appendix = st.text_area("📎 부록 (선택)", placeholder="추가 정보를 입력하세요", height=100)

        submitted = st.form_submit_button("📄 PDF 생성 및 다운로드", use_container_width=True)
        
        if submitted:
            parts = []
            if title:
                parts.append(f"[제목] {title}")
            if summary:
                parts.append(f"[사건요약] {summary}")
            if likelihood:
                parts.append(f"[청구가능성] {likelihood}")
            if timeline:
                steps = ", ".join([s.strip() for s in timeline.splitlines() if s.strip()])
                parts.append(f"[타임라인] {steps}")
            if required_docs:
                docs = ", ".join([d.strip() for d in required_docs.splitlines() if d.strip()])
                parts.append(f"[필요서류] {docs}")
            if meta:
                parts.append(f"[메타] {meta}")
            if appendix:
                parts.append(f"[부록] {appendix}")
            if qr_url:
                parts.append(f"[QR] {qr_url}")
            
            question_text = "\n".join(parts)
            
            if not question_text.strip():
                st.error("폼에 최소 한 개 항목 이상 입력하세요.")
            else:
                pdf_payload = {
                    "question": question_text,
                    "policy_type": ss.insurer,
                    "top_k": int(ss.top_k),
                    "max_tokens": int(ss.max_tokens),
                    "temperature": float(ss.temperature),
                }
                _download_pdf_via_browser("/qa/answer_pdf", pdf_payload, filename="answer.pdf")
                st.success("✅ PDF 생성 요청이 완료되었습니다. 잠시 후 다운로드가 시작됩니다.")
