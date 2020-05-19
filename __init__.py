#!/usr/bin/env python2
# vim:fileencoding=UTF-8:ts=4:sw=4:sta:et:sts=4:ai
from __future__ import (unicode_literals, division, absolute_import,
                        print_function)
from urllib import urlencode
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
        try:
            br = self.browser
            _raw = br.open_novisit(detail_url, timeout=timeout)
            raw = _raw.read()
        except Exception as e:
            log.exception('Failed to load detail page: %s' % detail_url)
            return

        root = etree.HTML(raw)
        info_json_text = root.xpath(
            "//script[@type='application/ld+json]/string()")
        info_json = json.loads(info_json_text)

        title = info_json['name'].decode('unicode-escape')
        authors = info_json['author'][0]['name'].decode(
            'unicode-escape').split(",")
        publisher = info_json['publisher'][0]['name'].decode(
            'unicode-escape')
        isbn = info_json['workExample']['workExample']['isbn']
        pubdate = info_json['datePublished']

        comments = root.xpath("//div[@class='content']/string()")
        tags = root.xpath(
            "//li[contains(text(),'本書分類：')]/string()").replace("本書分類：", "").split("&gt; ")

        if not authors:
            authors = [_('Unknown')]

        mi = Metadata(title, authors)
        mi.identifiers = {'bokelai': bokelai_id}
        mi.publisher = publisher
        mi.comments = comments
        mi.isbn = isbn
        mi.tags = tags
        pubdate_list = pubdate.split('/')
        mi.pubdate = (pubdate_list[0], pubdate_list[1],
                      pubdate_list[2], 0, 0, 0, 0, 0, 0)

    def parse_bokelai_query_page(self, log, raw):
        return list()

    def get_book_url(self, identifiers):

        db = identifiers.get('bokelai', None)
        if db is not None:
            return ('bokelai', db, self.BOKELAI_DETAIL_URL % db)

    def download_cover(self, log, result_queue, abort, title=None, authors=None, identifiers={}, timeout=30, get_best_cover=False):
        pass

    def get_cached_cover_url(self, identifiers):
        pass

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
            search_url = self.BOKELAI_QUERY_URL + search_str
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

        for id in candidate_bokelai_id_list:
            if abort.is_set:
                break
            self.retrieve_bokelai_detail(id, log, result_queue, timeout)
