# front/main.py
import os
import requests
import streamlit as st

# ===================== 기본 설정 =====================
st.set_page_config(page_title="보험 문서 RAG", page_icon="🧾", layout="wide")

API_BASE = st.secrets.get("API_BASE") or os.getenv("API_BASE") or "http://localhost:8000"
INSURERS = ["DB손해", "현대해상", "삼성화재"]

ss = st.session_state
ss.setdefault("messages_by_insurer", {})
ss.setdefault("insurer", "현대해상")
ss.setdefault("top_k", 3)
ss.setdefault("temperature", 0.30)   # 현재 /qa/ask엔 미사용이지만 UI에서 보관
ss.setdefault("max_tokens", 512)

def _msgs():
    k = ss.insurer
    ss.messages_by_insurer.setdefault(k, [])
    return ss.messages_by_insurer[k]

# ===================== CSS (통합 고정본) =====================
def inject_css(css: str): st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)

inject_css("""
:root{
  --page-max: 1000px;
  --page-pad: 16px;
  --btn-size: 36px;
  --btn-gap: 8px;
  --btn-inset: 16px;
}
#MainMenu, header, footer,
div[data-testid="stToolbar"],
div[data-testid="stDecoration"],
div[data-testid="stDeployButton"] { display:none !important; }

div.block-container{
  max-width: var(--page-max);
  padding: 18px var(--page-pad) 0 var(--page-pad);
  font-family: 'Noto Sans KR', system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
}
.page-hero{
  width:100%; background:#2563EB; color:#fff;
  padding:22px 24px; border-radius:16px;
  font-weight:800; font-size:34px; letter-spacing:-0.3px; margin-bottom:12px;
}

div[data-testid="stChatMessage"]{
  border:1px solid #eee; border-radius:16px; padding:10px 14px; margin:8px 0;
  box-shadow:0 2px 10px rgba(0,0,0,.04); background:#fff;
}

/* 입력창 고정 & 버튼 정렬 */
div[data-testid="stChatInput"]{
  position: sticky; bottom:0; z-index:5;
  background:rgba(255,255,255,.92);
  border-top:0 !important; padding:0;
}
div[data-testid="stChatInput"] > div{
  max-width: var(--page-max); margin: 0 auto; padding: 0 var(--page-pad);
}
div[data-testid="stChatInput"] > div,
div[data-testid="stChatInput"] > div > div,
div[data-testid="stChatInput"] form{
  background: transparent !important; border:0 !important; box-shadow:none !important;
}
div[data-testid="stChatInput"] label svg,
div[data-testid="stChatInput"] label [role="img"],
div[data-testid="stChatInput"] label [data-testid*="icon"]{
  display:none !important; width:0 !important; height:0 !important; opacity:0 !important;
  visibility:hidden !important; pointer-events:none !important; margin:0 !important;
}
div[data-testid="stChatInput"] textarea,
div[data-testid="stChatInput"] input[type="text"]{
  width:100% !important; box-sizing:border-box !important; min-height:44px;
  padding-right: calc(var(--btn-size) + var(--btn-inset) + var(--btn-gap)) !important;
  border:1px solid #e5e7eb !important; border-radius:12px !important;
}
div[data-testid="stChatInput"] form{ position:relative; }
div[data-testid="stChatInput"] [data-testid="stChatInputSubmitButton"],
div[data-testid="stChatInput"] form button:last-of-type{
  position:absolute !important;
  right: calc(var(--page-pad) + var(--btn-gap)) !important;
  top:50% !important; transform: translateY(-50%) !important;
  width: var(--btn-size) !important; height: var(--btn-size) !important;
  padding:0 !important; border-radius:10px !important;
  display:flex !important; align-items:center !important; justify-content:center !important;
  z-index: 2;
  margin-right: var(--btn-inset) !important;
}
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

# ===================== 기존 메시지 렌더 =====================
for m in _msgs():
    with st.chat_message(m["role"]):
        st.markdown(m["content"])

# ===================== 공통 HTTP 유틸 =====================
def _post(url, payload, timeout=(20,180)):
    try:
        r = requests.post(url, json=payload, timeout=timeout)
        r.raise_for_status()
        return r, None
    except requests.RequestException as e:
        return None, str(e)

# ===================== 소스 파싱/렌더 =====================
def _split_sources_from_context(ctx_text: str):
    if not ctx_text:
        return []
    blocks = [b for b in ctx_text.split("\n\n---\n\n") if b.strip()]
    out = []
    for i, b in enumerate(blocks, 1):
        lines = b.splitlines()
        title = lines[0][:160] if lines else f"근거 {i}"
        snippet = b if len(b) <= 600 else (b[:600] + "…")
        out.append({"title": title, "snippet": snippet, "score": None})
    return out

def render_answer_card(answer: str, sources: list[dict] | None = None):
    with st.chat_message("assistant"):
        st.markdown(answer)
        if sources:
            with st.expander("🔎 참조 문서 (Top-K)", expanded=False):
                for i, item in enumerate(sources, 1):
                    title = item.get("title") or "제목 없음"
                    score = item.get("score")
                    snippet = item.get("snippet") or ""
                    if len(snippet) > 320: snippet = snippet[:320] + "…"
                    st.markdown(
                        f"**{i}. {title}**" +
                        (f" (score: {score})" if score is not None else "") +
                        f"\n\n> {snippet}"
                    )

# ===================== RAG 호출 =====================
def send_rag_chat(user_text: str):
    log = _msgs()
    log.append({"role":"user","content":user_text})

    payload = {
        "query": user_text,
        "policy_type": ss.insurer,
        "top_k": int(ss.top_k),
        "max_tokens": int(ss.max_tokens),
    }
    r, err = _post(f"{API_BASE}/qa/ask", payload, timeout=(20,180))
    if err or r is None:
        log.append({"role":"assistant","content": f"❌ 요청 실패: {err or 'no response'}"})
        return

    data = r.json()
    answer = data.get("answer") or "⚠️ 빈 응답입니다."
    ctx_text = data.get("context") or ""
    sources = _split_sources_from_context(ctx_text)

    # 세션 로그에는 요약(불릿)만 간단히 남김
    extra = ""
    if sources:
        bullets = "\n".join([f"- {s['title']}" for s in sources[:3]])
        extra = f"\n\n🔎 참조 문서 (Top-K)\n{bullets}"
    log.append({"role":"assistant","content": answer + extra})

    # 현재 렌더는 상세 카드로
    render_answer_card(answer, sources)

def send_pdf_from_question(question_text: str):
    """
    /qa/answer_pdf 에 질문을 던져 PDF(바이트)를 받아,
    리런 없이 즉시 다운로드 버튼을 표시한다.
    """
    log = _msgs()
    log.append({"role":"user","content": f"(PDF 요청) {question_text}"})

    payload = {
        "question": question_text,
        "policy_type": ss.insurer,
        "top_k": int(ss.top_k),
        "max_tokens": int(ss.max_tokens),
    }
    try:
        resp = requests.post(f"{API_BASE.rstrip('/')}/qa/answer_pdf",
                             json=payload, timeout=300)
        # 200이면서 JSON일 수도 있으니 content-type 확인
        ctype = resp.headers.get("content-type","")
        if not resp.ok:
            raise requests.HTTPError(f"{resp.status_code} {resp.text}")
    except requests.RequestException as e:
        log.append({"role":"assistant","content": f"❌ PDF 생성 실패: {e}"})
        return

    if ctype.startswith("application/pdf"):
        pdf_bytes = resp.content or b""
        if not pdf_bytes:
            log.append({"role":"assistant","content": "⚠️ PDF가 비어 있습니다. 서버 응답 확인 필요."})
            return
        log.append({"role":"assistant","content": "📄 PDF가 생성되었습니다. 아래 버튼으로 받으세요."})
        with st.chat_message("assistant"):
            st.download_button(
                label="⬇️ PDF 다운로드",
                data=pdf_bytes,
                file_name="rag_answer.pdf",
                mime="application/pdf",
                use_container_width=True,
                type="primary",
            )
        # 주의: 여기서 st.rerun() 호출하지 않음 (버튼 사라지는 문제 방지)
    else:
        # 백엔드가 fallback JSON을 준 경우
        data = {}
        try:
            data = resp.json()
        except Exception:
            pass
        msg = (data.get("answer") if isinstance(data, dict) else None) or "⚠️ PDF 생성에 실패했습니다."
        log.append({"role":"assistant","content": msg})

# ===================== 입력/버튼 액션 =====================
insurer_selected = bool(ss.insurer)
user_text = st.chat_input(
    f"[{ss.insurer}] 질문을 입력하고 Enter를 누르세요…" if insurer_selected else "보험사를 먼저 선택하세요.",
    disabled=not insurer_selected
)
if user_text:
    send_rag_chat(user_text)
    st.rerun()

if make_pdf:
    # 직전 "일반 질문"을 PDF 생성 질문으로 사용
    last_user_q = next(
        (m["content"] for m in reversed(_msgs())
         if m["role"] == "user" and not m["content"].startswith("(PDF 요청)")),
        ""
    )
    if not last_user_q.strip():
        with st.chat_message("assistant"):
            st.warning("먼저 질문을 입력해 주세요.")
    else:
        send_pdf_from_question(last_user_q)

if clear_chat:
    ss.messages_by_insurer[ss.insurer] = []
    st.rerun()
