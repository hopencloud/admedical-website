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
import sys
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

def publish_one(posts: list[dict], candidates: list, stats: dict,
                dry_run: bool = False) -> dict | None:
    """한 편 생성. 성공하면 새 post dict, 발행할 게 없으면 None."""
    published_titles = [p["title"] for p in posts]
    published_keys = {p.get("topic_key", "") for p in posts}

    topic = news_writer.select_topic(candidates, published_titles)
    if not topic:
        log("오늘 다룰 만한 주제가 없습니다. 발행하지 않고 종료합니다.")
        return None

    log(f"주제: {topic['topic']}")
    log(f"관점: {topic.get('angle', '')}")

    draft = news_writer.write_article(topic, stats, top_expressions())
    log(f"초고 작성 완료: {draft.get('title', '')} ({news_writer.word_count(draft)}자)")

    before = news_writer.word_count(draft)
    draft = news_writer.expand_article(draft, topic)
    if news_writer.word_count(draft) != before:
        log(f"분량 보강: {before}자 → {news_writer.word_count(draft)}자")

    verdict, article, issues = news_writer.review_article(draft, topic, stats)
    log(f"자체 검수: {verdict}")
    for issue in issues[:6]:
        log(f"   · {issue}")

    if verdict == "reject":
        log("검수에서 반려되었습니다. 발행하지 않습니다.")
        return None

    # 근거에 없는 숫자는 파이썬이 직접 잡는다 (AI 자기검수만으로는 새는 경우가 있음)
    bad_before = news_writer.unsupported_numbers(article, topic, stats)
    if bad_before:
        log(f"근거 미확인 수치 {len(bad_before)}개 발견: {', '.join(bad_before[:8])}")
        article, bad_after = news_writer.strip_unsupported_numbers(article, topic, stats)
        if bad_after:
            log(f"정정 후에도 남음: {', '.join(bad_after[:8])} — 발행하지 않습니다.")
            return None
        log("수치 정정 완료")

    final_chars = news_writer.word_count(article)
    if final_chars < 800:
        log(f"본문이 너무 짧습니다({final_chars}자). 발행하지 않습니다.")
        return None
    log(f"최종 분량: {final_chars}자")

    topic_key = news_writer.article_topic_key(article)
    if topic_key and topic_key in published_keys:
        log("이미 같은 주제를 발행했습니다. 건너뜁니다.")
        return None

    now = datetime.now(KST)
    slug = news_writer.make_slug(article, now)
    if any(p["slug"] == slug for p in posts):
        slug = f"{slug}-2"

    if dry_run:
        print(json.dumps(article, ensure_ascii=False, indent=2))
        return None

    # ----- 시각자료 -----
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    cover_rel = inline_rel = None

    cover_file = IMG_DIR / news_images.safe_filename(slug, "cover", "jpg")
    if news_images.generate_illustration(article.get("cover_prompt", topic["topic"]),
                                         cover_file, landscape=True):
        cover_rel = f"/assets/news/{cover_file.name}"

    inline_file = IMG_DIR / news_images.safe_filename(slug, "inline")
    if news_images.generate_illustration(article.get("inline_prompt", topic["topic"]),
                                         inline_file, landscape=False):
        inline_rel = f"/assets/news/{inline_file.name}"

    chart_svg = news_images.render_trend_chart_svg(
        stats.get("chart_30d", []),
        title="일자별 의료광고 심의 통과 건수 (최근 14일)",
        caption=article.get("chart_caption", ""),
    )

    checklist_svg = ""
    if not cover_rel and not inline_rel:
        # 이미지 생성이 전부 실패한 날에도 시각자료가 최소 2개는 남도록
        checklist_svg = news_images.render_checklist_card_svg(
            "오늘의 마케터 체크리스트", article.get("checklist", [])
        )

    # ----- HTML -----
    meta = {
        "slug": slug,
        "date": f"{now:%Y-%m-%d}",
        "cover": cover_rel,
        "inline_image": inline_rel,
        "sources": [
            {"title": s.title, "source": s.source, "link": s.link,
             "date": f"{s.published:%Y-%m-%d}"}
            for s in topic["sources"]
        ],
    }

    html_out = news_render.render_post(article, meta, chart_svg, checklist_svg)
    news_render.NEWS_DIR.mkdir(parents=True, exist_ok=True)
    (news_render.NEWS_DIR / f"{slug}.html").write_text(html_out, encoding="utf-8")
    log(f"기사 생성: website/news/{slug}.html")

    return {
        "slug": slug,
        "title": article.get("title", ""),
        "summary": article.get("summary", ""),
        "date": meta["date"],
        "cover": cover_rel,
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

    log("뉴스 수집 시작")
    candidates = news_sources.collect(
        hours=int(os.getenv("NEWS_LOOKBACK_HOURS", "48")),
        use_web_search=not args.no_web_search,
    )
    log(f"후보 {len(candidates)}건 수집")

    if not candidates:
        log("수집된 기사가 없습니다. 종료합니다.")
        return 0

    created: list[dict] = []
    for i in range(max(1, count)):
        if i:
            log(f"--- {i + 1}번째 글 ---")
        try:
            post = publish_one(posts + created, candidates, stats, dry_run=args.dry_run)
        except Exception:
            log("발행 중 오류 — 이번 편은 건너뜁니다.")
            traceback.print_exc()
            break
        if not post:
            break
        created.append(post)
        record_post(client, post, news_writer.WRITER_MODEL)

    if not created:
        log("새로 발행된 글이 없습니다.")
        return 0

    all_posts = sorted(created + posts, key=lambda p: (p["date"], p["slug"]), reverse=True)
    news_render.write_post_files(all_posts)
    write_rss(all_posts)

    log(f"완료 — 신규 {len(created)}편 / 전체 {len(all_posts)}편")
    for p in created:
        log(f"   → https://www.admedical.co.kr/news/{p['slug']}.html")
    return 0


if __name__ == "__main__":
    sys.exit(main())
