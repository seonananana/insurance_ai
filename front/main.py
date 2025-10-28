import os
import json
import requests
import streamlit as st
import streamlit.components.v1 as components

# ─────────────────────────────────────────────────────────────
# 기본 설정
# ─────────────────────────────────────────────────────────────
st.set_page_config(page_title="보험 RAG 플랫폼", layout="wide", initial_sidebar_state="expanded")

API_BASE = st.secrets.get("API_BASE") or os.getenv("API_BASE") or "http://localhost:8000"
INSURERS = ["현대해상", "DB손해보험", "삼성화재"]

ss = st.session_state

# --- 보험사별 메시지 저장소 (대화 유지용)
if "messages_by_insurer" not in ss:
    ss["messages_by_insurer"] = {}

# --- 보험사 (최초만 현대해상으로 지정, 이후 변경 유지)
if "insurer" not in ss:
    ss["insurer"] = "현대해상"

# --- 보험사별 메시지 버퍼 생성 (없으면 새로)
if ss["insurer"] not in ss["messages_by_insurer"]:
    ss["messages_by_insurer"][ss["insurer"]] = []

# --- 기타 설정 (최초 실행 시만 초기화)
if "top_k" not in ss:
    ss["top_k"] = 5
if "temperature" not in ss:
    ss["temperature"] = 0.30
if "max_tokens" not in ss:
    ss["max_tokens"] = 512
if "auto_pdf" not in ss:
    ss["auto_pdf"] = True


# --- 헬퍼 함수: 현재 보험사별 메시지 접근
def _msgs():
    return ss["messages_by_insurer"][ss["insurer"]]


def inject_css(css: str):
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)

inject_css("""
:root{ --page-max: 1100px; --page-pad: 16px; }
section[data-testid="stSidebar"], div[data-testid="stSidebar"] {
  visibility:visible !important; opacity:1 !important; transform:none !important;
  display:flex !important; width:320px !important;
}
div.block-container {
  max-width: var(--page-max);
  padding: 18px var(--page-pad) 24px var(--page-pad);
  font-family: 'Noto Sans KR', system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
}
.page-hero { width:100%; background:#2563EB; color:#fff; padding:20px 22px; border-radius:16px;
  font-weight:800; font-size:28px; letter-spacing:-0.3px; margin-bottom:12px; }
div[data-testid="stChatMessage"]{
  border:1px solid #eee; border-radius:16px; padding:10px 14px; margin:8px 0;
  box-shadow:0 2px 10px rgba(0,0,0,.04); background:#fff;
}
blockquote {
  border-left:4px solid #2563EB; padding-left:12px; color:#374151;
  background:#f9fafb; margin:6px 0 12px 0;
}
kbd{ background:#f3f4f6; border:1px solid #e5e7eb; border-bottom-width:2px; padding:2px 6px; border-radius:6px; }
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

# ─────────────────────────────────────────────────────────────
# 참조 문서 정규화 (PDF 기반)
# ─────────────────────────────────────────────────────────────
def _normalize_references(resp_json: dict):
    refs = []
    if isinstance(resp_json.get("references"), list):
        # ✅ 새로운 백엔드 (rag_service) 구조 대응
        for it in resp_json["references"]:
            fname = it.get("file_name") or it.get("doc_id") or it.get("title") or "문서"
            page = it.get("page") or it.get("page_no")
            score = it.get("score")
            snippet = it.get("content") or it.get("text") or it.get("snippet") or ""
            title = f"{fname} (p.{page})" if page else fname
            refs.append({"title": title, "snippet": snippet.strip(), "score": score})
        return refs

    # ✅ context 기반 (구버전 호환)
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

# ─────────────────────────────────────────────────────────────
# 답변 + 근거 카드 렌더링
# ─────────────────────────────────────────────────────────────
def render_answer_card(answer: str, sources: list[dict] | None = None):
    with st.chat_message("assistant"):
        st.markdown(answer)
        if sources:
            with st.expander("🔎 참조 문서 (Top-K)", expanded=False):
                for i, item in enumerate(sources, 1):
                    title = item.get("title") or "제목 없음"
                    score = item.get("score")
                    snippet = (item.get("snippet") or "").strip()
                    if len(snippet) > 600:
                        snippet = snippet[:600] + "…"
                    meta = f" _(score: {score:.4f})_" if isinstance(score, (int, float)) else ""
                    st.markdown(f"**{i}. {title}**{meta}\n\n> {snippet}")

# ─────────────────────────────────────────────────────────────
# PDF 다운로드 함수 (변경 없음)
# ─────────────────────────────────────────────────────────────
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
# 사이드바
# ─────────────────────────────────────────────────────────────
with st.sidebar:
    st.subheader("⚙️ 설정")
    st.selectbox("보험사", INSURERS, key="insurer")
    st.write("Top-K (근거 개수)")
    st.slider("Top-K", 1, 10, key="top_k", label_visibility="collapsed")
    st.toggle("답변 후 자동 PDF 저장", key="auto_pdf")
    hc = _get(f"{API_BASE.rstrip('/')}/health/")
    if isinstance(hc, dict):
        llm_status = "ON" if hc.get("llm_ok", True) else "OFF"
        db_status = "ON" if hc.get("db_ok", True) else "OFF"
        st.caption(f"LLM: {llm_status}  ·  DB: {db_status}")
    st.caption(f"API_BASE: {API_BASE}")

# ─────────────────────────────────────────────────────────────
# 메인
# ─────────────────────────────────────────────────────────────
st.markdown('<div class="page-hero">보험 문서 RAG 플랫폼</div>', unsafe_allow_html=True)
tab_qna, tab_pdf = st.tabs(["💬 Q&A", "📄 PDF 생성(폼)"])

# ─────────────────────────────────────────────────────────────
# 💬 Q&A 탭
# ─────────────────────────────────────────────────────────────
with tab_qna:
    for m in _msgs():
        with st.chat_message(m["role"]):
            st.markdown(m["content"])

    insurer_selected = bool(ss.insurer)
    user_text = st.chat_input(
        f"[{ss.insurer}] 질문을 입력하고 Enter를 누르세요…" if insurer_selected else "보험사를 먼저 선택하세요.",
        disabled=not insurer_selected,
    )

    if user_text:
        log = _msgs()
        log.append({"role": "user", "content": user_text})

        payload_ask = {
            "query": user_text,
            "policy_type": ss.insurer,
            "top_k": int(ss.top_k),
            "max_tokens": int(ss.max_tokens),
            "temperature": float(ss.temperature),
        }

        r, err = _post(f"{API_BASE.rstrip('/')}/qa/ask", payload_ask, timeout=(20, 180))
        if err or r is None:
            log.append({"role": "assistant", "content": f"❌ 요청 실패: {err or 'no response'}"})
            st.rerun()

        data = r.json()
        answer = data.get("answer") or "⚠️ 빈 응답입니다."
        refs = _normalize_references(data)

        # ✅ 참조 문서 리스트를 함께 표시
        render_answer_card(answer, refs)

        log.append({"role": "assistant", "content": answer})

        # 자동 PDF 저장
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

# ─────────────────────────────────────────────────────────────
# 📄 PDF 생성(폼)
# ─────────────────────────────────────────────────────────────
with tab_pdf:
    st.info("이 탭은 폼 기반 PDF 생성 탭입니다. Q&A 탭에서는 답변 후 자동으로 PDF가 저장·다운로드됩니다.")
    st.markdown("#### 폼 입력")

    title = st.text_input("제목", value="보험 청구 상담 결과")
    summary = st.text_area("사건 요약", placeholder="사고/발병 경위, 증상, 치료 정보 등")
    likelihood = st.text_input("청구 가능성(선택)", value="")
    meta = st.text_input("메타 정보(선택)", value=f"모델: gpt-4o-mini / Top-K: {ss.top_k}")

    col1, col2 = st.columns(2)
    with col1:
        required_docs = st.text_area("필요 서류(줄바꿈으로 구분)", value="진단서\n진료비 영수증\n입퇴원확인서")
    with col2:
        timeline = st.text_area("타임라인(예: 2025-01-02 최초 내원 / 2025-01-05 입원 등)", value="초진\n입원\n퇴원")

    appendix = st.text_area("부록(선택)", value="")
    qr_url = st.text_input("QR URL(선택)", value="")

    def _compose_question_from_form():
        parts = []
        if title: parts.append(f"[제목] {title}")
        if summary: parts.append(f"[사건요약] {summary}")
        if likelihood: parts.append(f"[청구가능성] {likelihood}")
        if timeline:
            steps = ", ".join([s.strip() for s in timeline.splitlines() if s.strip()])
            parts.append(f"[타임라인] {steps}")
        if required_docs:
            docs = ", ".join([d.strip() for d in required_docs.splitlines() if d.strip()])
            parts.append(f"[필요서류] {docs}")
        if meta: parts.append(f"[메타] {meta}")
        if appendix: parts.append(f"[부록] {appendix}")
        if qr_url: parts.append(f"[QR] {qr_url}")
        return "\n".join(parts)

    if st.button("📄 PDF 생성 및 다운로드"):
        question_text = _compose_question_from_form()
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
