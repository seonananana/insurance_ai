# front/main.py
import os
import requests
import streamlit as st

st.set_page_config(page_title="보험 문서 RAG", page_icon="🧾", layout="wide")

# ---------------------------
# 환경
# ---------------------------
API_BASE = st.secrets.get("API_BASE") or os.getenv("API_BASE") or "http://localhost:8000"
INSURERS = ["DB손해", "현대해상", "삼성화재"]
DEFAULT_TEMP = 0.3
DEFAULT_MAXTOK = 512

# ---------------------------
# CSS
# ---------------------------
def inject_css(css: str):
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)

inject_css("""
/* 기본 폰트 */
html, body, [class*="stApp"] { font-family: 'Noto Sans KR', system-ui, -apple-system, sans-serif; }
h1, h2, h3 { letter-spacing: -0.3px; }

/* 페이지 컨테이너(헤더/구분선/입력창 기준) */
div.block-container { max-width: 1000px; padding-top: 18px; }

/* 사이드바 */
section[data-testid="stSidebar"] { width: 320px !important; }
section[data-testid="stSidebar"] [data-testid="stSidebarContent"] { padding-top: 12px; }

/* ====== 행 전체폭 강제 래퍼 ====== */
.full-row, .full-row > div, .full-row [data-testid="stMarkdownContainer"]{
  width:100% !important; max-width:100% !important;
}
.full-row .element-container{ margin:0 !important; padding:0 !important; width:100% !important; }

/* 헤더 카드: 파란 배경 + 흰 글자 + 전체폭 */
.page-hero{
  display:block; width:100% !important; box-sizing:border-box;
  background:#2563EB; color:#fff;
  padding:22px 24px; border-radius:16px;
  font-weight:800; font-size:34px; letter-spacing:-0.3px;
  margin-bottom:12px;
}

/* 헤더 아래 구분선(전체폭) */
hr.page-divider{ border:none; height:1px; background:#E5E7EB; margin:18px 0 12px; width:100%; }

/* 채팅 버블 */
div[data-testid="stChatMessage"]{
  border:1px solid #eee; border-radius:16px; padding:10px 14px; margin:8px 0;
  box-shadow:0 2px 10px rgba(0,0,0,0.04); background:#fff;
}
div[data-testid="stChatMessage"] pre { background:#f7f8fb; }

/* ====== 입력창 폭 정렬 + 왼쪽 아이콘 제거 후, 오른쪽으로 이동 ====== */
div[data-testid="stChatInput"]{
  position: sticky; bottom: 0; z-index: 5;
  background: rgba(255,255,255,0.92);
  backdrop-filter: saturate(1.8) blur(6px);
  border-top: 1px solid #eee;
  width:100% !important;
  margin-left:0 !important; margin-right:0 !important;
  padding-left:0 !important; padding-right:0 !important;
}

/* 내부 래퍼 최대폭 해제 */
div[data-testid="stChatInput"] form,
div[data-testid="stChatInput"] > div,
div[data-testid="stChatInput"] > div > div{
  width:100% !important; max-width:100% !important;
}

/* 폼을 기준으로 커스텀 아이콘 배치 */
div[data-testid="stChatInput"] form{ position:relative; }

/* (1) 왼쪽 기본 이모지/아이콘 전부 숨김 — 전송버튼 아이콘은 그대로 둠 */
div[data-testid="stChatInput"] form > svg,
div[data-testid="stChatInput"] form [role="img"]{
  opacity:0 !important; width:0 !important; height:0 !important;
  margin:0 !important; pointer-events:none !important;
}

/* (2) 오른쪽(전송 버튼 왼쪽)에 커스텀 이모지 표시 */
div[data-testid="stChatInput"] form::after{
  content: "💬";                    /* ← 원하는 이모지로 바꿔도 됨 */
  position:absolute;
  right: 52px;                      /* 전송버튼과 간격 */
  top: 50%;
  transform: translateY(-50%);
  font-size: 16px;
  opacity: .85;
}

/* (3) 이모지 들어갈 공간만큼 우측 패딩 확보 */
div[data-testid="stChatInput"] textarea,
div[data-testid="stChatInput"] input[type="text"]{
  padding-right: 72px !important;   /* 버튼+이모지 여유 */
  padding-left: 12px !important;
}

/* 둥근 버튼 */
button, .stDownloadButton, .stLinkButton { border-radius: 10px !important; }

/* 캡션 톤 */
small, .stCaption { color:#6b7280 !important; }
""")

# ---------------------------
# 상태
# ---------------------------
def ensure_state():
    ss = st.session_state
    if "messages_by_insurer" not in ss:
        ss["messages_by_insurer"] = {}
        if ss.get("messages"):
            owner = ss.get("insurer") or "기본"
            ss["messages_by_insurer"][owner] = ss["messages"]
        ss["messages"] = []
    ss.setdefault("insurer", None)
    ss.setdefault("top_k", 3)
    ss.setdefault("temperature", DEFAULT_TEMP)
    ss.setdefault("max_tokens", DEFAULT_MAXTOK)

ensure_state()

def _cur_messages():
    company = st.session_state.insurer
    if company not in st.session_state.messages_by_insurer:
        st.session_state.messages_by_insurer[company] = []
    return st.session_state.messages_by_insurer[company]

# ---------------------------
# HTTP
# ---------------------------
def post_json(url: str, payload: dict, timeout=(20, 180)):
    try:
        r = requests.post(url, json=payload, timeout=timeout)
    except requests.RequestException as e:
        return None, str(e)
    try:
        r.raise_for_status()
        return r, None
    except requests.RequestException as e:
        return None, str(e)

# ---------------------------
# 사이드바 (설정 + 액션)
# ---------------------------
with st.sidebar:
    st.subheader("⚙️ 설정")
    options = ["선택하세요…"] + INSURERS
    default_idx = options.index(st.session_state.insurer) if st.session_state.insurer in options else 0
    st.selectbox("보험사", options, index=default_idx, key="insurer",
                 help="검색에 사용할 문서를 어느 보험사 것으로 제한할지 선택합니다.")
    st.session_state.top_k = st.slider("Top-K (근거 개수)", 1, 10, st.session_state.get("top_k", 3))
    st.session_state.temperature = st.slider("온도(창의성)", 0.0, 1.0, float(st.session_state.get("temperature", DEFAULT_TEMP)), 0.05)
    st.session_state.max_tokens = st.slider("최대 토큰", 128, 2048, int(st.session_state.get("max_tokens", DEFAULT_MAXTOK)), 64)

    st.markdown("---")
    col_a, col_b = st.columns(2)
    with col_a:  make_pdf_clicked = st.button("📄 PDF 생성", use_container_width=True)
    with col_b:  clear_clicked = st.button("🗑️ 대화 지우기", use_container_width=True)

    st.markdown("---")
    st.caption(f"API_BASE: {API_BASE}")

# ---------------------------
# 헤더(파란 박스) + 구분선: 전체폭 래퍼(.full-row)로 감쌈
# ---------------------------
st.markdown('<div class="full-row"><div class="page-hero">보험 문서 RAG 플랫폼</div></div>', unsafe_allow_html=True)
st.markdown('<div class="full-row"><hr class="page-divider"/></div>', unsafe_allow_html=True)

# ---------------------------
# 오버레이 & 게이트
# ---------------------------
def render_overlay():
    st.markdown("""
    <style>
    .overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.25);
               display: flex; align-items: center; justify-content: center; z-index: 9999; }
    .overlay-card { background: white; padding: 24px 28px; border-radius: 12px;
                    box-shadow: 0 10px 30px rgba(0,0,0,0.2); font-size: 18px; text-align: center; }
    </style>
    <div class="overlay"><div class="overlay-card">
        <b>보험사를 선택해 주세요.</b><br/>왼쪽 사이드바에서 보험사를 고르면 시작할 수 있어요.
    </div></div>""", unsafe_allow_html=True)

insurer_selected = st.session_state.insurer in INSURERS
if not insurer_selected:
    render_overlay()
    st.stop()

# ---------------------------
# 채팅 메시지 렌더(선택 보험사 전용)
# ---------------------------
for msg in _cur_messages():
    with st.chat_message("user" if msg["role"] == "user" else "assistant"):
        st.markdown(msg["content"])
        meta = msg.get("meta") or {}
        sources = meta.get("sources") or []
        if sources:
            with st.expander("🔎 근거 문서/소스", expanded=False):
                for i, h in enumerate(sources, 1):
                    title = h.get("clause_title") or h.get("doc_id") or f"source {i}"
                    score = h.get("score")
                    snippet = (h.get("content") or "").strip()
                    if len(snippet) > 320: snippet = snippet[:320] + "…"
                    st.markdown(f"**{i}. {title}** (score: {score})\n\n> {snippet}")
        pdf = meta.get("pdf")
        if isinstance(pdf, dict):
            pdf_url = pdf.get("url"); pdf_bytes = pdf.get("bytes")
            if pdf_url:
                href = pdf_url if not pdf_url.startswith("/") else f"{API_BASE}{pdf_url}"
                st.link_button("📄 PDF 열기", href)
            elif pdf_bytes:
                st.download_button("📄 PDF 다운로드", data=pdf_bytes, file_name="rag_answer.pdf", mime="application/pdf")

# ---------------------------
# 호출 함수(선택 보험사 스레드에만 기록)
# ---------------------------
def send_normal_chat(user_text: str):
    msgs = _cur_messages()
    msgs.append({"role": "user", "content": user_text})
    payload = {
        "messages": [{"role": "user", "content": user_text}],
        "insurer": st.session_state.insurer,
        "top_k": int(st.session_state.top_k),
        "temperature": float(st.session_state.temperature),
        "max_tokens": int(st.session_state.max_tokens),
    }
    r, err = post_json(f"{API_BASE}/chat/completion", payload)
    if err:
        msgs.append({"role": "assistant", "content": f"❌ 요청 실패: {err}"})
        return
    reply = r.json().get("reply") or "⚠️ 빈 응답입니다."
    msgs.append({"role": "assistant", "content": reply})

def send_answer_pdf(user_text: str):
    msgs = _cur_messages()
    msgs.append({"role": "user", "content": f"(PDF 요청) {user_text}"})
    payload = {
        "question": user_text,
        "policy_type": st.session_state.insurer,
        "top_k": int(st.session_state.top_k),
        "max_tokens": int(st.session_state.max_tokens),
    }
    try:
        r = requests.post(f"{API_BASE}/qa/answer_pdf", json=payload, timeout=(20, 180))
        r.raise_for_status()
    except requests.RequestException as e:
        msgs.append({"role": "assistant", "content": f"❌ PDF 생성 실패: {e}"})
        return
    ctype = r.headers.get("content-type", "").lower()
    if ctype.startswith("application/pdf"):
        msgs.append({"role": "assistant", "content": "PDF가 생성되었습니다. 아래 버튼으로 내려받으세요.",
                     "meta": {"pdf": {"bytes": r.content}}})
    else:
        data = r.json()
        answer = data.get("answer") or "요약이 제공되지 않았습니다."
        sources = data.get("sources") or []
        pdf_url = data.get("pdf_url")
        msgs.append({"role": "assistant", "content": answer,
                     "meta": {"sources": sources, "pdf": {"url": pdf_url} if pdf_url else None}})

# ---------------------------
# 입력창 & 사이드바 액션 처리
# ---------------------------
user_input = st.chat_input(f"[{st.session_state.insurer}] 질문을 입력하고 Enter를 누르세요…",
                           disabled=not insurer_selected)
if user_input:
    send_normal_chat(user_input)
    st.rerun()

if 'make_pdf_clicked' in locals() and make_pdf_clicked:
    last_user = next((m["content"] for m in reversed(_cur_messages())
                      if m["role"]=="user" and not m["content"].startswith("(PDF 요청)")), None)
    if not last_user:
        st.warning("먼저 질문을 입력해 주세요.")
    else:
        send_answer_pdf(last_user)
        st.rerun()

if 'clear_clicked' in locals() and clear_clicked:
    st.session_state.messages_by_insurer[st.session_state.insurer] = []
    st.rerun()
