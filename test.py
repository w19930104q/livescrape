import datetime
import re
import unittest

import responses

import livescrape


class BasePage(livescrape.ScrapedPage):
    scrape_url = "http://fake-host/test.html"


DEFAULT_HTML = """<html><body>
<h1 class="foo" data-foo=1>Heading</h1>
<h1 id="the-id">15</h1>
<span class=float>3.14</span>
<span class=int>42</span>
<span class=bool></span>
<span class=date>2016-04-23</span>
<a href="/very-fake">link</a>
<table>
  <tr>test123
    <th>key</th> testmore
    <td>value</th></tr>
  <tr><th>key2<td>value2</tr>
</table
"""


class ResponsesTestCase(unittest.TestCase):
    def setUp(self):
        responses.reset()
        responses.start()
        self.addCleanup(responses.stop)
        self.addCleanup(responses.reset)

    def add_default_page(self, **kwargs):
        kwargs.setdefault("content_type", "text/html; charset=utf-8")
        responses.add(responses.GET, BasePage.scrape_url,
                      DEFAULT_HTML, **kwargs)


class Test(ResponsesTestCase):
    def setUp(self):
        super(Test, self).setUp()
        self.add_default_page()

    def test_simplecss(self):
        class Page(BasePage):
            foo = livescrape.Css("h1.foo")

        x = Page()

        self.assertEqual(x.foo, 'Heading')

    def test_dict(self):
        class Page(BasePage):
            foo = livescrape.Css("h1.foo")

        x = Page()

        self.assertEqual(x._dict, {"foo": 'Heading'})

    def test_ambigous(self):
        class Page(BasePage):
            foo = livescrape.Css("h1")

        x = Page()

        self.assertEqual(x.foo, 'Heading')

    def test_multiple(self):
        class Page(BasePage):
            foo = livescrape.Css("h1",
                                 multiple=True)

        x = Page()

        self.assertEqual(x.foo, ['Heading', '15'])

    def test_attribute(self):
        class Page(BasePage):
            foo = livescrape.Css("h1.foo",
                                 attribute="data-foo")
            not_there = livescrape.Css("h1.foo",
                                       attribute="not-there")

        x = Page()

        self.assertEqual(x.foo, '1')
        self.assertIsNone(x.not_there)

    def test_link(self):
        class Page(BasePage):
            foo = livescrape.CssLink("a", "Page")

        x = Page()

        self.assertIsInstance(x.foo, Page)
        self.assertEqual(x.foo.scrape_url,
                         "http://fake-host/very-fake")

    def test_float(self):
        class Page(BasePage):
            foo = livescrape.CssFloat(".float")
            foo_fail = livescrape.CssFloat(".date")

        x = Page()

        self.assertAlmostEqual(x.foo, 3.14)
        self.assertIsNone(x.foo_fail)

    def test_int(self):
        class Page(BasePage):
            foo = livescrape.CssInt(".int")
            foo_fail = livescrape.CssInt(".date")

        x = Page()

        self.assertEqual(x.foo, 42)
        self.assertIsNone(x.foo_fail)

    def test_date(self):
        class UTC(datetime.tzinfo):
            """UTC"""

            def utcoffset(self, dt):
                return datetime.timedelta(0)

            def tzname(self, dt):
                return "UTC"

            def dst(self, dt):
                return datetime.timedelta(0)

        class Page(BasePage):
            foo = livescrape.CssDate(".date", '%Y-%m-%d')
            foo_tz = livescrape.CssDate(".date", '%Y-%m-%d', tzinfo=UTC())
            foo_fail = livescrape.CssDate(".float", '%Y-%m-%d')

        x = Page()

        self.assertEqual(x.foo.year, 2016)
        self.assertEqual(x.foo.tzinfo, None)
        self.assertEqual(x.foo_tz.year, 2016)
        self.assertEqual(x.foo_tz.tzinfo.tzname(None), "UTC")
        self.assertIsNone(x.foo_fail)

    def test_bool(self):
        class Page(BasePage):
            foo = livescrape.CssBoolean(".bool")
            bar = livescrape.CssBoolean(".bool-not-there")

        x = Page()

        self.assertTrue(x.foo)
        self.assertFalse(x.bar)

    def test_raw(self):
        class Page(BasePage):
            foo = livescrape.CssRaw("table>tr")
            foo_withtag = livescrape.CssRaw("table>tr", include_tag=True)

        x = Page()
        html = re.sub(r'\s+', " ", x.foo).strip()
        self.assertEqual(html, "test123 <th>key</th> testmore <td>value</td>")

        html = re.sub(r'\s+', " ", x.foo_withtag).strip()
        self.assertEqual(
            html,
            "<tr>test123 <th>key</th> testmore <td>value</td></tr>")

    def test_complex(self):
        class Page(BasePage):
            foo = livescrape.CssMulti(
                "table tr",
                key=livescrape.Css("th"),
                value=livescrape.Css("td"))

        x = Page()

        self.assertEqual(x.foo, [{"key": "key", "value": "value"},
                                 {"key": "key2", "value": "value2"}])

    def test_group(self):
        class Page(BasePage):
            foo = livescrape.CssGroup("table tr", multiple=True)
            foo.key = livescrape.Css("th")
            foo.value = livescrape.Css("td")

        x = Page()

        self.assertEqual(x.foo[0]["key"], "key")
        self.assertEqual(x.foo[0]["value"], "value")
        self.assertEqual(x.foo[1]["key"], "key2")
        self.assertEqual(x.foo[1]["value"], "value2")

        self.assertEqual(x.foo[0].key, "key")
        self.assertEqual(x.foo[0].value, "value")
        self.assertEqual(x.foo[1].key, "key2")
        self.assertEqual(x.foo[1].value, "value2")
        self.assertEqual(x.foo[0]._dict(),
                         {"key": "key", "value": "value"})

        # List members, but filter private ones
        self.assertEqual([att for att in dir(x.foo[1])
                          if att[0] != "_"],
                         ["key", "value"])

        with self.assertRaises(AttributeError):
            x.foo[0].nonexistent

    def test_cleanup(self):
        cleanup_args = [None]

        def cleanup(x):
            self.assertIsNone(cleanup_args[0])
            cleanup_args[0] = x
            return "TESTed"

        class Page(BasePage):
            foo = livescrape.Css("h1.foo",
                                 cleanup=cleanup)

        x = Page()

        self.assertEqual(x.foo, "TESTed")
        self.assertEqual(cleanup_args[0], "Heading")

    def test_extract(self):
        extract_args = [None]

        def extract(x):
            self.assertIsNone(extract_args[0])
            extract_args[0] = x
            return "TESTed"

        class Page(BasePage):
            foo = livescrape.Css("h1.foo",
                                 extract=extract)

        x = Page()

        self.assertEqual(x.foo, "TESTed")
        self.assertEqual(extract_args[0].text, "Heading")

    def test_cleanup_extract(self):
        cleanup_args = [None]
        extract_args = [None]

        def cleanup(x):
            self.assertIsNone(cleanup_args[0])
            cleanup_args[0] = x
            return "TESTed"

        def extract(x):
            self.assertIsNone(extract_args[0])
            extract_args[0] = x
            return "Xtracted"

        class Page(BasePage):
            foo = livescrape.Css("h1.foo",
                                 cleanup=cleanup,
                                 extract=extract)

        x = Page()
        value = x.foo

        self.assertEqual(extract_args[0].text, "Heading")
        self.assertEqual(cleanup_args[0], "Xtracted")
        self.assertEqual(value, "TESTed")

    def test_decorator(self):
        cleanup_args = [None]
        extract_args = [None]
        method_args = [None]

        def cleanup(x):
            self.assertIsNone(cleanup_args[0])
            cleanup_args[0] = x
            return "TESTed"

        def extract(x):
            self.assertIsNone(extract_args[0])
            extract_args[0] = x
            return "Xtracted"

        class Page(BasePage):
            @livescrape.Css("h1.foo",
                            cleanup=cleanup,
                            extract=extract)
            def foo(self, value, element):
                method_args[0] = (value, element)
                return "METhod"

        x = Page()
        value = x.foo

        self.assertEqual(extract_args[0].text, "Heading")
        self.assertEqual(cleanup_args[0], "Xtracted")
        self.assertEqual(method_args[0][0], "TESTed")
        self.assertEqual(method_args[0][1].text, "Heading")
        self.assertEqual(value, "METhod")

    def test_headers(self):
        class Page(BasePage):
            scrape_headers = {"foo": "bar"}

        Page().scrape_fetch(BasePage.scrape_url)
        self.assertEqual(len(responses.calls), 1)
        self.assertEqual(responses.calls[0].request.headers['Foo'],
                         'bar')

    def test_referer(self):
        class Page(BasePage):
            foo = livescrape.CssLink("a", "Page")

        x = Page()

        self.assertIsInstance(x.foo, Page)

        responses.add(
            responses.GET, x.foo.scrape_url,
            "<html>")

        self.assertIsNone(x.foo.foo)

        self.assertEqual(len(responses.calls), 2)
        self.assertEqual(responses.calls[1].request.headers['Referer'],
                         'http://fake-host/test.html')

    def test_custom_referer(self):
        class Page(BasePage):
            foo = livescrape.CssLink("a", "Page", referer="http://no")

        x = Page()

        self.assertIsInstance(x.foo, Page)

        responses.add(
            responses.GET, x.foo.scrape_url,
            "<html>")

        self.assertIsNone(x.foo.foo)

        self.assertEqual(len(responses.calls), 2)
        self.assertEqual(responses.calls[1].request.headers['Referer'],
                         'http://no')

    def test_no_referer(self):
        class Page(BasePage):
            foo = livescrape.CssLink("a", "Page", referer=False)

        x = Page()

        self.assertIsInstance(x.foo, Page)

        responses.add(
            responses.GET, x.foo.scrape_url,
            "<html>")

        self.assertIsNone(x.foo.foo)

        self.assertEqual(len(responses.calls), 2)
        self.assertNotIn("Referer", responses.calls[1].request.headers)


class SnapshotTest(ResponsesTestCase):
    def test_snapshot_shared_between_fields(self):
        self.add_default_page()

        class Page(BasePage):
            foo = livescrape.Css("h1.foo")
            num = livescrape.CssInt(".int")

        x = Page()
        self.assertEqual(x.foo, "Heading")
        self.assertEqual(x.num, 42)

        # A single fetch serves all fields of the object
        self.assertEqual(len(responses.calls), 1)

        snapshot = x.scrape_snapshot
        self.assertTrue(snapshot.ok)
        self.assertIsNone(snapshot.error)
        self.assertEqual(snapshot.status_code, 200)
        self.assertEqual(snapshot.url, BasePage.scrape_url)
        self.assertEqual(snapshot.final_url, BasePage.scrape_url)
        self.assertEqual(snapshot.encoding.lower(), "utf-8")
        self.assertIn("Heading", snapshot.text)
        self.assertIsNotNone(snapshot.document)

    def test_snapshot_final_url_after_redirect(self):
        responses.add(responses.GET, BasePage.scrape_url,
                      status=302,
                      headers={"Location": "http://fake-host/landing.html"})
        responses.add(responses.GET, "http://fake-host/landing.html",
                      DEFAULT_HTML,
                      content_type="text/html; charset=utf-8")

        class Page(BasePage):
            foo = livescrape.Css("h1.foo")

        x = Page()
        self.assertEqual(x.foo, "Heading")
        self.assertEqual(x.scrape_snapshot.final_url,
                         "http://fake-host/landing.html")

    def test_legacy_html(self):
        # Pre-HTML5 markup: unclosed tags, font tags, bare entities
        responses.add(responses.GET, BasePage.scrape_url, """<html>
<head><title>Legacy page</title>
<body bgcolor=white>
<font size=3 class=banner>Legacy &amp; font</font>
<p>Unclosed paragraph
<table><tr><td class=cell>cell value</table>
</html>""", content_type="text/html; charset=utf-8")

        class Page(BasePage):
            banner = livescrape.Css("font.banner")
            cell = livescrape.Css("td.cell")

        x = Page()
        self.assertEqual(x.banner, "Legacy & font")
        self.assertEqual(x.cell, "cell value")
        self.assertTrue(x.scrape_snapshot.ok)

    def test_non_200(self):
        responses.add(responses.GET, BasePage.scrape_url,
                      "<html><body><h1 class=foo>oops</h1>",
                      status=503)

        class Page(BasePage):
            foo = livescrape.Css("h1.foo")

        x = Page()

        with self.assertRaises(livescrape.ScrapeError) as ctx:
            x.foo

        # The failure carries the full snapshot
        snapshot = ctx.exception.snapshot
        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.status_code, 503)
        self.assertFalse(snapshot.ok)
        self.assertIs(x.scrape_snapshot, snapshot)

        # Every field sees the same failure, no extra requests
        with self.assertRaises(livescrape.ScrapeError):
            x.foo
        self.assertEqual(len(responses.calls), 1)

    def test_non_200_allowed(self):
        responses.add(responses.GET, BasePage.scrape_url,
                      "<html><body><h1 class=foo>oops</h1>",
                      status=404)

        class Page(BasePage):
            scrape_raise_for_status = False
            foo = livescrape.Css("h1.foo")

        x = Page()
        self.assertEqual(x.foo, "oops")
        self.assertEqual(x.scrape_snapshot.status_code, 404)

    def test_bad_encoding(self):
        # UTF-8 bytes, but the server declares iso-8859-1
        body = ("<html><body><h1 class=foo>Grüße</h1></body></html>"
                .encode("utf-8"))
        responses.add(responses.GET, BasePage.scrape_url, body,
                      content_type="text/html; charset=iso-8859-1")

        class Page(BasePage):
            foo = livescrape.Css("h1.foo")

        x = Page()
        snapshot = x.scrape_snapshot

        # The declared (wrong) encoding is recorded on the snapshot...
        self.assertEqual(snapshot.encoding.lower(), "iso-8859-1")
        self.assertNotIn("Grüße", snapshot.text)

        # ...and the raw content is available to recover the real text
        self.assertIn("Grüße", snapshot.text_as("utf-8"))
        self.assertIn("Grüße", snapshot.content.decode("utf-8"))

    def test_parse_failure(self):
        # An empty body cannot be parsed by lxml
        responses.add(responses.GET, BasePage.scrape_url, "")

        class Page(BasePage):
            foo = livescrape.Css("h1.foo")

        x = Page()

        with self.assertRaises(livescrape.ScrapeError) as ctx:
            x.foo

        snapshot = ctx.exception.snapshot
        self.assertIsNotNone(snapshot.error)
        self.assertFalse(snapshot.ok)
        self.assertIsNone(snapshot.document)

    def test_consecutive_retries(self):
        responses.add(responses.GET, BasePage.scrape_url, status=500)
        responses.add(responses.GET, BasePage.scrape_url, status=500)
        responses.add(responses.GET, BasePage.scrape_url, DEFAULT_HTML,
                      content_type="text/html; charset=utf-8")

        class Page(BasePage):
            foo = livescrape.Css("h1.foo")

        x = Page()

        with self.assertRaises(livescrape.ScrapeError):
            x.foo

        snapshot = x.scrape_retry()
        self.assertFalse(snapshot.ok)
        self.assertEqual(snapshot.status_code, 500)
        with self.assertRaises(livescrape.ScrapeError):
            x.foo

        snapshot = x.scrape_retry()
        self.assertTrue(snapshot.ok)
        self.assertEqual(x.foo, "Heading")

        self.assertEqual(len(responses.calls), 3)

    def test_retry_after_parse_failure(self):
        responses.add(responses.GET, BasePage.scrape_url, "")
        responses.add(responses.GET, BasePage.scrape_url, DEFAULT_HTML,
                      content_type="text/html; charset=utf-8")

        class Page(BasePage):
            foo = livescrape.Css("h1.foo")

        x = Page()
        with self.assertRaises(livescrape.ScrapeError):
            x.foo

        self.assertTrue(x.scrape_retry().ok)
        self.assertEqual(x.foo, "Heading")

    def test_sessions_do_not_leak_cookies(self):
        responses.add(responses.GET, BasePage.scrape_url, DEFAULT_HTML,
                      headers={"Set-Cookie": "sessionid=abc123"})
        responses.add(responses.GET, BasePage.scrape_url, DEFAULT_HTML)

        class Page(BasePage):
            foo = livescrape.Css("h1.foo")

        first = Page()
        self.assertEqual(first.foo, "Heading")
        # The first page's own session picked up the cookie
        self.assertEqual(first.scrape_session.cookies["sessionid"],
                         "abc123")

        second = Page()
        self.assertEqual(second.foo, "Heading")

        self.assertEqual(len(responses.calls), 2)
        self.assertNotIn("Cookie", responses.calls[1].request.headers)


if __name__ == '__main__':
    unittest.main()
