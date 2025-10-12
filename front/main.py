# front/main.py
# -----------------------------------------------------------------------------
# 보험 문서 RAG 플랫폼 (Streamlit)
# - Q&A: /qa/ask
# - 문서 검색: /qa/search
# - Chat: /chat/log (대화 저장) + /qa/answer_pdf (PDF 생성)
# -----------------------------------------------------------------------------

import os
import requests
import streamlit as st

API_BASE = st.secrets.get("API_BASE") or os.getenv("API_BASE", "http://localhost:8000")
st.set_page_config(page_title="보험 문서 RAG 플랫폼", layout="wide")
st.title("보험 문서 RAG 플랫폼")

DEFAULT_TIMEOUT = (5, 60)  # (connect, read)
INSURERS = ["", "DB손해", "현대해상", "삼성화재"]

tab1, tab2, tab3 = st.tabs(["Q&A", "문서 검색", "Chat"])

# =============================================================================
# Tab 1: Q&A (/qa/ask)
# =============================================================================
with tab1:
    left, right = st.columns([3, 1])
    with left:
        q = st.text_input("질문을 입력하세요", placeholder="예) 실손 청구에 필요한 서류는?")
    with right:
        policy = st.selectbox("보험사(선택)", INSURERS, index=0)
        top_k = st.slider("Top-K", 1, 10, 5)

    if st.button("질문하기", use_container_width=True, disabled=not q):
        try:
            payload = {"q": q, "top_k": int(top_k)}
            if policy:
                payload["policy_type"] = policy
            resp = requests.post(f"{API_BASE}/qa/ask", json=payload, timeout=DEFAULT_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()

            st.markdown("### 답변")
            st.write(data.get("answer", ""))

            sources = data.get("sources") or []
            if sources:
                st.markdown("### 출처 (Top-K)")
                for s in sources:
                    title = s.get("clause_title") or "문서"
                    score = s.get("score")
                    score_txt = f" · score={score:.4f}" if isinstance(score, (int, float)) else ""
                    st.markdown(f"- **{title}**{score_txt}")
                    with st.expander("내용 보기", expanded=False):
                        st.write((s.get("content") or "")[:1500])

        except requests.exceptions.ConnectionError:
            st.error(f"백엔드 연결 실패: {API_BASE} 가 실행 중인지 확인하세요.")
        except requests.exceptions.Timeout:
            st.error("요청이 시간 초과되었습니다. 잠시 후 다시 시도해주세요.")
        except Exception as e:
            st.error(f"요청 실패: {e}")

# =============================================================================
# Tab 2: 문서 검색 (/qa/search)
# =============================================================================
with tab2:
    left, right = st.columns([3, 1])
    with left:
        q_search = st.text_input("검색어", key="search", placeholder="예) 입원비 지급 한도")
    with right:
        policy2 = st.selectbox("보험사(선택)", INSURERS, index=0, key="policy2")
        top_k2 = st.slider("Top-K(검색)", 1, 20, 5, key="topk2")

    if st.button("검색하기", use_container_width=True, disabled=not q_search):
        try:
            payload = {"q": q_search, "top_k": int(top_k2)}
            if policy2:
                payload["policy_type"] = policy2

            resp = requests.post(f"{API_BASE}/qa/search", json=payload, timeout=DEFAULT_TIMEOUT)
            resp.raise_for_status()
            items = resp.json()

            if not items:
                st.info("검색 결과가 없습니다. (임베딩/DB 데이터를 확인하세요)")
            else:
                st.markdown("### 검색 결과")
                for it in items:
                    title = it.get("clause_title") or "문서"
                    score = it.get("score")
                    snippet = it.get("content_snippet") or ""
                    score_txt = f" | score={score:.4f}" if isinstance(score, (int, float)) else ""
                    st.markdown(f"- **{title}**{score_txt}")
                    st.write(snippet)

        except requests.exceptions.ConnectionError:
            st.error(f"백엔드 연결 실패: {API_BASE} 가 실행 중인지 확인하세요.")
        except requests.exceptions.Timeout:
            st.error("요청이 시간 초과되었습니다. 잠시 후 다시 시도해주세요.")
        except Exception as e:
            st.error(f"검색 실패: {e}")

# =============================================================================
# Tab 3: Chat  (대화 저장 + PDF 생성)
# =============================================================================
with tab3:
    st.subheader("대화형 Q&A (RAG + PDF)")

    if "conv_id" not in st.session_state:
        st.session_state.conv_id = None
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []

    # 입력영역
    user_in = st.text_input("메시지 입력", key="chat_input", placeholder="무엇이든 질문하세요")
    colA, colB, colC = st.columns([1, 1, 1])
    with colA:
        policy3 = st.selectbox("보험사(선택)", INSURERS, index=0, key="policy3")
    with colB:
        top_k3 = st.slider("Top-K", 1, 10, 3, key="topk3")
    with colC:
        st.caption(" ")  # spacing
        send_clicked = st.button("보내기", use_container_width=True, disabled=not user_in)

    # 1) 대화 저장
    if send_clicked:
        try:
            payload = {
                "conv_id": st.session_state.conv_id,
                "message": {"role": "user", "content": user_in},
            }
            r = requests.post(f"{API_BASE}/chat/log", json=payload, timeout=(5, 30))
            r.raise_for_status()
            st.session_state.conv_id = r.json()["conv_id"]
            st.session_state.chat_history.append({"role": "user", "content": user_in})
            st.success("메시지 저장됨")
        except Exception as e:
            st.error(f"대화 저장 실패: {e}")

    # 2) PDF 생성 버튼
    st.divider()
    pdf_clicked = st.button(
        "근거 기반 답변 PDF 받기",
        use_container_width=True,
        disabled=not (st.session_state.conv_id or user_in),
    )
    if pdf_clicked:
        try:
            # conv_id가 있으면 그걸 우선 사용. 없으면 현재 입력을 단일 질문으로 보냄.
            payload = {
                "conv_id": st.session_state.conv_id,
                "question": None if st.session_state.conv_id else (user_in or None),
                "policy_type": policy3 or None,
                "top_k": int(top_k3),
                "max_tokens": 800,
            }
            r = requests.post(f"{API_BASE}/qa/answer_pdf", json=payload, timeout=(10, 120))
            r.raise_for_status()
            out = r.json()
            st.success("PDF 생성 완료!")
            st.markdown("**요약 답변**")
            st.write(out.get("answer", ""))
            st.markdown(f"[PDF 다운로드]({API_BASE}{out['pdf_url']})")
        except Exception as e:
            st.error(f"PDF 생성 실패: {e}")

    # 최근 대화 표시
    st.markdown("### 최근 대화")
    for m in st.session_state.chat_history[-12:]:
        role = "🧑" if m["role"] == "user" else "🤖"
        st.markdown(f"**{role} {m['role']}**: {m['content']}")

st.caption(f"API_BASE = {API_BASE}")
