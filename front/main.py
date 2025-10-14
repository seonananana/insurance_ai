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
/* 스트림릿 상단 메뉴/Deploy/브랜딩 숨김 */
#MainMenu {visibility:hidden;}
header {visibility:hidden;}
footer {visibility:hidden;}
div[data-testid="stToolbar"]{display:none;}
div[data-testid="stDecoration"]{display:none;}
div[data-testid="stDeployButton"]{display:none;}

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

/* ====== 입력창 폭 정렬 + 왼쪽 이모지 제거 & 전송버튼 오른쪽 정렬 ====== */
div[data-testid="stChatInput"]{
  position: sticky; bottom: 0; z-index: 5;
  background: rgba(255,255,255,0.92);
  backdrop-filter: saturate(1.8) blur(6px);
  border-top: 1px solid #eee;
  width:100% !important;
  margin-left:0 !important; margin-right:0 !important;
  padding-left:0 !important; padding-right:0 !important;
}

/* 폼을 기준으로 배치 */
div[data-testid="stChatInput"] form{ position:relative; }

/* (1) 왼쪽 기본 이모지/아이콘 전부 숨김 */
div[data-testid="stChatInput"] form > svg,
div[data-testid="stChatInput"] form [role="img"]{
  opacity:0 !important; width:0 !important; height:0 !important;
  margin:0 !important; pointer-events:none !important;
}

/* (2) 전송 버튼을 입력창 우측 끝으로 정렬 */
div[data-testid="stChatInput"] form button{
  position:absolute;
  right:8px; top:50%; transform:translateY(-50%);
  min-width:36px; height:36px; padding:0 8px; border-radius:10px;
}

/* (3) 버튼 공간만큼 인풋 오른쪽 패딩 확보 + 높이 통일 */
div[data-testid="stChatInput"] textarea,
div[data-testid="stChatInput"] input[type="text"]{
  padding-right:56px !important; min-height:44px;
}

/* 내부 래퍼 최대폭 해제 */
div[data-testid="stChatInput"] form,
div[data-testid="stChatInput"] > div,
div[data-testid="stChatInput"] > div > div{
  width:100% !important; max-width:100% !important;
}

/* 입력창 박스 자체의 모양(가독성) */
div[data-testid="stChatInput"] textarea,
div[data-testid="stChatInput"] input[type="text"]{
  border:1px solid #e5e7eb !important; border-radius:12px !important;
}

/* 액션 버튼들 */
.stButton>button, .stDownloadButton>button, .stLinkButton>button{
  border-radius:10px !important; padding:8px 12px !important; font-weight:600 !important;
}
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
    except requests.HTTPError as e:
        return None, f"{e} / {getattr(e, 'response', None) and e.response.text}"

# ---------------------------
# UI - 사이드바
# ---------------------------
with st.sidebar:
    st.subheader("⚙️ 설정")
    insurer = st.selectbox("보험사", INSURERS, index=1)  # 기본: 현대해상
    st.session_state.insurer = insurer

    st.write("Top-K (근거 개수)")
    top_k = st.slider("Top-K", 1, 10, st.session_state.top_k, key="top_k", label_visibility="collapsed")

    st.write("온도(창의성)")
    temperature = st.slider("온도", 0.0, 1.0, st.session_state.temperature, 0.01, key="temperature", label_visibility="collapsed")

    st.write("최대 토큰")
    max_tokens = st.slider("max tokens", 128, 2048, st.session_state.max_tokens, key="max_tokens", label_visibility="collapsed")

    cols = st.columns(2)
    with cols[0]:
        make_pdf_clicked = st.button("📄 PDF 생성", use_container_width=True)
    with cols[1]:
        clear_clicked = st.button("🗑️ 대화 지우기", type="secondary", use_container_width=True)

    st.caption(f"API_BASE: {API_BASE}")

# ---------------------------
# 헤더(파란 박스) + 구분선: 전체폭 래퍼(.full-row)로 감쌈
# ---------------------------
st.markdown('<div class="full-row"><div class="page-hero">보험 문서 RAG 플랫폼</div></div>', unsafe_allow_html=True)
st.markdown('<div class="full-row"><hr class="page-divider"/></div>', unsafe_allow_html=True)

# ---------------------------
# 오버레이 & 게이트
# ---------------------------
st.markdown("""
    <style>
    .overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.25); display: none; z-index: 9; }
    .gate {
        position: fixed; inset: 0; display: none; place-items: center; z-index: 10;
        font-size: 14px;
    }
    .gate .card {
        width: 520px; max-width: 90vw; background: #fff; border: 1px solid #e5e7eb;
        border-radius: 14px; padding: 16px 16px 10px 16px; box-shadow: 0 10px 30px rgba(0,0,0,0.08);
    }
    .gate .title { font-weight: 800; font-size: 18px; margin-bottom: 8px; }
    .gate .desc  { color:#555; line-height:1.6; }
    </style>
""", unsafe_allow_html=True)

# ---------------------------
# 채팅 표시
# ---------------------------
for m in _cur_messages():
    with st.chat_message(m["role"]):
        st.markdown(m["content"])

# ---------------------------
# 서버 응답 표시 함수
# ---------------------------
def render_answer_card(answer: str, meta: dict | None = None):
    with st.chat_message("assistant"):
        st.markdown(answer)

        if not meta:
            return
        sources = meta.get("sources") or []
        if sources:
            with st.expander("🔎 참조 문서 (Top-K)", expanded=False):
                for i, item in enumerate(sources, 1):
                    title = item.get("title") or "제목 없음"
                    score = item.get("score")
                    snippet = item.get("snippet") or ""
                    pdf_url = item.get("pdf_url")

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
    msgs.append({"role":"user", "content": f"(PDF 요청) {user_text}"})
    payload = {
        "messages": [{"role":"user","content": user_text}],
        "insurer": st.session_state.insurer,
        "top_k": int(st.session_state.top_k),
        "temperature": float(st.session_state.temperature),
        "max_tokens": int(st.session_state.max_tokens),
        "pdf": True,
    }
    r, err = post_json(f"{API_BASE}/chat/completion", payload, timeout=(20, 300))
    if err:
        msgs.append({"role":"assistant","content": f"❌ PDF 생성 실패: {err}"})
        return

    data = r.json() if r is not None else {}
    answer = data.get("reply") or "⚠️ 빈 응답입니다."
    sources = data.get("sources") or []
    pdf_url = (data.get("pdf") or {}).get("url")
    render_answer_card(answer, {"sources": sources, "pdf": {"url": pdf_url} if pdf_url else None})

# ---------------------------
# 입력창 & 사이드바 액션 처리
# ---------------------------
user_input = st.chat_input(f"[{st.session_state.insurer}] 질문을 입력하고 Enter를 누르세요…",
                           disabled=not insurer_selected if (insurer_selected := bool(st.session_state.insurer)) else True)
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
