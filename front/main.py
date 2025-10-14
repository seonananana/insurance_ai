# front/main.py
import os
import requests
import streamlit as st

# ===================== 기본 =====================
st.set_page_config(page_title="보험 문서 RAG", page_icon="🧾", layout="wide")
API_BASE = st.secrets.get("API_BASE") or os.getenv("API_BASE") or "http://localhost:8000"
INSURERS = ["DB손해", "현대해상", "삼성화재"]

ss = st.session_state
ss.setdefault("messages_by_insurer", {})
ss.setdefault("insurer", "현대해상")
ss.setdefault("top_k", 3)
ss.setdefault("temperature", 0.30)
ss.setdefault("max_tokens", 512)

def _msgs():
    k = ss.insurer
    ss.messages_by_insurer.setdefault(k, [])
    return ss.messages_by_insurer[k]

def inject_css(css: str): st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)

# ===================== CSS (최종 고정본) =====================
inject_css("""
:root{
  --page-max: 1000px;   /* 헤더/본문/입력창 동일 폭 */
  --page-pad: 16px;     /* 좌우 패딩 */
  --btn-size: 36px;     /* 전송 버튼 크기 */
  --btn-gap: 8px;       /* 버튼과 입력 우측 테두리 간격 */
  --btn-inset: 16px;    /* 버튼을 입력 상자 '안쪽'으로 들여보내는 정도 */
}

/* 상단 메뉴/Deploy 숨김 */
#MainMenu, header, footer,
div[data-testid="stToolbar"],
div[data-testid="stDecoration"],
div[data-testid="stDeployButton"] { display:none !important; }

/* 본문 폭/패딩 */
div.block-container{
  max-width: var(--page-max);
  padding: 18px var(--page-pad) 0 var(--page-pad);
  font-family: 'Noto Sans KR', system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
}

/* 헤더(파란 박스) */
.page-hero{
  width:100%; background:#2563EB; color:#fff;
  padding:22px 24px; border-radius:16px;
  font-weight:800; font-size:34px; letter-spacing:-0.3px; margin-bottom:12px;
}
/* 헤더 아래 선 제거 */
hr.page-divider{ display:none !important; }

/* 메시지 버블 */
div[data-testid="stChatMessage"]{
  border:1px solid #eee; border-radius:16px; padding:10px 14px; margin:8px 0;
  box-shadow:0 2px 10px rgba(0,0,0,.04); background:#fff;
}

/* ===== 입력창 정렬/고정 ===== */
div[data-testid="stChatInput"]{
  position: sticky; bottom:0; z-index:5;
  background:rgba(255,255,255,.92);
  border-top:0 !important; padding:0;
}
div[data-testid="stChatInput"] > div{
  max-width: var(--page-max); margin: 0 auto; padding: 0 var(--page-pad);
}
/* 겹박스 제거 */
div[data-testid="stChatInput"] > div,
div[data-testid="stChatInput"] > div > div,
div[data-testid="stChatInput"] form{
  background: transparent !important; border:0 !important; box-shadow:none !important;
}
/* 왼쪽 이모지/첨부 아이콘만 숨김 */
div[data-testid="stChatInput"] label svg,
div[data-testid="stChatInput"] label [role="img"],
div[data-testid="stChatInput"] label [data-testid*="icon"]{
  display:none !important;
  width:0 !important;height:0 !important;opacity:0 !important;
  visibility:hidden !important;pointer-events:none !important;margin:0 !important;
}

/* 입력 상자: 버튼 자리 확보 + 높이 통일 */
div[data-testid="stChatInput"] textarea,
div[data-testid="stChatInput"] input[type="text"]{
  width:100% !important; box-sizing:border-box !important; min-height:44px;
  /* 버튼 크기 + inset + gap 만큼 우측 여백 확보 */
  padding-right: calc(var(--btn-size) + var(--btn-inset) + var(--btn-gap)) !important;
  border:1px solid #e5e7eb !important; border-radius:12px !important;
}

/* 폼을 기준으로 버튼 절대배치 */
div[data-testid="stChatInput"] form{ position:relative; }

/* 전송 버튼을 입력 상자 '안쪽' 오른쪽에 고정 */
div[data-testid="stChatInput"] [data-testid="stChatInputSubmitButton"],
div[data-testid="stChatInput"] form button:last-of-type{
  position:absolute !important;
  /* 페이지 패딩 + inset 값만큼 왼쪽으로 들여서 상자 안쪽에 박음 */
  right: calc(var(--page-pad) + var(--btn-gap)) !important;
  top:50% !important; transform: translateY(-50%) !important;
  width: var(--btn-size) !important; height: var(--btn-size) !important;
  padding:0 !important; border-radius:10px !important;
  display:flex !important; align-items:center !important; justify-content:center !important;
  z-index: 2;
  /* 버튼을 살짝 안쪽으로 더 들여보내기 (입력 상자 테두리 안) */
  margin-right: var(--btn-inset) !important;
}

/* 버튼 아이콘 정상 표시 */
div[data-testid="stChatInput"] [data-testid="stChatInputSubmitButton"] svg,
div[data-testid="stChatInput"] form button:last-of-type svg{
  width:18px !important; height:18px !important; display:inline-block !important;
  opacity:1 !important; visibility:visible !important;
}

/* 사이드바 폭 */
section[data-testid="stSidebar"]{ width:320px !important; }
""")

# ===================== 사이드바 =====================
with st.sidebar:
    st.subheader("⚙️ 설정")
    st.selectbox("보험사", INSURERS, key="insurer")
    st.write("Top-K (근거 개수)")
    st.slider("Top-K", 1, 10, key="top_k", label_visibility="collapsed")
    st.write("온도(창의성)")
    st.slider("온도", 0.0, 1.0, step=0.01, key="temperature", label_visibility="collapsed")
    st.write("최대 토큰")
    st.slider("max tokens", 128, 2048, step=64, key="max_tokens", label_visibility="collapsed")
    c1, c2 = st.columns(2)
    with c1: make_pdf = st.button("📄 PDF 생성", use_container_width=True)
    with c2: clear_chat = st.button("🗑️ 대화 지우기", use_container_width=True)
    st.caption(f"API_BASE: {API_BASE}")

# ===================== 헤더 =====================
st.markdown('<div class="page-hero">보험 문서 RAG 플랫폼</div>', unsafe_allow_html=True)

# ===================== 채팅 표시 =====================
for m in _msgs():
    with st.chat_message(m["role"]):
        st.markdown(m["content"])

# ===================== 서버 통신 =====================
def _post(url, payload, timeout=(20,180)):
    try:
        r = requests.post(url, json=payload, timeout=timeout); r.raise_for_status()
        return r.json(), None
    except requests.RequestException as e:
        return None, str(e)

def send_chat(t):
    log = _msgs()
    log.append({"role":"user","content":t})
    data, err = _post(f"{API_BASE}/chat/completion", {
        "messages":[{"role":"user","content":t}],
        "insurer": ss.insurer,
        "top_k": int(ss.top_k),
        "temperature": float(ss.temperature),
        "max_tokens": int(ss.max_tokens),
    })
    if err: log.append({"role":"assistant","content": f"❌ 요청 실패: {err}"}); return
    log.append({"role":"assistant","content": (data or {}).get("reply") or "⚠️ 빈 응답입니다."})

def send_pdf_from_last():
    """
    마지막 assistant 답변을 /export/pdf 로 보내 PDF를 받고,
    그 자리에서 즉시 다운로드 버튼을 띄운다.
    (CSS/레이아웃 안 건드림)
    """
    import os, requests, streamlit as st

    # API_BASE: 네 코드 전역에 있으면 그걸 쓰고, 없으면 기본값
    API = globals().get("API_BASE") or os.environ.get("API_BASE", "http://localhost:8000")

    # 마지막 assistant 메시지 찾기 (_msgs()가 있으면 사용, 없으면 session_state.messages 사용)
    try:
        msgs = _msgs()  # 네 파일에 이미 있을 가능성 높음
    except NameError:
        msgs = st.session_state.get("messages", [])
    last_answer = ""
    for m in reversed(msgs or []):
        role = (m.get("role") or m.get("speaker") or "").lower()
        if role in ("assistant", "ai", "bot"):
            last_answer = m.get("content", "")
            break

    if not last_answer.strip():
        with st.chat_message("assistant"):
            st.warning("먼저 질문하고 답변을 생성하세요.")
        return

    # 백엔드에 PDF 생성 요청
    try:
        resp = requests.post(
            f"{API.rstrip('/')}/export/pdf",
            json={"title": "상담 결과", "content": last_answer},
            timeout=60,
        )
        resp.raise_for_status()
        pdf_bytes = resp.content or b""
    except requests.RequestException as e:
        with st.chat_message("assistant"):
            st.error(f"PDF 생성 실패: {e}")
        return

    if not pdf_bytes:
        with st.chat_message("assistant"):
            st.error("PDF가 비어 있습니다. 서버 응답을 확인하세요.")
        return

    # 여기서 즉시 다운로드 버튼 표기 (리런되더라도 이번 런에서는 보임)
    with st.chat_message("assistant"):
        st.success("PDF가 생성되었습니다. 아래에서 내려받기 하세요.")
        st.download_button(
            label="⬇️ 다운로드",
            data=pdf_bytes,
            file_name="answer.pdf",
            mime="application/pdf",
            type="primary",
            use_container_width=True,
        )

# ===================== 입력 / 액션 =====================
user_text = st.chat_input(f"[{ss.insurer}] 질문을 입력하고 Enter를 누르세요…", disabled=not bool(ss.insurer))
if user_text:
    send_chat(user_text); st.rerun()
if make_pdf:
    send_pdf_from_last(); st.rerun()
if clear_chat:
    ss.messages_by_insurer[ss.insurer] = []; st.rerun()
