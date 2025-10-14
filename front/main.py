# front/main.py
import os
import requests
import streamlit as st

# ------------------------------------------------------------
# 기본 설정
# ------------------------------------------------------------
st.set_page_config(page_title="보험 문서 RAG", page_icon="🧾", layout="wide")

API_BASE = st.secrets.get("API_BASE") or os.getenv("API_BASE") or "http://localhost:8000"
INSURERS = ["DB손해", "현대해상", "삼성화재"]
DEFAULT_TEMP = 0.30
DEFAULT_MAXTOK = 512

# ------------------------------------------------------------
# 유틸
# ------------------------------------------------------------
def inject_css(css: str):
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)

inject_css("""
/* ================== 상단/브랜딩 숨김 ================== */
#MainMenu {visibility:hidden;}
header {visibility:hidden;}
footer {visibility:hidden;}
div[data-testid="stToolbar"]{display:none;}
div[data-testid="stDecoration"]{display:none;}
div[data-testid="stDeployButton"]{display:none;}

/* ================== 기본 타이포/컨테이너 ================== */
html, body, [class*="stApp"] { font-family: 'Noto Sans KR', system-ui, -apple-system, sans-serif; }
h1, h2, h3 { letter-spacing: -0.3px; }
div.block-container { max-width: 1000px; padding-top: 18px; }

/* 사이드바 폭 */
section[data-testid="stSidebar"] { width: 320px !important; }
section[data-testid="stSidebar"] [data-testid="stSidebarContent"] { padding-top: 12px; }

/* ================== 전체폭 래퍼 ================== */
.full-row, .full-row > div, .full-row [data-testid="stMarkdownContainer"]{
  width:100% !important; max-width:100% !important;
}
.full-row .element-container{ margin:0 !important; padding:0 !important; width:100% !important; }

/* ================== 헤더 카드/구분선 ================== */
.page-hero{
  display:block; width:100% !important; box-sizing:border-box;
  background:#2563EB; color:#fff; padding:22px 24px; border-radius:16px;
  font-weight:800; font-size:34px; letter-spacing:-0.3px; margin-bottom:12px;
}
hr.page-divider{ border:none; height:1px; background:#E5E7EB; margin:18px 0 12px; width:100%; }

/* ================== 채팅 버블 ================== */
div[data-testid="stChatMessage"]{
  border:1px solid #eee; border-radius:16px; padding:10px 14px; margin:8px 0;
  box-shadow:0 2px 10px rgba(0,0,0,0.04); background:#fff;
}
div[data-testid="stChatMessage"] pre { background:#f7f8fb; }

/* ================== 입력창 정렬/커스터마이즈 ================== */
div[data-testid="stChatInput"]{
  position: sticky; bottom: 0; z-index: 5;
  background: rgba(255,255,255,0.92);
  backdrop-filter: saturate(1.8) blur(6px);
  border-top: 1px solid #eee;
  padding-left:0 !important; padding-right:0 !important;
}

/* 입력창도 본문과 같은 1000px로 중앙 정렬 */
div[data-testid="stChatInput"] > div{ max-width:1000px !important; margin:0 auto !important; }

/* 왼쪽 기본 이모지/아이콘 전부 숨김 (전송 버튼은 유지) */
div[data-testid="stChatInput"] label svg,
div[data-testid="stChatInput"] [role="img"],
div[data-testid="stChatInput"] [data-testid*="icon"]{
  width:0 !important; height:0 !important; opacity:0 !important; visibility:hidden !important;
  pointer-events:none !important; margin:0 !important;
}

/* 폼 기준 배치 & 전송 버튼을 맨 오른쪽에 고정 */
div[data-testid="stChatInput"] form{ position:relative; }
div[data-testid="stChatInput"] form button:last-of-type{
  position:absolute; right:8px; top:50%; transform:translateY(-50%);
  min-width:36px; height:36px; padding:0 10px; border-radius:10px;
}

/* 전송 버튼 공간만큼 우측 패딩 확보 + 높이 통일 */
div[data-testid="stChatInput"] textarea,
div[data-testid="stChatInput"] input[type="text"]{
  padding-right:60px !important; min-height:44px;
  border:1px solid #e5e7eb !important; border-radius:12px !important;
}

/* 둥근 버튼 & 캡션 톤 */
.stButton>button, .stDownloadButton>button, .stLinkButton>button{ border-radius: 10px !important; }
small, .stCaption { color:#6b7280 !important; }

/* 스트림릿 노란 경고(세션 충돌 등) 숨김 */
div[data-testid="stNotification"]{ display:none !important; }
""")

# ------------------------------------------------------------
# 세션 상태 (경고 회피: 위젯 만들기 '전'에만 기본값 주입)
# ------------------------------------------------------------
ss = st.session_state
ss.setdefault("messages_by_insurer", {})
ss.setdefault("insurer", "선택하세요…")  # 첫 로드시 placeholder 선택
ss.setdefault("top_k", 3)
ss.setdefault("temperature", DEFAULT_TEMP)
ss.setdefault("max_tokens", DEFAULT_MAXTOK)

def _cur_messages():
    key = ss.insurer
    if key not in ss.messages_by_insurer:
        ss.messages_by_insurer[key] = []
    return ss.messages_by_insurer[key]

# ------------------------------------------------------------
# HTTP
# ------------------------------------------------------------
def post_json(url: str, payload: dict, timeout=(20, 180)):
    try:
        r = requests.post(url, json=payload, timeout=timeout)
        r.raise_for_status()
        return r
    except requests.RequestException as e:
        return e

# ------------------------------------------------------------
# 사이드바
# ------------------------------------------------------------
with st.sidebar:
    st.subheader("⚙️ 설정")
    options = ["선택하세요…"] + INSURERS
    # 기본값은 위의 ss.setdefault("insurer")로 넣었으므로 index 지정하지 않음(노란 박스 방지)
    st.selectbox("보험사", options, key="insurer",
                 help="검색에 사용할 문서를 어느 보험사 것으로 제한할지 선택합니다.")

    # value 인자 없이 key만 사용(기본값은 ss.setdefault로 이미 주입) → 노란 박스 방지
    st.write("Top-K (근거 개수)")
    st.slider("Top-K (근거 개수)", 1, 10, key="top_k", label_visibility="collapsed")

    st.write("온도(창의성)")
    st.slider("온도", 0.0, 1.0, step=0.05, key="temperature", label_visibility="collapsed")

    st.write("최대 토큰")
    st.slider("max tokens", 128, 2048, step=64, key="max_tokens", label_visibility="collapsed")

    st.markdown("---")
    col_a, col_b = st.columns(2)
    with col_a:
        make_pdf_clicked = st.button("📄 PDF 생성", use_container_width=True)
    with col_b:
        clear_clicked = st.button("🗑️ 대화 지우기", use_container_width=True)

    st.caption(f"API_BASE: {API_BASE}")

# ------------------------------------------------------------
# 헤더/구분선
# ------------------------------------------------------------
st.markdown('<div class="full-row"><div class="page-hero">보험 문서 RAG 플랫폼</div></div>', unsafe_allow_html=True)
st.markdown('<div class="full-row"><hr class="page-divider"/></div>', unsafe_allow_html=True)

# ------------------------------------------------------------
# 보험사 선택 게이트
# ------------------------------------------------------------
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

insurer_selected = ss.insurer in INSURERS
if not insurer_selected:
    render_overlay()

# ------------------------------------------------------------
# 채팅 메시지 렌더
# ------------------------------------------------------------
for msg in _cur_messages():
    with st.chat_message("user" if msg["role"] == "user" else "assistant"):
        st.markdown(msg["content"])
        meta = (msg.get("meta") or {})
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

# ------------------------------------------------------------
# 호출 함수 (선택 보험사 스레드에만 기록)
# ------------------------------------------------------------
def send_normal_chat(user_text: str):
    msgs = _cur_messages()
    msgs.append({"role": "user", "content": user_text})
    payload = {
        "messages": [{"role": "user", "content": user_text}],
        "insurer": ss.insurer,
        "top_k": int(ss.top_k),
        "temperature": float(ss.temperature),
        "max_tokens": int(ss.max_tokens),
    }
    r = post_json(f"{API_BASE}/chat/completion", payload)
    if isinstance(r, Exception):
        msgs.append({"role": "assistant", "content": f"❌ 요청 실패: {r}"})
        return
    reply = r.json().get("reply") or "⚠️ 빈 응답입니다."
    msgs.append({"role": "assistant", "content": reply})

def send_answer_pdf(user_text: str):
    msgs = _cur_messages()
    msgs.append({"role":"user", "content": f"(PDF 요청) {user_text}"})
    payload = {
        "messages": [{"role":"user","content": user_text}],
        "insurer": ss.insurer,
        "top_k": int(ss.top_k),
        "temperature": float(ss.temperature),
        "max_tokens": int(ss.max_tokens),
        "pdf": True,
    }
    try:
        r = requests.post(f"{API_BASE}/qa/answer_pdf", json=payload, timeout=(20, 300))
        r.raise_for_status()
    except requests.RequestException as e:
        msgs.append({"role":"assistant","content": f"❌ PDF 생성 실패: {e}"})
        return

    ctype = (r.headers.get("content-type") or "").lower()
    if ctype.startswith("application/pdf"):
        # 서버가 바로 PDF 바이트를 주는 케이스
        with st.chat_message("assistant"):
            st.markdown("PDF가 생성되었습니다. 아래 버튼으로 내려받으세요.")
            st.download_button("📄 PDF 다운로드", data=r.content, file_name="rag_answer.pdf", mime="application/pdf")
        return

    # JSON(요약/링크) 형태
    data = r.json()
    answer = data.get("answer") or "요약이 제공되지 않았습니다."
    sources = data.get("sources") or []
    pdf_url = data.get("pdf_url")
    msgs.append({"role": "assistant", "content": answer,
                 "meta": {"sources": sources, "pdf": {"url": pdf_url} if pdf_url else None}})

# ------------------------------------------------------------
# 입력창 & 사이드바 액션 처리
# ------------------------------------------------------------
user_input = st.chat_input(f"[{ss.insurer}] 질문을 입력하고 Enter를 누르세요…",
                           disabled=not insurer_selected)
if user_input:
    send_normal_chat(user_input)
    st.rerun()

if make_pdf_clicked:
    last_user = next((m["content"] for m in reversed(_cur_messages())
                      if m["role"]=="user" and not m["content"].startswith("(PDF 요청)")), None)
    if not last_user:
        with st.chat_message("assistant"):
            st.warning("먼저 질문을 입력해 주세요.")
    else:
        send_answer_pdf(last_user)
    st.rerun()

if clear_clicked:
    ss.messages_by_insurer[ss.insurer] = []
    st.rerun()
