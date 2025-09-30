#data/curated/{insurer}/{file}.jsonl을 읽어서 PostgreSQL 의 policy_form, clause, coverage, exclusion, rider 테이블에 넣음
# insurance_ai/etl/load_db.py
from __future__ import annotations
import argparse, json, hashlib
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable

from sqlalchemy import (
    create_engine, MetaData, Table, Column, Integer, BigInteger, String, Text,
    Date, ForeignKey, JSON, UniqueConstraint, Index
)
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
import os
from tqdm import tqdm

# ---------- Config ----------
load_dotenv()  # loads DATABASE_URL if present
DEFAULT_DSN = os.getenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/insurance_ai")

CURATED_DIR = Path("data/curated")

# ---------- DB Schema (SQLAlchemy Core) ----------
metadata = MetaData()

policy_form = Table(
    "policy_form", metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("insurer", String(64), nullable=False),
    Column("product_name", String(128), nullable=False),
    Column("version_label", String(64)),
    Column("effective_from", Date, nullable=False),
    Column("effective_to", Date, nullable=True),
    Column("source_url", Text, nullable=False, default="local"),
    Column("content_hash", String(64), nullable=False, unique=True),
    UniqueConstraint("insurer", "product_name", "version_label", name="uq_policy_version"),
)

clause = Table(
    "clause", metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("policy_form_id", BigInteger, ForeignKey("policy_form.id"), nullable=False),
    Column("clause_no", String(32)),
    Column("section", String(32)),  # coverage|exclusion|rider|other
    Column("title", Text),
    Column("body_text", Text, nullable=False),
    Index("idx_clause_policy", "policy_form_id")
)

coverage = Table(
    "coverage", metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("clause_id", BigInteger, ForeignKey("clause.id"), nullable=False),
    Column("coverage_name", String(128)),
    Column("condition_json", JSON),
    Column("payout_json", JSON),
    Column("notes", Text),
    Index("idx_coverage_name", "coverage_name")
)

exclusion = Table(
    "exclusion", metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("clause_id", BigInteger, ForeignKey("clause.id"), nullable=False),
    Column("rule_json", JSON),
    Column("notes", Text)
)

rider = Table(
    "rider", metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("clause_id", BigInteger, ForeignKey("clause.id"), nullable=False),
    Column("rider_name", String(128)),
    Column("detail_json", JSON)
)

# ---------- Helpers ----------
@dataclass
class PolicyKey:
    insurer: str
    product_name: str
    version_label: str

def parse_policy_key(from_path: Path) -> PolicyKey:
    """
    data/curated/{insurer}/{file}.jsonl
    파일명에서 제품/버전 추출: 예) '현대암보험2504.jsonl' -> product_name='현대암보험', version_label='2504'
    규칙은 MVP용 간단 규칙. 필요시 개선.
    """
    insurer = from_path.parents[0].name
    stem = from_path.stem  # 파일명(확장자 제외)
    # 숫자 연속을 버전으로 가정
    import re
    m = re.search(r"(\d{3,6})$", stem)
    if m:
        version_label = m.group(1)
        product_name = stem[:m.start()]
    else:
        version_label = "v1"
        product_name = stem
    return PolicyKey(insurer=insurer, product_name=product_name or "product", version_label=version_label)

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()

def iter_jsonl(path: Path) -> Iterable[dict]:
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)

def classify_defaults(item: dict) -> tuple[str, str, dict, dict]:
    """
    coverage_name, notes, condition_json, payout_json 기본값 생성
    normalize.py에서 아직 세부 구조화를 안 한 상태라도 안전하게 넣기 위한 기본 처리.
    """
    body = item.get("body", "")
    title = item.get("title") or ""
    coverage_name = title.strip() or item.get("coverage_name") or None
    notes = None

    # 매우 러프한 규칙 (MVP)
    condition_json = item.get("condition_json") or {}
    payout_json = item.get("payout_json") or {}

    return coverage_name, notes, condition_json, payout_json

# ---------- Loaders ----------
def get_or_create_policy_form(engine: Engine, pkey: PolicyKey, content_hash: str, source_url: str = "local") -> int:
    with engine.begin() as conn:
        # content_hash로 먼저 조회 (동일 파일 재적재 방지)
        r = conn.execute(policy_form.select().where(policy_form.c.content_hash == content_hash)).fetchone()
        if r:
            return r.id

        # 동일 (insurer, product, version) 존재하면 그대로 사용 (content_hash가 다르더라도)
        r2 = conn.execute(
            policy_form.select().where(
                (policy_form.c.insurer == pkey.insurer) &
                (policy_form.c.product_name == pkey.product_name) &
                (policy_form.c.version_label == pkey.version_label)
            )
        ).fetchone()
        if r2:
            return r2.id

        ins = policy_form.insert().values(
            insurer=pkey.insurer,
            product_name=pkey.product_name,
            version_label=pkey.version_label,
            effective_from=date.today(),
            effective_to=None,
            source_url=source_url,
            content_hash=content_hash,
        ).returning(policy_form.c.id)
        new_id = conn.execute(ins).scalar_one()
        return new_id

def insert_clause_and_children(engine: Engine, policy_form_id: int, items: Iterable[dict]):
    """
    items: normalize.py 결과 jsonl의 한 줄(dict)
      필요한 키:
        - clause_no (선택)
        - type: coverage|exclusion|rider|other
        - title (선택)
        - body (필수)
        - coverage_name/condition_json/payout_json (선택)
        - rule_json (exclusion일 때 선택)
        - rider_name/detail_json (rider일 때 선택)
    """
    with engine.begin() as conn:
        for it in items:
            body = it.get("body") or ""
            if not body.strip():
                continue

            c_ins = clause.insert().values(
                policy_form_id=policy_form_id,
                clause_no=it.get("clause_no"),
                section=it.get("type") or "other",
                title=it.get("title"),
                body_text=body
            ).returning(clause.c.id)
            clause_id = conn.execute(c_ins).scalar_one()

            ctype = (it.get("type") or "other").lower()

            if ctype == "coverage":
                cov_name, notes, cond_json, pay_json = classify_defaults(it)
                conn.execute(coverage.insert().values(
                    clause_id=clause_id,
                    coverage_name=cov_name,
                    condition_json=cond_json,
                    payout_json=pay_json,
                    notes=notes
                ))

            elif ctype == "exclusion":
                conn.execute(exclusion.insert().values(
                    clause_id=clause_id,
                    rule_json=it.get("rule_json") or {},
                    notes=it.get("notes")
                ))

            elif ctype == "rider":
                conn.execute(rider.insert().values(
                    clause_id=clause_id,
                    rider_name=it.get("rider_name"),
                    detail_json=it.get("detail_json") or {}
                ))
            else:
                # other는 clause만 저장
                pass

# ---------- Main ----------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dsn", default=DEFAULT_DSN, help="PostgreSQL DSN, e.g., postgresql://user:pass@localhost:5432/insurance_ai")
    ap.add_argument("--curated", default=str(CURATED_DIR), help="Curated JSONL root directory")
    args = ap.parse_args()

    engine = create_engine(args.dsn, future=True)
    metadata.create_all(engine)  # 테이블 없으면 생성

    curated_root = Path(args.curated)
    jsonl_files = sorted(curated_root.rglob("*.jsonl"))

    if not jsonl_files:
        print(f"[WARN] No JSONL files under {curated_root}")
        return

    for jf in tqdm(jsonl_files, desc="Loading JSONL"):
        try:
            # 정책 키 파싱
            pkey = parse_policy_key(jf)
            # 동일 정책 판단을 위한 content hash (파일 자체 해시)
            c_hash = sha256_file(jf)
            policy_form_id = get_or_create_policy_form(engine, pkey, c_hash, source_url="local-jsonl")

            # 조항 & 하위 테이블 삽입
            items = list(iter_jsonl(jf))
            insert_clause_and_children(engine, policy_form_id, items)

        except IntegrityError as e:
            print(f"[ERROR] IntegrityError on {jf}: {e}")
        except Exception as e:
            print(f"[ERROR] {jf}: {e}")

    print("✅ Load finished.")

if __name__ == "__main__":
    main()
