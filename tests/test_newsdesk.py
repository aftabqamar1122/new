"""Unit tests for the NewsDesk collection, analysis and export layers.

Run with:  python -m unittest discover -s tests -v
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import feedparser  # noqa: E402

from newsdesk import analysis, export, sources, summarize  # noqa: E402
from newsdesk.ai.base import ProviderError  # noqa: E402
from newsdesk.ai.gemini_provider import GeminiProvider  # noqa: E402
from newsdesk.ai.openai_provider import OpenAIProvider  # noqa: E402
from newsdesk.config import Config  # noqa: E402
from newsdesk.models import Article, Report  # noqa: E402


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def rfc822(when: datetime) -> str:
    return when.strftime("%a, %d %b %Y %H:%M:%S GMT")


def make_article(title: str, **kwargs) -> Article:
    defaults = {
        "link": f"https://example.com/{abs(hash(title))}",
        "source": "Reuters",
        "feed_name": "Reuters World",
        "published": utc_now(),
    }
    defaults.update(kwargs)
    return Article(title=title, **defaults)


class FeedParsingTests(unittest.TestCase):
    def _feed(self, items: str) -> list[Article]:
        rss = f"""<?xml version="1.0"?><rss version="2.0"><channel>
        <title>Test</title>{items}</channel></rss>"""
        parsed = feedparser.parse(rss.encode())
        source = {
            "name": "Reuters World",
            "source": "Reuters",
            "category": "mixed",
            "url": "https://news.google.com/rss/search?q=x",
        }
        return sources._entries_to_articles(parsed.entries, source, 40)

    def test_parses_title_link_and_date(self):
        when = utc_now()
        articles = self._feed(
            f"<item><title>NATO expands eastern deployments</title>"
            f"<link>https://example.com/a</link>"
            f"<pubDate>{rfc822(when)}</pubDate></item>"
        )
        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0].title, "NATO expands eastern deployments")
        self.assertEqual(articles[0].link, "https://example.com/a")
        self.assertIsNotNone(articles[0].published)
        self.assertLess(abs((articles[0].published - when).total_seconds()), 2)

    def test_strips_html_and_google_news_publisher_suffix(self):
        articles = self._feed(
            "<item><title>Oil prices climb on supply fears - Reuters</title>"
            "<link>https://example.com/b</link>"
            "<description>&lt;p&gt;Brent &lt;b&gt;rose&lt;/b&gt; 3%&lt;/p&gt;</description></item>"
        )
        self.assertEqual(articles[0].title, "Oil prices climb on supply fears")
        self.assertEqual(articles[0].summary, "Brent rose 3%")

    def test_missing_date_is_tolerated(self):
        articles = self._feed(
            "<item><title>Undated wire copy</title><link>https://e.com/c</link></item>"
        )
        self.assertIsNone(articles[0].published)
        self.assertEqual(articles[0].age_hours, float("inf"))


class DedupeTests(unittest.TestCase):
    def test_same_link_collapses(self):
        one = make_article("Story one", link="https://x.com/1")
        two = make_article("Different headline", link="https://x.com/1")
        self.assertEqual(len(sources.dedupe([one, two])), 1)

    def test_same_headline_records_corroboration(self):
        one = make_article("Central bank holds rates", source="Reuters")
        two = make_article("Central bank holds rates", source="BBC", link="https://y.com/2")
        result = sources.dedupe([one, two])
        self.assertEqual(len(result), 1)
        self.assertIn("BBC", result[0].corroborating_sources)


class ClassificationTests(unittest.TestCase):
    def test_military_story(self):
        article = make_article("Airstrike hits military base as troops mobilise")
        self.assertEqual(analysis.classify(article), "military")

    def test_financial_story(self):
        article = make_article("Federal Reserve holds interest rates as inflation cools")
        self.assertEqual(analysis.classify(article), "financial")

    def test_off_topic_story(self):
        article = make_article("Local bakery wins national pastry prize")
        self.assertEqual(analysis.classify(article), "other")

    def test_feed_hint_breaks_a_tie(self):
        article = make_article("Ministry announces new budget", category="military")
        self.assertEqual(analysis.classify(article), "military")


class RegionTests(unittest.TestCase):
    def test_regions_are_detected(self):
        cases = {
            "Israeli forces enter Gaza as Hezbollah responds": "Middle East",
            "Ukraine says Russian drones hit Kyiv power grid": "Eastern Europe",
            "Taiwan scrambles jets as China holds drills": "East Asia",
            "Federal Reserve keeps Washington guessing on rates": "North America",
            "Nigeria and Kenya sign Africa trade pact": "Africa",
        }
        for title, expected in cases.items():
            with self.subTest(title=title):
                self.assertEqual(analysis.detect_region(make_article(title)), expected)

    def test_unknown_region_defaults_to_global(self):
        self.assertEqual(analysis.detect_region(make_article("Markets slip on rate worry")), "Global")


class ImportanceTests(unittest.TestCase):
    def test_breaking_wire_story_scores_high(self):
        article = make_article(
            "Invasion forces cross border as nuclear alert declared",
            category="military",
        )
        article.corroborating_sources = ["BBC", "CNN"]
        score, _ = analysis.score_article(article)
        self.assertEqual(analysis.grade(score), "high")

    def test_routine_story_scores_low(self):
        article = make_article(
            "Analysts publish quarterly outlook review",
            source="Unknown Blog",
            published=utc_now() - timedelta(hours=20),
        )
        score, _ = analysis.score_article(article)
        self.assertEqual(analysis.grade(score), "low")

    def test_grades_are_ordered(self):
        self.assertEqual(analysis.grade(80), "high")
        self.assertEqual(analysis.grade(30), "medium")
        self.assertEqual(analysis.grade(5), "low")

    def test_clustering_links_same_story_across_outlets(self):
        items = [
            make_article("Central bank delivers surprise rate cut", source="Reuters"),
            make_article("Central bank delivers surprise interest rate cut", source="CNBC"),
            make_article("Warship transits contested strait", source="BBC"),
        ]
        analysis.cluster(items)
        self.assertEqual(items[0].cluster_id, items[1].cluster_id)
        self.assertNotEqual(items[0].cluster_id, items[2].cluster_id)
        self.assertIn("CNBC", items[0].corroborating_sources)


class AnalyzePipelineTests(unittest.TestCase):
    def setUp(self):
        self.logs: list[tuple[str, str]] = []
        self.log = lambda level, message: self.logs.append((level, message))

    def test_drops_stale_and_off_topic_items(self):
        articles = [
            make_article("Missile strike destroys airbase"),
            make_article(
                "Old missile strike report", published=utc_now() - timedelta(hours=48)
            ),
            make_article("Celebrity wedding photos released"),
        ]
        kept = analysis.analyze(articles, {"max_age_hours": 24}, self.log)
        titles = [a.title for a in kept]
        self.assertIn("Missile strike destroys airbase", titles)
        self.assertNotIn("Old missile strike report", titles)
        self.assertNotIn("Celebrity wedding photos released", titles)

    def test_keep_other_category_flag(self):
        articles = [make_article("Celebrity wedding photos released")]
        kept = analysis.analyze(
            articles, {"max_age_hours": 24, "keep_other_category": True}, self.log
        )
        self.assertEqual(len(kept), 1)

    def test_results_are_sorted_and_capped(self):
        # Genuinely distinct stories, so the duplicate collapser leaves them alone.
        headlines = [
            "Defence ministry reviews shipyard contract terms",
            "Reservists called for winter readiness exercise",
            "Arms exports licence backlog grows sharply",
            "Airbase runway repairs delayed until spring",
            "Frigate returns home after Baltic patrol",
            "Army recruitment shortfall prompts pay review",
            "Military logistics corps trials autonomous supply trucks",
            "Navy coastal radar network upgrade contract awarded",
            "Garrison town protests planned barracks closure",
            "Naval dockyard union votes on overtime deal",
            "Helicopter fleet grounded for gearbox inspection at airbase",
            "Cyber command opens second military operations centre",
        ]
        articles = [make_article(title) for title in headlines]
        articles.append(make_article("Nuclear alert declared after invasion begins"))
        kept = analysis.analyze(
            articles, {"max_age_hours": 24, "max_articles": 10}, self.log
        )
        self.assertEqual(len(kept), 10)
        self.assertEqual(kept, sorted(kept, key=lambda a: -a.score))
        self.assertEqual(kept[0].importance, "high")

    def test_duplicate_stories_collapse_into_one(self):
        articles = [
            make_article("Central bank delivers surprise rate cut", source="Reuters"),
            make_article(
                "Central bank delivers surprise interest rate cut",
                source="CNBC",
                link="https://other.example/2",
            ),
            make_article(
                "Central bank announces surprise rate cut decision",
                source="BBC",
                link="https://other.example/3",
            ),
        ]
        kept = analysis.analyze(articles, {"max_age_hours": 24}, self.log)
        self.assertEqual(len(kept), 1)
        self.assertGreaterEqual(len(set(kept[0].corroborating_sources)), 2)

    def test_duplicates_can_be_kept(self):
        articles = [
            make_article("Central bank delivers surprise rate cut", source="Reuters"),
            make_article(
                "Central bank delivers surprise interest rate cut",
                source="CNBC",
                link="https://other.example/2",
            ),
        ]
        kept = analysis.analyze(
            articles, {"max_age_hours": 24, "collapse_duplicates": False}, self.log
        )
        self.assertEqual(len(kept), 2)

    def test_short_headlines_are_dropped(self):
        kept = analysis.analyze(
            [make_article("War")], {"max_age_hours": 24, "min_title_length": 15}, self.log
        )
        self.assertEqual(kept, [])


class ExportTests(unittest.TestCase):
    def _report(self) -> Report:
        articles = [
            make_article(
                "Ceasefire agreed after missile exchange",
                category="military",
                region="Middle East",
                importance="high",
                summary="Both sides confirmed the deal.",
            ),
            make_article(
                "Fed holds rates steady",
                category="financial",
                region="North America",
                importance="medium",
                source="CNBC",
            ),
        ]
        return Report(
            generated_at=utc_now(),
            articles=articles,
            ai_summary="## Executive summary\n\nTwo developments.\n\n- **One** (Reuters)\n",
            ai_provider="Anthropic (Claude)",
            ai_model="claude-opus-5",
            feeds_ok=20,
            feeds_failed=1,
            errors=["Feed Z: timeout"],
        )

    def test_markdown_contains_sections_and_links(self):
        markdown = export.render_markdown(self._report())
        self.assertIn("# Military & Financial Brief", markdown)
        self.assertIn("## Military & security stories (1)", markdown)
        self.assertIn("## Financial & economic stories (1)", markdown)
        self.assertIn("Ceasefire agreed after missile exchange", markdown)
        self.assertIn("## Collection issues", markdown)

    def test_html_is_self_contained_and_escaped(self):
        report = self._report()
        report.articles[0].title = 'Tanks & "armour" <deployed>'
        html = export.render_html(report)
        self.assertTrue(html.startswith("<!doctype html>"))
        self.assertIn("<style>", html)
        self.assertNotIn("<deployed>", html)
        self.assertIn("&lt;deployed&gt;", html)
        self.assertIn("card high", html)

    def test_write_reports_creates_both_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = export.write_reports(
                self._report(), Path(tmp), ["markdown", "html"]
            )
            self.assertEqual(len(paths), 2)
            for path in paths:
                self.assertTrue(path.exists())
                self.assertGreater(path.stat().st_size, 200)

    def test_markdown_to_html_handles_common_syntax(self):
        html = export.markdown_to_html(
            "## Heading\n\n- **bold** item\n- [link](https://x.com)\n\nPlain <script> text\n"
        )
        self.assertIn("<h3>Heading</h3>", html)
        self.assertIn("<strong>bold</strong>", html)
        self.assertIn('<a href="https://x.com"', html)
        self.assertIn("&lt;script&gt;", html)


class ConfigTests(unittest.TestCase):
    def test_round_trip_and_defaults_merge(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            config = Config.load(path)
            config.set("ai.provider", "gemini")
            config.set("schedule.times", ["05:00"])
            config.save()

            # Simulate an older file that predates a newer setting.
            stored = json.loads(path.read_text())
            stored["collection"].pop("max_age_hours", None)
            path.write_text(json.dumps(stored))

            reloaded = Config.load(path)
            self.assertEqual(reloaded.get("ai.provider"), "gemini")
            self.assertEqual(reloaded.get("schedule.times"), ["05:00"])
            self.assertEqual(reloaded.get("collection.max_age_hours"), 24)

    def test_corrupt_file_falls_back_to_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text("{not json")
            self.assertEqual(Config.load(path).get("ai.provider"), "anthropic")

    def test_env_var_is_used_when_key_is_blank(self):
        config = Config()
        with mock.patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-env"}):
            self.assertEqual(config.provider_config("anthropic")["api_key"], "sk-env")

    def test_enabled_sources_filter(self):
        config = Config()
        config.data["sources"][0]["enabled"] = False
        self.assertEqual(
            len(config.enabled_sources()), len(config.data["sources"]) - 1
        )


class ProviderTests(unittest.TestCase):
    NET = {"timeout": 20, "verify_ssl": True, "proxy": ""}

    def test_openai_reads_responses_output(self):
        payload = {
            "output": [
                {"type": "reasoning", "summary": []},
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "The brief."}],
                },
            ]
        }
        provider = OpenAIProvider({"api_key": "k", "model": "gpt-5.6"}, self.NET)
        with mock.patch.object(provider, "_post", return_value=payload):
            self.assertEqual(provider.complete("sys", "prompt"), "The brief.")

    def test_openai_falls_back_to_chat_completions_on_404(self):
        provider = OpenAIProvider({"api_key": "k", "model": "gpt-5.6"}, self.NET)
        with mock.patch.object(
            provider, "_responses", side_effect=ProviderError("OpenAI API error 404: x")
        ), mock.patch.object(
            provider, "_chat_completions", return_value="fallback"
        ) as chat:
            self.assertEqual(provider.complete("sys", "prompt"), "fallback")
            chat.assert_called_once()

    def test_gemini_extracts_candidate_text(self):
        provider = GeminiProvider(
            {"api_key": "k", "model": "gemini-3.5-flash"}, self.NET
        )
        response = mock.Mock(status_code=200)
        response.json.return_value = {
            "candidates": [
                {"content": {"parts": [{"text": "Gemini brief."}]}, "finishReason": "STOP"}
            ]
        }
        with mock.patch("newsdesk.ai.gemini_provider.requests.post", return_value=response):
            self.assertEqual(provider.complete("sys", "prompt"), "Gemini brief.")

    def test_gemini_blocked_prompt_raises(self):
        provider = GeminiProvider({"api_key": "k", "model": "m"}, self.NET)
        response = mock.Mock(status_code=200)
        response.json.return_value = {"promptFeedback": {"blockReason": "SAFETY"}}
        with mock.patch("newsdesk.ai.gemini_provider.requests.post", return_value=response):
            with self.assertRaises(ProviderError):
                provider.complete("sys", "prompt")

    def test_missing_key_is_reported_not_raised(self):
        provider = OpenAIProvider({"api_key": "", "model": "gpt-5.6"}, self.NET)
        usable, reason = provider.ready()
        self.assertFalse(usable)
        self.assertIn("API key", reason)

    def test_ai_timeout_scales_above_feed_timeout(self):
        provider = OpenAIProvider({"model": "m", "api_key": "k"}, {"timeout": 20})
        self.assertGreaterEqual(provider.timeout, 120)


@unittest.skipUnless(
    __import__("importlib").util.find_spec("anthropic"),
    "the anthropic SDK is not installed",
)
class AnthropicProviderTests(unittest.TestCase):
    NET = {"timeout": 20, "verify_ssl": True, "proxy": ""}

    def setUp(self):
        from newsdesk.ai.anthropic_provider import AnthropicProvider

        self.provider = AnthropicProvider(
            {"api_key": "sk-test", "model": "claude-opus-5", "max_tokens": 8000}, self.NET
        )
        self.message = mock.Mock(
            stop_reason="end_turn",
            stop_details=None,
            content=[
                mock.Mock(type="thinking", thinking=""),
                mock.Mock(type="text", text="The brief."),
            ],
        )
        self.client = mock.Mock()
        self.client.messages.create.return_value = self.message

    def _patched(self):
        import anthropic

        return mock.patch.object(anthropic, "Anthropic", return_value=self.client)

    def test_returns_text_blocks_only(self):
        with self._patched():
            self.assertEqual(self.provider.complete("sys", "prompt"), "The brief.")

    def test_does_not_send_parameters_current_models_reject(self):
        with self._patched():
            self.provider.complete("sys", "prompt")
        kwargs = self.client.messages.create.call_args.kwargs
        for rejected in ("temperature", "top_p", "top_k"):
            self.assertNotIn(rejected, kwargs)
        self.assertEqual(kwargs["model"], "claude-opus-5")

    def test_refusal_is_reported_not_returned_as_content(self):
        self.message.stop_reason = "refusal"
        self.message.stop_details = mock.Mock(category="cyber")
        with self._patched():
            with self.assertRaises(ProviderError) as caught:
                self.provider.complete("sys", "prompt")
        self.assertIn("cyber", str(caught.exception))

    def test_truncated_answer_is_flagged(self):
        self.message.stop_reason = "max_tokens"
        with self._patched():
            self.assertIn("truncated", self.provider.complete("sys", "prompt"))

    def test_proxy_settings_build_a_custom_http_client(self):
        from newsdesk.ai.anthropic_provider import AnthropicProvider

        provider = AnthropicProvider(
            {"api_key": "k", "model": "m"},
            {"timeout": 20, "verify_ssl": True, "proxy": "http://proxy:8080"},
        )
        import anthropic

        with mock.patch.object(
            anthropic, "Anthropic", return_value=self.client
        ) as constructor:
            provider._client()
        self.assertIn("http_client", constructor.call_args.kwargs)


class SummarizeTests(unittest.TestCase):
    def test_digest_is_compact_and_labelled(self):
        articles = [
            make_article("Missile strike reported", importance="high", category="military")
        ]
        digest = summarize.build_digest(articles)
        self.assertIn("[1] HIGH | military", digest)
        self.assertIn("Missile strike reported", digest)

    def test_rank_json_parsing_is_lenient(self):
        parsed = summarize._parse_rank_json(
            'Sure!\n```json\n{"high": [1, 3], "medium": ["2"], "low": []}\n```'
        )
        self.assertEqual(parsed["high"], [1, 3])
        self.assertEqual(parsed["medium"], [2])

    def test_rerank_applies_model_grades(self):
        articles = [
            make_article("One story", importance="low"),
            make_article("Another story", importance="low"),
        ]
        provider = mock.Mock()
        provider.ready.return_value = (True, "")
        provider.complete.return_value = '{"high": [1], "low": [2]}'
        changed = summarize.rerank(provider, articles, lambda *_: None)
        self.assertEqual(changed, 1)
        self.assertEqual(articles[0].importance, "high")

    def test_fallback_summary_used_without_provider(self):
        text = summarize.fallback_summary(
            [make_article("Troops deploy", category="military", importance="high")]
        )
        self.assertIn("Executive summary", text)
        self.assertIn("Troops deploy", text)


class SerializationTests(unittest.TestCase):
    def test_report_round_trip(self):
        report = Report(
            generated_at=utc_now(),
            articles=[make_article("Story", importance="high", region="Africa")],
            ai_summary="brief",
            ai_provider="none",
        )
        restored = Report.from_dict(json.loads(json.dumps(report.to_dict())))
        self.assertEqual(len(restored.articles), 1)
        self.assertEqual(restored.articles[0].title, "Story")
        self.assertEqual(restored.articles[0].region, "Africa")
        self.assertEqual(restored.articles[0].importance, "high")
        self.assertIsNotNone(restored.articles[0].published)


class SchedulerTests(unittest.TestCase):
    def test_slot_parsing(self):
        from newsdesk.ui.scheduler import parse_slot

        self.assertIsNotNone(parse_slot("07:30"))
        self.assertIsNone(parse_slot("nonsense"))
        self.assertIsNone(parse_slot("25:00"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
