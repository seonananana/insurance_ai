# front/main.py
from __future__ import annotations
import os
import json
import time
from io import BytesIO
from typing import Dict, Any, List

import requests
import streamlit as st

# ──────────────────────────────────────────────────────────────────────────────
# 기본 설정
# ──────────────────────────────────────────────────────────────────────────────
DEFAULT_API_BASE = os.environ.get("API_BASE", "http://localhost:8000")
INSURERS = ["현대해상", "삼성화재", "DB손해보험", "메리츠화재", "교보생명", "한화생명"]

st.set_page_config(page_title="보험 문서 RAG", page_icon="📄", layout="wide")

if "messages" not in st.session_state:
    st.session_state.messages: List[Dict[str, str]] = []

if "last_answer" not in st.session_state:
    st.session_state.last_answer = ""

# ──────────────────────────────────────────────────────────────────────────────
# 사이드바(설정)
# ──────────────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ 설정")
    insurer = st.selectbox("보험사", INSURERS, index=0)
    top_k = st.slider("Top-K (근거 개수)", 1, 10, 3)
    temperature = st.slider("온도(창의성)", 0.0, 1.0, 0.30, step=0.01)
    max_tokens = st.slider("최대 토큰", 128, 2048, 512, step=32)

    api_base = st.text_input("API_BASE", value=DEFAULT_API_BASE)
    st.caption(api_base)

    # PDF 생성 버튼
    if st.button("📄 PDF 생성", use_container_width=True):
        _answer = (st.session_state.get("last_answer") or "").strip()
        if not _answer:
            st.warning("먼저 질문해서 답변을 생성하세요.")
        else:
            # 1) 백엔드가 제공하는 /export/pdf 사용 시도
            ok, pdf_bytes, err = try_export_pdf_via_backend(api_base, "상담 결과", _answer)
            if not ok:
                # 2) 백엔드가 없으면 프론트에서 PDF 생성(로컬)
                ok, pdf_bytes, err = try_export_pdf_locally("상담 결과", _answer)

            if ok:
                st.success("PDF가 준비되었습니다. 아래 버튼으로 내려받기 하세요.")
                st.download_button(
                    label="⬇️ 다운로드",
                    data=pdf_bytes,
                    file_name="answer.pdf",
                    mime="application/pdf",
                    type="primary",
                    key=f"download_{int(time.time())}",
                    use_container_width=True,
                )
            else:
                st.error(f"PDF 생성 실패: {err}")

    # 대화 지우기
    if st.button("🧹 대화 지우기", use_container_width=True):
        st.session_state.messages = []
        st.session_state.last_answer = ""
        st.experimental_rerun()

# ──────────────────────────────────────────────────────────────────────────────
# 본문: 대화 영역
# ──────────────────────────────────────────────────────────────────────────────
st.title("보험 문서 RAG")

# 기존 대화 표시
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# 입력창
prompt = st.chat_input(f"[{insurer}] 질문을 입력하세요…")
if prompt:
    # 사용자 메시지 추가/표시
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # 모델 호출
    with st.chat_message("assistant"):
        with st.spinner("답변 생성 중…"):
            answer_text, raw = ask_backend(
                api_base=api_base,
                query=prompt,
                insurer=insurer,
                top_k=top_k,
                temperature=temperature,
                max_tokens=max_tokens,
                history=st.session_state.messages[:-1],  # 마지막 user 제외한 히스토리
            )
            st.markdown(answer_text)

    # 상태 저장
    st.session_state.messages.append({"role": "assistant", "content": answer_text})
    st.session_state.last_answer = answer_text


# ──────────────────────────────────────────────────────────────────────────────
# 함수들
# ──────────────────────────────────────────────────────────────────────────────
def ask_backend(
    api_base: str,
    query: str,
    insurer: str,
    top_k: int,
    temperature: float,
    max_tokens: int,
    history: List[Dict[str, str]],
) -> tuple[str, Any]:
    """
    백엔드 엔드포인트가 프로젝트마다 다를 수 있어
    여러 후보 경로를 순차 시도한다.
    반환: (answer_text, raw_json_or_text)
    """
    payload = {
        "query": query,
        "insurer": insurer,
        "top_k": top_k,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "history": history,  # [{role, content}...]
    }

    # 가능한 엔드포인트 후보들
    candidates = [
        "/ask",
        "/chat",
        "/query",
        "/rag/ask",
        "/answer",
        "/v1/ask",
    ]

    last_error = None
    for path in candidates:
        url = f"{api_base.rstrip('/')}{path}"
        try:
            res = requests.post(url, json=payload, timeout=60)
            if res.status_code == 404:
                continue
            res.raise_for_status()
            # JSON 혹은 텍스트 응답 유연 처리
            try:
                data = res.json()
            except ValueError:
                text = res.text.strip()
                return (text or "(빈 응답)"), text

            # 흔한 키 패턴 처리
            for key in ["answer", "content", "text"]:
                if key in data and isinstance(data[key], str):
                    return data[key], data

            # nested: {"output": {"text": "..."}}
            if isinstance(data, dict) and "output" in data:
                out = data["output"]
                if isinstance(out, dict):
                    for key in ["text", "answer", "content"]:
                        if key in out and isinstance(out[key], str):
                            return out[key], data

            # 최후 수단: 전체 문자열화
            return json.dumps(data, ensure_ascii=False, indent=2), data

        except requests.RequestException as e:
            last_error = e
            continue

    if last_error:
        return f"(요청 실패) {last_error}", None
    return "(요청 실패) 사용 가능한 API 경로를 찾지 못했습니다.", None


def try_export_pdf_via_backend(api_base: str, title: str, content: str) -> tuple[bool, bytes | None, str | None]:
    """
    백엔드의 /export/pdf 엔드포인트로 PDF를 생성해 받아온다.
    """
    url = f"{api_base.rstrip('/')}/export/pdf"
    try:
        res = requests.post(url, json={"title": title, "content": content}, timeout=60)
        if res.status_code == 404:
            return False, None, "백엔드에 /export/pdf 엔드포인트가 없습니다(404)."
        res.raise_for_status()
        return True, res.content, None
    except requests.RequestException as e:
        return False, None, str(e)


def try_export_pdf_locally(title: str, content: str) -> tuple[bool, bytes | None, str | None]:
    """
    백엔드가 없을 때 프론트(스트림릿)에서 PDF를 만들어 반환.
    reportlab이 필요하다.
    """
    try:
        from reportlab.pdfgen import canvas
        from reportlab.lib.pagesizes import A4
        from textwrap import wrap
    except Exception as e:
        return False, None, f"로컬 PDF 생성 실패(의존성 필요): {e}. `pip install reportlab` 필요."

    buf = BytesIO()
    try:
        c = canvas.Canvas(buf, pagesize=A4)
        w, h = A4
        x, y = 40, h - 50
        c.setTitle(title)
        c.setFont("Helvetica-Bold", 14)
        c.drawString(x, y, title or "문서")
        y -= 24
        c.setFont("Helvetica", 11)
        for line in (content or "(내용 없음)").splitlines():
            for seg in wrap(line, 90):
                c.drawString(x, y, seg)
                y -= 16
                if y < 40:
                    c.showPage()
                    c.setFont("Helvetica", 11)
                    y = h - 50
        c.save()
        buf.seek(0)
        return True, buf.getvalue(), None
    except Exception as e:
        return False, None, f"로컬 PDF 생성 실패: {e}"
