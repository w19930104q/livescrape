from abc import abstractmethod
import datetime
from html import escape
from urllib import parse as urlparse
import warnings

import lxml.etree
import lxml.html
import requests


DEFAULT_USER_AGENT = "Mozilla/5.0 (Livescrape)"


class ScrapeError(Exception):
    """Raised when a page could not be retrieved or parsed.

    The ``snapshot`` attribute holds the :class:`PageSnapshot` that caused
    the failure, so callers can inspect the HTTP status, final url,
    encoding and the original exception.
    """

    def __init__(self, message, snapshot=None):
        super(ScrapeError, self).__init__(message)
        self.snapshot = snapshot


class PageSnapshot(object):
    """The result of a single fetch and parse of a ScrapedPage.

    All scraped attributes of a single page object share one snapshot, so
    every field reflects the exact same response. A snapshot explicitly
    carries the HTTP status, the final url (after redirects), the detected
    encoding and any retrieval or parse failure.
    """

    def __init__(self, url, status_code=None, final_url=None, encoding=None,
                 text=None, content=None, document=None, error=None):
        self.url = url
        self.status_code = status_code
        self.final_url = final_url
        self.encoding = encoding
        self.text = text
        self.content = content
        self.document = document
        self.error = error

    @property
    def ok(self):
        """Whether this snapshot holds a usable, successfully fetched
        document."""
        return (self.error is None
                and self.document is not None
                and (self.status_code is None or self.status_code < 400))

    def text_as(self, encoding):
        """Decode the raw response content with an explicit encoding.

        Useful when the server declared a wrong encoding; the detected
        encoding is available as ``snapshot.encoding``.
        """
        if self.content is None:
            return self.text
        return self.content.decode(encoding, errors="replace")

    def __repr__(self):
        return ("%s(url=%r, status_code=%r, final_url=%r, encoding=%r, "
                "ok=%r)" % (type(self).__name__, self.url, self.status_code,
                            self.final_url, self.encoding, self.ok))


class ScrapedAttribute(object):
    """Base class for scraped attributes.

    When used in a ScrapedPage, it will be converted into an attribute.
    """

    def __init__(self, extract=None, cleanup=None, attribute=None,
                 multiple=False):
        if extract and attribute:
            raise ValueError("extract and attribute are mututally exclusive")

        self._cleanup = cleanup
        self._extract = extract
        self.attribute = attribute
        self.multiple = multiple

        # Placeholder for cleanup method when using the decorator syntax
        self._cleanup_method = None

    @abstractmethod
    def get(self, doc, scraped_page):  # pragma: no cover
        raise NotImplementedError()

    def extract(self, element, scraped_page):
        if self._extract:
            value = self._extract(element)
        elif self.attribute is None:
            value = element.text_content()
        else:
            value = element.get(self.attribute)
            if value is None:
                return

        return self.perform_cleanups(value, element, scraped_page)

    def perform_cleanups(self, value, element, scraped_page=None):
        if self._cleanup:
            value = self._cleanup(value)

        if self._cleanup_method:
            value = self._cleanup_method(scraped_page, value, element)

        return self.cleanup(value, element, scraped_page)

    def cleanup(self, value, elements, scraped_page=None):
        return value

    def __call__(self, func):
        self._cleanup_method = func
        return self


_SCRAPER_CLASSES = {}


class _ScrapedMeta(type):
    """A metaclass for Scraped.

    Converts any ScrapedAttribute attributes to usable properties.
    """
    def __new__(cls, name, bases, namespace):
        keys = []
        for key, value in namespace.items():
            if isinstance(value, ScrapedAttribute):
                def mk_attribute(selector):
                    def method(scraped):
                        return scraped._get_value(selector)
                    return property(method)

                namespace[key] = mk_attribute(value)
                keys.append(key)

        result = super(_ScrapedMeta, cls).__new__(cls, name, bases, namespace)
        result.scrape_keys = keys
        _SCRAPER_CLASSES[name] = result
        return result


class ScrapedPage(object, metaclass=_ScrapedMeta):
    scrape_url = None
    scrape_args = []
    scrape_arg_defaults = {}
    scrape_headers = {}

    # Whether a HTTP error status (>= 400) should fail attribute access.
    # When disabled, error pages are scraped like any other page.
    scrape_raise_for_status = True

    def __init__(self, *pargs, **kwargs):
        scrape_url = kwargs.pop("scrape_url", None)
        scrape_referer = kwargs.pop("scrape_referer", None)

        arguments = dict(self.scrape_arg_defaults)
        arguments.update(kwargs)
        arguments.update(zip(self.scrape_args, pargs))
        self.scrape_args = arguments

        if scrape_url:
            self.scrape_url = scrape_url
        elif not self.scrape_url:
            # We can't scrape if we don't actually have a url configured
            raise ValueError("%s.scrape_url needs to be defined" %
                             type(self).__name__)
        else:
            self.scrape_url = self.scrape_url % arguments

        self.scrape_headers = dict(self.scrape_headers)
        if scrape_referer:
            self.scrape_headers['Referer'] = scrape_referer

        self._scrape_snapshot = None
        self._scrape_session = None

    @property
    def scrape_session(self):
        # Each page object gets its own session, so cookies and other
        # state never leak between unrelated page objects. Override this
        # property (or scrape_create_session) to share a session.
        if self._scrape_session is None:
            self._scrape_session = self.scrape_create_session()
        return self._scrape_session

    def scrape_create_session(self):
        session = requests.Session()
        session.headers['User-Agent'] = DEFAULT_USER_AGENT
        return session

    def scrape_fetch(self, url):
        """Fetch the page, and return the ``requests`` response object."""
        return self.scrape_session.get(url,
                                       headers=self.scrape_headers)

    def scrape_create_document(self, page):
        return lxml.html.fromstring(page)

    def scrape_create_snapshot(self, response):
        """Build a PageSnapshot from a fetched response."""
        document = None
        error = None
        try:
            document = self.scrape_create_document(response.text)
        except Exception as exc:
            error = exc

        return PageSnapshot(
            url=self.scrape_url,
            status_code=response.status_code,
            final_url=response.url,
            encoding=response.encoding or response.apparent_encoding,
            text=response.text,
            content=response.content,
            document=document,
            error=error)

    @property
    def scrape_snapshot(self):
        """The snapshot all scraped attributes of this object operate on.

        The page is fetched lazily on first access; from then on, every
        attribute shares this exact snapshot.
        """
        if self._scrape_snapshot is None:
            self._scrape_snapshot = self._scrape_fetch_snapshot()
        return self._scrape_snapshot

    def _scrape_fetch_snapshot(self):
        try:
            response = self.scrape_fetch(self.scrape_url)
        except Exception as exc:
            return PageSnapshot(url=self.scrape_url, error=exc)
        return self.scrape_create_snapshot(response)

    def scrape_retry(self):
        """Discard the current snapshot and fetch the page again.

        Returns the new snapshot. Use this to recover from a failed
        snapshot (``snapshot.ok`` is False).
        """
        self._scrape_snapshot = None
        return self.scrape_snapshot

    def _get_value(self, property_scraper):
        snapshot = self.scrape_snapshot

        if snapshot.error is not None:
            raise ScrapeError(
                "Failed to retrieve %s: %s" % (self.scrape_url,
                                               snapshot.error),
                snapshot=snapshot)

        if (self.scrape_raise_for_status
                and snapshot.status_code is not None
                and snapshot.status_code >= 400):
            raise ScrapeError(
                "HTTP status %s while retrieving %s" % (
                    snapshot.status_code, self.scrape_url),
                snapshot=snapshot)

        return property_scraper.get(snapshot.document, scraped_page=self)

    @property
    def _dict(self):
        return dict((key, getattr(self, key)) for key in self.scrape_keys)

    def __repr__(self):
        return "%s(scrape_url=%r)" % (type(self).__name__, self.scrape_url)


class Css(ScrapedAttribute):
    def __init__(self, selector, **kwargs):
        self.selector = selector
        assert selector or not self.multiple, "Empty selectors are only "\
            "with singular matches"

        super(Css, self).__init__(**kwargs)

    def get(self, doc, scraped_page):
        assert doc is not None
        if not self.selector:
            return doc

        elements = doc.cssselect(self.selector)

        if self.multiple:
            values = [self.extract(element, scraped_page)
                      for element in elements]
            return [v for v in values if v is not None]
        elif len(elements):
            return self.extract(elements[0], scraped_page)


class CssFloat(Css):
    def cleanup(self, value, elements, scraped_page=None):
        try:
            return float(value)
        except ValueError:
            return None


class CssInt(Css):
    def cleanup(self, value, elements, scraped_page=None):
        try:
            return int(value)
        except ValueError:
            return None


class CssDate(Css):
    def __init__(self, selector, date_format, tzinfo=None, **kwargs):
        self.date_format = date_format
        self.tzinfo = tzinfo
        super(CssDate, self).__init__(selector, **kwargs)

    def cleanup(self, value, elements, scraped_page=None):
        try:
            result = datetime.datetime.strptime(value, self.date_format)
            if self.tzinfo:
                result = result.replace(tzinfo=self.tzinfo)
            return result
        except ValueError:
            return None


class CssBoolean(Css):
    def cleanup(self, value, elements, scraped_page=None):
        return True


class CssRaw(Css):
    def __init__(self, selector, include_tag=False, **kwargs):
        self.include_tag = include_tag
        super(CssRaw, self).__init__(selector, **kwargs)

    def extract(self, element, scraped_page):
        if self.include_tag:
            value = lxml.html.tostring(element, encoding="unicode")
        else:
            value = ""
            if element.text:
                value = escape(element.text, quote=False)
            for child in element:
                value += lxml.html.tostring(child, encoding="unicode")

        return self.perform_cleanups(value, element, scraped_page)


class CssMulti(Css):
    def __init__(self, selector, cleanup=None, **subselectors):
        super(CssMulti, self).__init__(selector, cleanup=cleanup,
                                       multiple=True)
        self.subselectors = subselectors
        warnings.warn(
            "The 'CssMulti' class was deprecated in favor of CssGroup",
            DeprecationWarning)

    def extract(self, element, scraped_page=None):
        value = {}

        for key, selector in self.subselectors.items():
            value[key] = selector.get(element,
                                      scraped_page=scraped_page)

        return self.perform_cleanups(value, element, scraped_page)


class CssGroup(Css):
    class _CompoundAttribute(object):
        def __init__(self, parent, element, scraped_page):
            self._subselectors = parent._subselectors
            self._element = element
            self._scaped_page = scraped_page

        def __getattr__(self, attribute):
            try:
                selector = self._subselectors[attribute]
            except KeyError:
                return getattr(super(CssGroup._CompoundAttribute, self),
                               attribute)

            return selector.get(self._element, self._scaped_page)

        def __getitem__(self, attribute):
            # May raise keyerror, which is suitable for __getitem__
            selector = self._subselectors[attribute]
            return selector.get(self._element, self._scaped_page)

        def __dir__(self):
            attrs = dir(super(CssGroup._CompoundAttribute, self))
            attrs += self._subselectors.keys()
            return attrs

        def _dict(self):
            return dict(
                (key, selector.get(self._element, self._scaped_page))
                for (key, selector) in self._subselectors.items())

    def __init__(self, *pargs, **kwargs):
        super(CssGroup, self).__init__(*pargs, **kwargs)
        self._subselectors = {}

    def extract(self, element, scraped_page=None):
        value = CssGroup._CompoundAttribute(self, element, scraped_page)
        return self.perform_cleanups(value, element, scraped_page)

    def __setattr__(self, key, value):
        if isinstance(value, ScrapedAttribute):
            self._subselectors[key] = value
        else:
            super(CssGroup, self).__setattr__(key, value)


class CssLink(Css):
    def __init__(self, selector, page_factory, referer=True, **kwargs):
        kwargs.setdefault('attribute', 'href')
        super(CssLink, self).__init__(selector, **kwargs)
        self.page_factory = page_factory
        self.referer = referer

    def cleanup(self, value, elements, scraped_page=None):
        # Resolve relative links against the final url of the snapshot,
        # so redirects are taken into account.
        base_url = (scraped_page.scrape_snapshot.final_url
                    or scraped_page.scrape_url)
        url = urlparse.urljoin(base_url, value)
        factory = (_SCRAPER_CLASSES[self.page_factory]
                   if isinstance(self.page_factory, str)
                   else self.page_factory)

        if self.referer is True:  # automatic referer
            referer = base_url
        elif not self.referer:
            referer = None
        else:
            referer = self.referer

        return factory(scrape_url=url, scrape_referer=referer)
