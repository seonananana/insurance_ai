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
/* 전체 폰트/기본 */
html, body, [class*="stApp"] { font-family: 'Noto Sans KR', system-ui, -apple-system, sans-serif; }
h1, h2, h3 { letter-spacing: -0.3px; }

/* 페이지 컨테이너 폭 (헤더/디바이더/입력창 동일) */
div.block-container { max-width: 1000px; padding-top: 18px; }

/* 사이드바 */
section[data-testid="stSidebar"] { width: 320px !important; }
section[data-testid="stSidebar"] [data-testid="stSidebarContent"] { padding-top: 12px; }

/* 헤더 카드: 파란 배경 + 흰 글자 + 컨테이너 가득 채우기 */
.page-hero{
  display:block;           /* ✅ 블록 요소로 강제 */
  width:100% !important;   /* ✅ 컨테이너 전체 폭 */
  background:#2563EB; color:#fff;
  padding:22px 24px; border-radius:16px;
  font-weight:800; font-size:34px; letter-spacing:-0.3px;
  margin-bottom:12px;
}

/* 헤더 아래 구분선(컨테이너 전체) */
hr.page-divider{
  border:none; height:1px; background:#E5E7EB; margin:18px 0 12px;
}

/* 페이지 컨테이너 폭(헤더/구분선/입력창 동일 기준) */
div.block-container{ max-width:1000px; padding-top:18px; }

/* 입력창: 컨테이너 폭과 정확히 맞춤 + 고정 */
div[data-testid="stChatInput"]{
  position: sticky; bottom:0; z-index:5;
  background:rgba(255,255,255,0.92); backdrop-filter:saturate(1.8) blur(6px);
  border-top:1px solid #eee;
  width:100% !important;
  margin-left:0 !important; margin-right:0 !important;
  padding-left:0 !important; padding-right:0 !important;
}
/* 내부 래퍼들이 걸어둔 max-width 해제 */
div[data-testid="stChatInput"] form,
div[data-testid="stChatInput"] > div,
div[data-testid="stChatInput"] > div > div{
  width:100% !important; max-width:100% !important;
}

/* 입력창: 컨테이너 폭과 정확히 맞춤 + 고정 */
div[data-testid="stChatInput"]{
  position: sticky; bottom: 0; z-index: 5;
  background: rgba(255,255,255,0.92);
  backdrop-filter: saturate(1.8) blur(6px);
  border-top: 1px solid #eee;
  width: 100% !important;
  margin-left: 0 !important; margin-right: 0 !important;
}
div[data-testid="stChatInput"] > div{
  width: 100% !important; max-width: 100% !important;
}

/* 버튼 둥글게 */
button, .stDownloadButton, .stLinkButton { border-radius: 10px !important; }

/* 캡션 톤 */
small, .stCaption { color:#6b7280 !important; }
""")

# ---------------------------
# 상태
# ---------------------------
def ensure_state():
    ss = st.session_state
    # 예전 단일 메시지 리스트를 쓰고 있었다면 1회 마이그레이션
    if "messages_by_insurer" not in ss:
        ss["messages_by_insurer"] = {}
        if ss.get("messages"):
            fallback_owner = ss.get("insurer") or "기본"
            ss["messages_by_insurer"][fallback_owner] = ss["messages"]
        ss["messages"] = []  # 더는 사용하지 않음

    ss.setdefault("insurer", None)  # 선택 박스 값이 여기에 직접 들어옴
    ss.setdefault("top_k", 3)
    ss.setdefault("temperature", DEFAULT_TEMP)
    ss.setdefault("max_tokens", DEFAULT_MAXTOK)

ensure_state()

def _cur_messages():
    """현재 선택된 보험사의 메시지 리스트를 반환(없으면 생성)."""
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
    st.selectbox(
        "보험사",
        options,
        index=default_idx,
        key="insurer",  # 세션에 직접 저장
        help="검색에 사용할 문서를 어느 보험사 것으로 제한할지 선택합니다.",
    )

    st.session_state.top_k = st.slider(
        "Top-K (근거 개수)", 1, 10, st.session_state.get("top_k", 3),
        help="질문과 가장 유사한 문서 조각을 몇 개까지 불러올지입니다. 높을수록 느려질 수 있습니다."
    )
    st.session_state.temperature = st.slider(
        "온도(창의성)", 0.0, 1.0, float(st.session_state.get("temperature", DEFAULT_TEMP)), 0.05,
        help="답변의 무작위성입니다. 문서 QA는 0.2~0.4 권장."
    )
    st.session_state.max_tokens = st.slider(
        "최대 토큰", 128, 2048, int(st.session_state.get("max_tokens", DEFAULT_MAXTOK)), 64,
        help="생성 길이 상한. 클수록 느릴 수 있어요."
    )

    st.markdown("---")
    col_a, col_b = st.columns(2)
    with col_a:
        make_pdf_clicked = st.button("📄 PDF 생성", use_container_width=True)
    with col_b:
        clear_clicked = st.button("🗑️ 대화 지우기", use_container_width=True)

    with st.expander("ℹ️ 이 옵션은 뭐죠?"):
        st.markdown(
            "- **보험사**: 해당 보험사의 약관/안내문만 우선 검색합니다.\n"
            "- **Top-K**: 근거 문서 조각 개수(3~5 권장).\n"
            "- **온도**: 0=보수적, 1=창의적. 문서 QA는 0.2~0.4.\n"
            "- **최대 토큰**: 답변 길이 상한."
        )
    st.markdown("---")
    st.caption(f"API_BASE: {API_BASE}")

# ---------------------------
# 헤더 (파란 카드 + 디바이더)
# ---------------------------
st.markdown('<div class="page-hero">보험 문서 RAG 플랫폼</div>', unsafe_allow_html=True)
st.markdown('<hr class="page-divider"/>', unsafe_allow_html=True)

# ---------------------------
# 오버레이 & 게이트
# ---------------------------
def render_overlay():
    st.markdown(
        """
        <style>
        .overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.25);
                   display: flex; align-items: center; justify-content: center; z-index: 9999; }
        .overlay-card { background: white; padding: 24px 28px; border-radius: 12px;
                        box-shadow: 0 10px 30px rgba(0,0,0,0.2); font-size: 18px; text-align: center; }
        </style>
        <div class="overlay"><div class="overlay-card">
            <b>보험사를 선택해 주세요.</b><br/>왼쪽 사이드바에서 보험사를 고르면 시작할 수 있어요.
        </div></div>
        """, unsafe_allow_html=True
    )

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
        # 근거
        sources = meta.get("sources") or []
        if sources:
            with st.expander("🔎 근거 문서/소스", expanded=False):
                for i, h in enumerate(sources, 1):
                    title = h.get("clause_title") or h.get("doc_id") or f"source {i}"
                    score = h.get("score")
                    snippet = (h.get("content") or "").strip()
                    if len(snippet) > 320: snippet = snippet[:320] + "…"
                    st.markdown(f"**{i}. {title}** (score: {score})\n\n> {snippet}")
        # PDF
        pdf = meta.get("pdf")
        if isinstance(pdf, dict):
            pdf_url = pdf.get("url")
            pdf_bytes = pdf.get("bytes")
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
        msgs.append({
            "role": "assistant",
            "content": "PDF가 생성되었습니다. 아래 버튼으로 내려받으세요.",
            "meta": {"pdf": {"bytes": r.content}}
        })
    else:
        data = r.json()
        answer = data.get("answer") or "요약이 제공되지 않았습니다."
        sources = data.get("sources") or []
        pdf_url = data.get("pdf_url")
        msgs.append({
            "role": "assistant",
            "content": answer,
            "meta": {"sources": sources, "pdf": {"url": pdf_url} if pdf_url else None}
        })

# ---------------------------
# 입력창 & 사이드바 액션 처리
# ---------------------------
user_input = st.chat_input(
    f"[{st.session_state.insurer}] 질문을 입력하고 Enter를 누르세요…",
    disabled=not insurer_selected,
)
if user_input:
    send_normal_chat(user_input)
    st.rerun()   # 전송 직후 즉시 반영

if 'make_pdf_clicked' in locals() and make_pdf_clicked:
    last_user = next((m["content"] for m in reversed(_cur_messages())
                      if m["role"] == "user" and not m["content"].startswith("(PDF 요청)")), None)
    if not last_user:
        st.warning("먼저 질문을 입력해 주세요.")
    else:
        send_answer_pdf(last_user)
        st.rerun()   # PDF 생성 후 즉시 반영

if 'clear_clicked' in locals() and clear_clicked:
    st.session_state.messages_by_insurer[st.session_state.insurer] = []
    st.rerun()
