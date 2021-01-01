#!/usr/bin/env python3
# vim:fileencoding=UTF-8:ts=4:sw=4:sta:et:sts=4:ai
from __future__ import (unicode_literals, division, absolute_import,
                        print_function)
try:
    from queue import Empty, Queue
except ImportError:
    from Queue import Empty, Queue
import json
import re
from lxml import etree
from calibre import as_unicode
from calibre.ebooks.metadata.book.base import Metadata
from calibre.ebooks.metadata.sources.base import Source, Option

__license__ = 'GPL v3'
__copyright__ = '2020, SamLangTen <samlangten@outlook.com>'
__docformat__ = 'restructuredtext en'


class Bokelai(Source):

    name = 'Bokelai Books.com.tw'
    author = 'SamLangTen'
    version = (1, 0, 0)
    minimum_calibre_version = (2, 80, 0)

    BOKELAI_DETAIL_URL = 'https://www.books.com.tw/products/%s'
    BOKELAI_QUERY_URL = 'https://search.books.com.tw/search/query/key/%s'

    description = _('Download metadata and cover from books.com.tw.'
                    'Useful only for books published in Hong Kong and Taiwan.'
                    'Not compatible with books published in Mainland China. ')

    capabilities = frozenset(['identify', 'cover'])
    touched_fields = frozenset(
        ['title', 'authors', 'tags', 'publisher', 'comments', 'pubdate', 'identifier:isbn', 'identifier:bokelai'])
    supports_gzip_transfer_encoding = True
    cached_cover_url_is_reliable = True

    def __init__(self, *args, **kwargs):
        Source.__init__(self, *args, **kwargs)

    def retrieve_bokelai_detail(self, bokelai_id, log, result_queue, timeout):

        detail_url = self.BOKELAI_DETAIL_URL % bokelai_id
        log.info(detail_url)

        try:
            br = self.browser
            _raw = br.open_novisit(detail_url, timeout=timeout)
            raw = _raw.read()
        except Exception as e:
            log.exception('Failed to load detail page: %s' % detail_url)
            return

        root = etree.HTML(raw)
        info_json_text = root.xpath(
            "//script[@type='application/ld+json']")[0].text
        log.info(info_json_text)
        info_json = json.loads(info_json_text)


        title = info_json['name']
        authors = info_json['author'][0]['name'].split(",")
        publisher = info_json['publisher'][0]['name']
        isbn = info_json['workExample']['workExample']['isbn']
        pubdate = info_json['datePublished']

        comments = ""
        comments_ele = root.xpath("(//div[@class='content'])[1]//text()")
        comments = "\n".join(comments_ele)

        
        tags = list()
        for ele in root.xpath("//li[contains(text(),'本書分類：')]/a"):
            log.info(ele.text)
            if "／" in ele.text:
                tags.extend(ele.text.split("／"))
            if "/" in ele.text:
                tags.extend(ele.text.split("/"))
            else:
                tags.append(ele.text)
        

        cover_url = re.search(r'https[^\?\=\&]*'+bokelai_id+r'[^\?\=\&]*', info_json['image']).group(0)

        if not authors:
            authors = [_('Unknown')]

        log.info(title,authors,publisher,isbn,pubdate,comments,tags,cover_url)

        mi = Metadata(title, authors)
        mi.identifiers = {'bokelai': bokelai_id, 'isbn': isbn}
        mi.publisher = publisher
        mi.comments = comments
        mi.isbn = isbn
        mi.tags = tags
        if pubdate:
            try:
                from calibre.utils.date import parse_date, utcnow
                default = utcnow().replace(day=15)
                mi.pubdate = parse_date(pubdate, assume_utc=True, default=default)
            except:
                log.error('Failed to parse pubdate %r' % pubdate)       

        if not cover_url is None:
            mi.has_bokelai_cover = cover_url
            self.cache_identifier_to_cover_url(
                mi.identifiers['bokelai'], mi.has_bokelai_cover)
        else:
            mi.has_bokelai_cover = None

        result_queue.put(mi)

    def parse_bokelai_query_page(self, log, raw):
        root = etree.HTML(raw)
        books_url = root.xpath("//form[@id='searchlist']/ul/li/a[@rel='mid_image']/@href")
        book_ids = list()
        for url in books_url:
            bid = re.search(r"(?<=item\/)[^\/]*",url).group()
            book_ids.append(bid)
        return book_ids

    def get_book_url(self, identifiers):

        db = identifiers.get('bokelai', None)
        if db is not None:
            return ('bokelai', db, self.BOKELAI_DETAIL_URL % db)

    def download_cover(self, log, result_queue, abort, title=None, authors=None, identifiers={}, timeout=30, get_best_cover=False):
        cached_url = self.get_cached_cover_url(identifiers)
        if cached_url is None:
            log.info('No cached cover found, running identify')
            rq = Queue()
            self.identify(log, rq, abort, title=title,
                          authors=authors, identifiers=identifiers)
            if abort.is_set():
                return
            results = []
            while True:
                try:
                    results.append(rq.get_nowait())
                except Empty:
                    break
            results.sort(
                key=self.identify_results_keygen(
                    title=title, authors=authors, identifiers=identifiers)
            )
            for mi in results:
                cached_url = self.get_cached_cover_url(mi.identifiers)
                if cached_url is not None:
                    break
        if cached_url is None:
            log.info('No cover found')
            return

        if abort.is_set():
            return
        br = self.browser
        log('Downloading cover from:', cached_url)
        try:
            cdata = br.open_novisit(cached_url, timeout=timeout).read()
            if cdata:
                result_queue.put((self, cdata))
        except:
            log.exception('Failed to download cover from:', cached_url)

    def get_cached_cover_url(self, identifiers):
        url = None
        bokelai_id = identifiers.get('bokelai', None)
        if bokelai_id is not None:
            url = self.cached_identifier_to_cover_url(bokelai_id)
        return url

    def identify(self, log, result_queue, abort, title=None, authors=None, identifiers={}, timeout=30):

        # Bokelai id exists, read detail page
        bokelai_id = identifiers.get('bokelai', None)
        if bokelai_id:
            self.retrieve_bokelai_detail(
                bokelai_id, log, result_queue, timeout)
            return

        # ISBN exists, use isbn to query
        isbn = identifiers.get('isbn', None)
        if isbn:
            search_url = self.BOKELAI_QUERY_URL % isbn

        # No isbn, use title and authors to query
        if not isbn:
            search_str = ''
            if title:
                search_str = search_str + title
            if authors:
                for author in authors:
                    search_str = search_str + author
            search_url = self.BOKELAI_QUERY_URL % search_str
        try:
            br = self.browser
            _raw = br.open_novisit(search_url, timeout=timeout)
            raw = _raw.read()
        except Exception as e:
            log.exception('Failed to make identify query: %s' % search_url)
            return as_unicode(e)

        candidate_bokelai_id_list = self.parse_bokelai_query_page(log, raw)
        if not candidate_bokelai_id_list:
            log.error('No result found.\n', 'query: %s' % search_url)
            return

        for bid in candidate_bokelai_id_list:
            if abort.is_set:
                pass
            self.retrieve_bokelai_detail(bid, log, result_queue, timeout)

if __name__ == '__main__':  # tests {{{
    # To run these test use: calibre-debug -e src/calibre/ebooks/metadata/sources/douban.py
    from calibre.ebooks.metadata.sources.test import (
        test_identify_plugin, title_test, authors_test
    )
    test_identify_plugin(
        Bokelai.name, [
            ({
                'identifiers': {
                    'isbn': '9789862376836'
                },
                'title': '姊嫁物語 01',
                'authors': ['森薰']
            }, [title_test('姊嫁物語 01', exact=False),
                authors_test(['森薰'])])
        ]
    )
# }}}