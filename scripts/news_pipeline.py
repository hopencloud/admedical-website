"""
뉴스 게시판 일일 자동 발행 — 전체 오케스트레이터.

흐름:
    킬스위치 확인 → 뉴스 수집 → 주제 선정 → 초고 → 자체 검수
      → 이미지(일러스트 2 + 실데이터 도표 1) → 정적 HTML 렌더 → 인덱스/사이트맵/RSS 갱신
      → Supabase 이력 기록

GitHub Actions 에서 매일 실행되며, 커밋·푸시는 워크플로우가 담당한다.

실행:
    python scripts/news_pipeline.py                # 정상 발행
    python scripts/news_pipeline.py --dry-run      # 파일/이미지 생성 없이 원고까지만
    python scripts/news_pipeline.py --force        # 오늘 이미 발행했어도 한 편 더
    python scripts/news_pipeline.py --count 2      # 2편 발행
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent))

import news_images                                    # noqa: E402
import news_render                                    # noqa: E402
import news_sources                                   # noqa: E402
import news_writer                                    # noqa: E402
from news_feed import write_rss                       # noqa: E402

KST = timezone(timedelta(hours=9))
ROOT = Path(__file__).parent.parent
WEB = ROOT / "website"
STATS_JSON = WEB / "assets" / "data" / "statistics.json"
TOP_JSON = WEB / "assets" / "data" / "this_week_top20.json"
IMG_DIR = WEB / "assets" / "news"

load_dotenv(ROOT / ".env")


# ---------- 보조 ----------

def log(msg: str) -> None:
    print(f"[news] {msg}", flush=True)


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def get_supabase():
    """없어도 파이프라인은 돈다. 킬스위치/이력 기록만 생략된다."""
    url, key = os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_KEY")
    if not url or not key:
        return None
    try:
        from supabase import create_client
        return create_client(url, key)
    except Exception as exc:
        log(f"Supabase 연결 실패 (계속 진행): {exc}")
        return None


def check_killswitch(client) -> tuple[bool, int]:
    """(발행해도 되는가, 하루 발행 수). Supabase가 없으면 기본값으로 진행."""
    if client is None:
        return True, 1
    try:
        res = client.table("news_settings").select("*").eq("id", 1).limit(1).execute()
        if not res.data:
            return True, 1
        row = res.data[0]
        return bool(row.get("auto_publish", True)), int(row.get("daily_count", 1) or 1)
    except Exception as exc:
        log(f"설정 조회 실패 (기본값으로 진행): {exc}")
        return True, 1


def record_post(client, post: dict, model: str) -> None:
    if client is None:
        return
    try:
        client.table("news_posts").upsert({
            "slug": post["slug"],
            "title": post["title"],
            "summary": post.get("summary", ""),
            "published_date": post["date"],
            "topic_key": post.get("topic_key", ""),
            "source_links": post.get("sources", []),
            "tags": post.get("tags", []),
            "cover_image": post.get("cover"),
            "status": "published",
            "model_used": model,
        }).execute()
    except Exception as exc:
        log(f"Supabase 이력 기록 실패 (파일은 정상 생성됨): {exc}")


# ---------- 진행상황 ----------
#
# /admin 이 폴링해서 "지금 몇 건 중 몇 건, 어느 단계인지"를 보여준다.
# Supabase 가 없거나 실패해도 파이프라인은 그대로 진행한다.

_run_id: int | None = None


def start_run(client, total: int) -> None:
    global _run_id
    _run_id = None
    if client is None:
        return
    try:
        res = client.table("news_runs").insert({
            "status": "running", "total": total, "done": 0,
            "stage": "시작", "detail": "",
        }).execute()
        _run_id = res.data[0]["id"] if res.data else None
    except Exception as exc:
        log(f"진행상황 기록 불가 (계속 진행): {exc}")


def progress(client, stage: str = "", detail: str = "",
             done: int | None = None, title: str | None = None) -> None:
    log(f"· {stage}{(' — ' + detail) if detail else ''}")
    if client is None or _run_id is None:
        return
    patch = {"stage": stage, "detail": detail[:200], "updated_at": now_iso()}
    if done is not None:
        patch["done"] = done
    if title is not None:
        patch["current_title"] = title[:200]
    try:
        client.table("news_runs").update(patch).eq("id", _run_id).execute()
    except Exception:
        pass


def finish_run(client, status: str, note: str = "") -> None:
    if client is None or _run_id is None:
        return
    try:
        client.table("news_runs").update({
            "status": status, "stage": "완료" if status == "done" else "중단",
            "detail": note[:200], "finished_at": now_iso(), "updated_at": now_iso(),
        }).eq("id", _run_id).execute()
    except Exception:
        pass


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# 최근 몇 편과 주제가 겹치면 안 되는가. /admin 에서 바꿀 일이 없어 상수로 둔다.
DEDUP_WINDOW = int(os.getenv("NEWS_DEDUP_WINDOW", "10"))
SIMILARITY_LIMIT = float(os.getenv("NEWS_SIMILARITY_LIMIT", "0.28"))


def _bigrams(text: str) -> set[str]:
    t = re.sub(r"[^0-9a-zA-Z가-힣]", "", text)
    return {t[i:i + 2] for i in range(len(t) - 1)} or {t}


def similarity(a: str, b: str) -> float:
    """제목 두 개의 글자 바이그램 자카드 유사도."""
    x, y = _bigrams(a), _bigrams(b)
    return len(x & y) / len(x | y) if x | y else 0.0


def used_source_links(posts: list[dict]) -> set[str]:
    """최근 발행분이 근거로 쓴 기사 링크. 같은 기사를 두 번 우려먹지 않기 위함."""
    links: set[str] = set()
    for post in posts[:DEDUP_WINDOW]:
        for src in post.get("sources") or []:
            if src.get("link"):
                links.add(src["link"])
    return links


def duplicate_of(title: str, posts: list[dict]) -> str | None:
    """최근 발행분 중 주제가 겹치는 글의 제목. 없으면 None."""
    for post in posts[:DEDUP_WINDOW]:
        if similarity(title, post.get("title", "")) >= SIMILARITY_LIMIT:
            return post.get("title", "")
    return None


def sort_key(post: dict) -> str:
    """최신 글이 먼저. 발행 시각이 없는 옛 글은 날짜 자정으로 본다."""
    return post.get("published_at") or f'{post["date"]}T00:00:00+09:00'


def top_expressions() -> list[str]:
    data = load_json(TOP_JSON, {})
    items = data.get("top20") or data.get("items") or []
    out = []
    for it in items:
        if isinstance(it, str):
            out.append(it)
        elif isinstance(it, dict):
            val = it.get("expression") or it.get("text") or it.get("phrase")
            if val:
                out.append(val)
    return out


# ---------- 본체 ----------

def publish_one(client, posts: list[dict], candidates: list, stats: dict,
                index: int = 0, dry_run: bool = False,
                tried_links: set[str] | None = None) -> dict | None:
    """한 편 생성. 성공하면 새 post dict, 발행할 게 없으면 None."""
    published_titles = [p["title"] for p in posts]
    published_keys = {p.get("topic_key", "") for p in posts}

    progress(client, "주제 선정", "수집된 기사에서 오늘 다룰 주제 고르는 중", done=index)

    # 최근 발행분이 이미 근거로 쓴 기사는 후보에서 아예 뺀다.
    # AI 에게 "겹치지 마라"고 부탁하는 것만으로는 같은 주제가 반복해서 나왔다.
    # 이번 실행에서 이미 손댄 기사도 뺀다. 안 그러면 한 편이 반려됐을 때
    # 다음 시도가 똑같은 주제를 다시 골라 같은 이유로 또 반려된다.
    used = used_source_links(posts) | (tried_links or set())
    pool = [c for c in candidates if c.link not in used]
    if len(pool) < len(candidates):
        log(f"이미 다룬 기사 {len(candidates) - len(pool)}건을 후보에서 제외")

    topic = None
    for attempt in range(3):
        picked = news_writer.select_topic(pool, published_titles)
        if not picked:
            break
        if tried_links is not None:
            tried_links |= {s.link for s in picked["sources"]}
        dup = duplicate_of(picked["topic"], posts)
        if not dup:
            topic = picked
            break
        log(f"주제 중복 — '{dup}' 와 유사. 다시 고릅니다 ({attempt + 1}/3)")
        drop = {s.link for s in picked["sources"]}
        pool = [c for c in pool if c.link not in drop]

    if not topic:
        log("최근 발행분과 겹치지 않는 주제가 없습니다. 발행하지 않습니다.")
        return None

    log(f"주제: {topic['topic']}")
    log(f"관점: {topic.get('angle', '')}")

    progress(client, "원고 작성", topic["topic"][:120], title=topic["topic"])
    recent_types = [x for x in (q.get("infographic_type") for q in posts[:5]) if x]
    draft = news_writer.write_article(topic, stats, top_expressions(), recent_types)
    log(f"초고 작성 완료: {draft.get('title', '')} ({news_writer.word_count(draft)}자)")

    progress(client, "분량 보강", f'{draft.get("title", "")}', title=draft.get("title", ""))
    before = news_writer.word_count(draft)
    draft = news_writer.expand_article(draft, topic)
    if news_writer.word_count(draft) != before:
        log(f"분량 보강: {before}자 → {news_writer.word_count(draft)}자")

    progress(client, "자체 검수", "근거 대조 및 표현 교정 중")
    verdict, article, issues = news_writer.review_article(draft, topic, stats)
    log(f"자체 검수: {verdict}")
    for issue in issues[:6]:
        log(f"   · {issue}")

    if verdict == "reject":
        log("검수에서 반려되었습니다. 발행하지 않습니다.")
        return None

    # 근거에 없는 숫자는 파이썬이 직접 잡는다 (AI 자기검수만으로는 새는 경우가 있음)
    progress(client, "수치 검증", "본문 숫자를 근거 자료와 대조 중")
    bad_before = news_writer.unsupported_numbers(article, topic, stats)
    if bad_before:
        log(f"근거 미확인 수치 {len(bad_before)}개 발견: {', '.join(bad_before[:8])}")
        article, bad_after = news_writer.strip_unsupported_numbers(article, topic, stats)
        if bad_after:
            log(f"정정 후에도 남음: {', '.join(bad_after[:8])} — 발행하지 않습니다.")
            return None
        log("수치 정정 완료")

    # 검수·수치 정정을 거치며 문장이 잘려 분량이 줄어드는 경우가 있다.
    # 짧다고 바로 버리지 말고 근거 범위 안에서 한 번 더 늘려본다.
    final_chars = news_writer.word_count(article)
    if final_chars < 1000:
        progress(client, "분량 재보강", f"{final_chars}자 → 보강 중")
        article = news_writer.expand_article(article, topic)
        # 늘리는 과정에서 새 숫자가 들어갔을 수 있으니 다시 대조한다
        article, still_bad = news_writer.strip_unsupported_numbers(article, topic, stats)
        if still_bad:
            log(f"재보강 후 미확인 수치 잔존: {', '.join(still_bad[:6])} — 발행하지 않습니다.")
            return None
        log(f"분량 재보강: {final_chars}자 → {news_writer.word_count(article)}자")
        final_chars = news_writer.word_count(article)

    if final_chars < 800:
        log(f"본문이 너무 짧습니다({final_chars}자). 발행하지 않습니다.")
        return None
    log(f"최종 분량: {final_chars}자")

    topic_key = news_writer.article_topic_key(article)
    if topic_key and topic_key in published_keys:
        log("이미 같은 주제를 발행했습니다. 건너뜁니다.")
        return None

    # 제목이 겹치면 기사를 버리지 말고 제목만 다시 짓는다.
    # 주제 단계에서 이미 중복 검사를 통과한 기사다. 좁은 분야라 제목만 뻔하게
    # 나오는 경우가 잦은데, 그때마다 버리면 한 주에 한 편도 못 나간다.
    dup = duplicate_of(article.get("title", ""), posts)
    if dup:
        log(f"최종 제목이 '{dup}' 와 겹칩니다. 제목을 다시 짓습니다.")
        progress(client, "제목 재작성", f"'{dup}' 와 중복")
        article = news_writer.retitle_article(article, dup)
        dup = duplicate_of(article.get("title", ""), posts)
        if dup:
            log(f"다시 지은 제목도 '{dup}' 와 겹칩니다. 발행하지 않습니다.")
            return None
        log(f"새 제목: {article.get('title', '')}")

    now = datetime.now(KST)
    slug = news_writer.make_slug(article, now)
    if any(p["slug"] == slug for p in posts):
        slug = f"{slug}-2"

    if dry_run:
        print(json.dumps(article, ensure_ascii=False, indent=2))
        return None

    # ----- 시각자료 -----
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    # 기사 1편당 시각자료 3종을 기본으로 한다: 사진 1 + 일러스트 1 + 도식 1
    images = article.get("images") or []

    def _spec(*roles):
        return next((i for i in images if i.get("role") in roles), {})

    photo_spec = _spec("photo", "cover")
    illust_spec = _spec("illustration", "inline")

    # 사진과 일러스트를 동시에 만든다. 순차로 하면 편당 1분 이상 더 걸려
    # 5편이면 GitHub Actions 제한 시간을 넘긴다.
    progress(client, stage="이미지 제작", detail="사진·일러스트 동시 생성 중")
    cover_rel = inline_rel = thumb_rel = None

    cover_file = IMG_DIR / news_images.safe_filename(slug, "photo", "jpg")
    inline_file = IMG_DIR / news_images.safe_filename(slug, "illust")

    with ThreadPoolExecutor(max_workers=2) as pool:
        photo_job = pool.submit(
            news_images.generate_image,
            photo_spec.get("concept") or topic["topic"], cover_file,
            photo_spec.get("detail", ""), True, "photo")
        illust_job = pool.submit(
            news_images.generate_image,
            illust_spec.get("concept") or topic["topic"], inline_file,
            illust_spec.get("detail", ""), False, "illustration")

        if photo_job.result():
            cover_rel = f"/assets/news/{cover_file.name}"
        if illust_job.result():
            inline_rel = f"/assets/news/{inline_file.name}"

    # ③ 도식 — 기사 성격에 맞는 유형으로. 실데이터 추이는 stat_trend 일 때만.
    progress(client, stage="도표 생성", detail=(article.get("infographic") or {}).get("type", ""))
    infographic_svg = news_images.render_infographic(
        article.get("infographic") or {}, stats.get("chart_30d", []))

    if not infographic_svg:
        # AI 도식 스펙이 부실하면 체크리스트 카드로 대체한다. 도식은 반드시 하나 있어야 한다.
        infographic_svg = news_images.render_checklist(
            {"title": "실무 체크리스트", "items": article.get("checklist", [])})
    extra_svg = ""

    if not (cover_rel and inline_rel and infographic_svg):
        log(f"시각자료 부족 (사진={bool(cover_rel)} 일러스트={bool(inline_rel)} "
            f"도식={bool(infographic_svg)}) — 발행하지 않습니다.")
        return None

    # 썸네일 — 목록·메인·SNS 공유에 쓰는 일관 디자인 카드
    progress(client, stage="썸네일 생성", detail=slug)
    thumb_file = IMG_DIR / news_images.safe_filename(slug, "thumb", "jpg")
    if news_images.render_thumbnail(
            article.get("title", ""), f"{now:%Y년 %-m월 %-d일}", thumb_file,
            cover_file if cover_rel else None):
        thumb_rel = f"/assets/news/{thumb_file.name}"

    # ----- HTML -----
    progress(client, stage="페이지 생성", detail=slug)
    meta = {
        "slug": slug,
        "date": f"{now:%Y-%m-%d}",
        "cover": cover_rel,
        "inline_image": inline_rel,
        "thumb": thumb_rel,
        "sources": [
            {"title": s.title, "source": s.source, "link": s.link,
             "date": f"{s.published:%Y-%m-%d}"}
            for s in topic["sources"]
        ],
    }

    html_out = news_render.render_post(article, meta, infographic_svg, extra_svg)
    news_render.NEWS_DIR.mkdir(parents=True, exist_ok=True)
    (news_render.NEWS_DIR / f"{slug}.html").write_text(html_out, encoding="utf-8")
    log(f"기사 생성: website/news/{slug}.html")

    return {
        "slug": slug,
        "title": article.get("title", ""),
        "summary": article.get("summary", ""),
        "date": meta["date"],
        # 같은 날 여러 편을 내면 날짜만으로는 순서가 정해지지 않는다. 시각까지 남긴다.
        "published_at": now.isoformat(),
        "cover": cover_rel,
        "thumb": thumb_rel,
        "infographic_type": (article.get("infographic") or {}).get("type", ""),
        "tags": article.get("tags", [])[:6],
        "topic_key": topic_key,
        "sources": [{"title": s["title"], "source": s["source"], "link": s["link"]}
                    for s in meta["sources"]],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="뉴스 게시판 일일 자동 발행")
    parser.add_argument("--dry-run", action="store_true", help="파일·이미지 생성 없이 원고까지만")
    parser.add_argument("--force", action="store_true", help="오늘 이미 발행했어도 실행")
    parser.add_argument("--count", type=int, default=0, help="발행할 글 수 (기본: 설정값)")
    parser.add_argument("--no-web-search", action="store_true", help="OpenAI 웹검색 생략")
    args = parser.parse_args()

    client = get_supabase()
    enabled, daily_count = check_killswitch(client)
    if not enabled:
        log("자동 발행이 꺼져 있습니다 (news_settings.auto_publish = false). 종료합니다.")
        return 0

    count = args.count or daily_count
    posts = news_render.load_index()
    today = f"{datetime.now(KST):%Y-%m-%d}"

    if not args.force and any(p["date"] == today for p in posts):
        log(f"오늘({today}) 이미 발행된 글이 있습니다. --force 로 강제 실행할 수 있습니다.")
        return 0

    stats = load_json(STATS_JSON, {})
    log(f"통계 로드: 어제 {stats.get('yesterday', {}).get('count', '-')}건 / "
        f"누적 {stats.get('total', {}).get('count', '-')}건")

    start_run(client, total=max(1, count))
    progress(client, "뉴스 수집", "의료 전문지 RSS · 정부 보도자료 수집 중")
    candidates = news_sources.collect(
        hours=int(os.getenv("NEWS_LOOKBACK_HOURS", "168")),   # 주 1회 발행이라 지난 7일
        use_web_search=not args.no_web_search,
    )
    log(f"후보 {len(candidates)}건 수집")

    if not candidates:
        log("수집된 기사가 없습니다. 종료합니다.")
        finish_run(client, "skipped", "수집된 기사 없음")
        return 0

    # 한 편이 반려돼도 다음 편을 시도한다.
    #
    # 예전에는 반려되면 곧바로 break 라서, 첫 편이 걸리면 나머지 4편도 시도조차
    # 못 하고 그 주 발행이 통째로 0편이 됐다 (2026-08-10). 목표 편수를 채울 때까지
    # 최대 count*3 번 시도하되, 연속 3번 반려되면 그날은 소재가 없다고 보고 멈춘다.
    created: list[dict] = []
    target = max(1, count)
    max_attempts = target * 3
    misses = 0
    tried_links: set[str] = set()
    for attempt in range(max_attempts):
        if len(created) >= target:
            break
        if attempt:
            log(f"--- {attempt + 1}번째 시도 (발행 {len(created)}/{target}) ---")
        try:
            post = publish_one(client, posts + created, candidates, stats,
                               index=len(created), dry_run=args.dry_run,
                               tried_links=tried_links)
        except Exception as exc:
            log("발행 중 오류 — 이번 편은 건너뜁니다.")
            traceback.print_exc()
            misses += 1
            if misses >= 3:
                finish_run(client, "failed", f"{type(exc).__name__}: {exc}")
                break
            continue
        if not post:
            misses += 1
            if misses >= 3:
                log("연속 3번 반려됐습니다. 오늘은 여기서 멈춥니다.")
                break
            continue
        misses = 0
        created.append(post)
        record_post(client, post, news_writer.WRITER_MODEL)

        # 편마다 목록·사이트맵·RSS 를 갱신해 둔다. 뒤쪽 편에서 실패하거나
        # 실행이 중단돼도 앞서 만든 글은 온전한 상태로 남는다.
        snapshot = sorted(created + posts, key=sort_key, reverse=True)
        news_render.write_post_files(snapshot)
        write_rss(snapshot)

    if not created:
        log("새로 발행된 글이 없습니다.")
        finish_run(client, "skipped", "발행 조건을 만족한 기사 없음")
        return 0

    progress(client, "목록·사이트맵·RSS 갱신", f"{len(created)}편 반영", done=len(created))
    all_posts = sorted(created + posts, key=sort_key, reverse=True)
    news_render.write_post_files(all_posts)
    write_rss(all_posts)

    finish_run(client, "done", f"신규 {len(created)}편")
    log(f"완료 — 신규 {len(created)}편 / 전체 {len(all_posts)}편")
    for p in created:
        log(f"   → https://www.admedical.co.kr/news/{p['slug']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
