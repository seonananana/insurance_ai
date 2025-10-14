# front/main.py
import os
import requests
import streamlit as st

# ============================================================
# 기본 설정
# ============================================================
st.set_page_config(page_title="보험 문서 RAG", page_icon="🧾", layout="wide")

API_BASE = st.secrets.get("API_BASE") or os.getenv("API_BASE") or "http://localhost:8000"
INSURERS = ["DB손해", "현대해상", "삼성화재"]
DEFAULTS = dict(
    insurer="현대해상",
    top_k=3,
    temperature=0.30,
    max_tokens=512,
)

# ============================================================
# 세션 상태 (위젯 만들기 전에만 기본값 주입: 경고 방지)
# ============================================================
ss = st.session_state
ss.setdefault("messages_by_insurer", {})
ss.setdefault("insurer", DEFAULTS["insurer"])
ss.setdefault("top_k", DEFAULTS["top_k"])
ss.setdefault("temperature", DEFAULTS["temperature"])
ss.setdefault("max_tokens", DEFAULTS["max_tokens"])

def _msgs():
    k = ss.insurer
    ss.messages_by_insurer.setdefault(k, [])
    return ss.messages_by_insurer[k]

# ============================================================
# CSS 도우미
# ============================================================
def inject_css(css: str) -> None:
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)

# ===== CSS 주입 (헤더/본문/입력창 폭·패딩 완전 정렬) =====
inject_css("""
:root{
  --page-max: 1000px;     /* 본문/입력창 동일 폭 */
  --page-pad: 16px;       /* 좌우 패딩 */
  --btn-size: 36px;       /* 전송 버튼 한 변 길이 */
  --btn-gap: 6px;         /* 버튼과 입력창 오른쪽 여백 */
}

/* 상단 메뉴/Deploy/브랜딩 숨김 */
#MainMenu, header, footer,
div[data-testid="stToolbar"],
div[data-testid="stDecoration"],
div[data-testid="stDeployButton"] { display:none !important; }

/* 본문 컨테이너 폭/패딩 */
div.block-container{
  max-width: var(--page-max);
  padding: 18px var(--page-pad) 0 var(--page-pad);
  font-family: 'Noto Sans KR', system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
}

/* 헤더 카드 */
.page-hero{
  width:100%; background:#2563EB; color:#fff;
  padding:22px 24px; border-radius:16px;
  font-weight:800; font-size:34px; letter-spacing:-0.3px; margin-bottom:12px;
}

/* 헤더 아래 얇은 선 완전 제거 */
hr.page-divider{ display:none !important; }

/* 채팅 버블 */
div[data-testid="stChatMessage"]{
  border:1px solid #eee; border-radius:16px; padding:10px 14px; margin:8px 0;
  box-shadow:0 2px 10px rgba(0,0,0,.04); background:#fff;
}

/* ===== 입력창을 본문과 정확히 정렬 ===== */
div[data-testid="stChatInput"]{
  position: sticky; bottom:0; z-index:5;
  background:rgba(255,255,255,.92);
  /* 위쪽 얇은 라인도 제거 */
  border-top: 0 !important;
  padding:0; /* 바깥 여백 제거 */
}

/* 입력창 래퍼도 중앙 정렬 + 동일 패딩 */
div[data-testid="stChatInput"] > div{
  max-width: var(--page-max);
  margin: 0 auto;
  padding: 0 var(--page-pad);
}

/* 입력창 주변의 중복 박스/그림자 제거 */
div[data-testid="stChatInput"] > div,
div[data-testid="stChatInput"] > div > div,
div[data-testid="stChatInput"] form{
  background: transparent !important;
  border: 0 !important;
  box-shadow: none !important;
}

/* ✅ 왼쪽 이모지/첨부 아이콘만 숨김 (label 내부만 타겟) */
div[data-testid="stChatInput"] label svg,
div[data-testid="stChatInput"] label [role="img"],
div[data-testid="stChatInput"] label [data-testid*="icon"]{
  display:none !important;
  width:0 !important; height:0 !important;
  opacity:0 !important; visibility:hidden !important;
  pointer-events:none !important; margin:0 !important;
}

/* ✅ 전송 버튼은 정상 표시 + 가운데 정렬 + 크기 고정 */
div[data-testid="stChatInput"] form button{
  position:absolute;                /* (이미 사용 중이면 유지) */
  right: calc(var(--page-pad) + var(--btn-gap));
  top:50%; transform: translateY(-50%);
  width: var(--btn-size); height: var(--btn-size);
  padding:0; border-radius:10px;

  display:flex; align-items:center; justify-content:center; /* ← 아이콘 가운데 정렬 */
}

/* ✅ 전송 버튼 아이콘 복구(크기/가시성) */
div[data-testid="stChatInput"] form button svg,
div[data-testid="stChatInput"] form button [role="img"]{
  width: 18px !important;
  height: 18px !important;
  opacity: 1 !important;
  visibility: visible !important;
  display: inline-block !important;
}

/* 폼 기준 배치 */
div[data-testid="stChatInput"] form{ position:relative; }

/* 입력 상자: 버튼 공간만큼 우측 패딩 확보 */
div[data-testid="stChatInput"] textarea,
div[data-testid="stChatInput"] input[type="text"]{
  width:100% !important; box-sizing: border-box !important;
  min-height: 44px;
  padding-right: calc(var(--btn-size) + var(--btn-gap) + 4px) !important;
  border:1px solid #e5e7eb !important; border-radius:12px !important;
}

/* 전송 버튼: 항상 입력 상자 '안쪽' 오른쪽에 위치 */
div[data-testid="stChatInput"] form button:last-of-type{
  position:absolute;
  right: calc(var(--page-pad) + var(--btn-gap));
  top:50%; transform: translateY(-50%);
  width: var(--btn-size); height: var(--btn-size);
  padding:0; border-radius:10px;
}

/* 사이드바 폭 고정 */
section[data-testid="stSidebar"]{ width:320px !important; }
""")

# ============================================================
# HTTP
# ============================================================
def _post_json(url: str, payload: dict, timeout=(20, 180)):
    try:
        r = requests.post(url, json=payload, timeout=timeout)
        r.raise_for_status()
        return r.json(), None
    except requests.RequestException as e:
        return None, str(e)

# ============================================================
# 사이드바
# ============================================================
with st.sidebar:
    st.subheader("⚙️ 설정")
    # value/index를 따로 주지 않고 key만 사용 → 세션 충돌 경고 미발생
    st.selectbox("보험사", INSURERS, key="insurer")

    st.write("Top-K (근거 개수)")
    st.slider("Top-K", 1, 10, key="top_k", label_visibility="collapsed")

    st.write("온도(창의성)")
    st.slider("온도", 0.0, 1.0, step=0.01, key="temperature", label_visibility="collapsed")

    st.write("최대 토큰")
    st.slider("max tokens", 128, 2048, step=64, key="max_tokens", label_visibility="collapsed")

    c1, c2 = st.columns(2)
    with c1:
        make_pdf = st.button("📄 PDF 생성", use_container_width=True)
    with c2:
        clear_chat = st.button("🗑️ 대화 지우기", use_container_width=True)

    st.caption(f"API_BASE: {API_BASE}")

# ============================================================
# 헤더/구분선
# ============================================================
st.markdown('<div class="page-hero">보험 문서 RAG 플랫폼</div>', unsafe_allow_html=True)
st.markdown('<hr class="page-divider"/>', unsafe_allow_html=True)

# ============================================================
# 채팅 로그 렌더
# ============================================================
for m in _msgs():
    with st.chat_message(m["role"]):
        st.markdown(m["content"])

# ============================================================
# 동작 함수
# ============================================================
def send_chat(user_text: str):
    msgs = _msgs()
    msgs.append({"role":"user","content":user_text})

    data, err = _post_json(f"{API_BASE}/chat/completion", {
        "messages":[{"role":"user","content":user_text}],
        "insurer": ss.insurer,
        "top_k": int(ss.top_k),
        "temperature": float(ss.temperature),
        "max_tokens": int(ss.max_tokens),
    })
    if err:
        msgs.append({"role":"assistant","content": f"❌ 요청 실패: {err}"})
        return
    reply = (data or {}).get("reply") or "⚠️ 빈 응답입니다."
    msgs.append({"role":"assistant","content": reply})

def send_pdf_from_last():
    msgs = _msgs()
    last_q = next((m["content"] for m in reversed(msgs) if m["role"]=="user"), None)
    if not last_q:
        with st.chat_message("assistant"):
            st.warning("먼저 질문을 입력해 주세요.")
        return

    data, err = _post_json(f"{API_BASE}/chat/completion", {
        "messages":[{"role":"user","content":last_q}],
        "insurer": ss.insurer,
        "top_k": int(ss.top_k),
        "temperature": float(ss.temperature),
        "max_tokens": int(ss.max_tokens),
        "pdf": True,
    }, timeout=(20, 300))
    if err:
        with st.chat_message("assistant"):
            st.error(f"PDF 생성 실패: {err}")
        return

    reply = (data or {}).get("reply") or "⚠️ 빈 응답입니다."
    with st.chat_message("assistant"):
        st.markdown(reply)
        pdf_url = (data or {}).get("pdf",{}).get("url")
        if pdf_url:
            href = pdf_url if not pdf_url.startswith("/") else f"{API_BASE}{pdf_url}"
            st.link_button("📄 PDF 열기", href)

# ============================================================
# 입력창 (본문/헤더와 동일 폭·패딩으로 정렬됨)
# ============================================================
user_input = st.chat_input(f"[{ss.insurer}] 질문을 입력하고 Enter를 누르세요…", disabled=not bool(ss.insurer))
if user_input:
    send_chat(user_input)
    st.rerun()

if make_pdf:
    send_pdf_from_last()
    st.rerun()

if clear_chat:
    ss.messages_by_insurer[ss.insurer] = []
    st.rerun()
