import codecs
from collections import defaultdict
import hashlib
import logging
import os
import re
import shelve
import sqlite3
import subprocess
import time
import xml.etree.ElementTree as etree

import logging
import os

logger = logging.getLogger('wikidump.config')

scratch = 'E:/enwiki-20190101-pages-articles-multistream.xml/scratch'
xml_dumps = 'E:/enwiki-20190101-pages-articles-multistream.xml/_actual'

fname = 'enwiki-20190101-pages-articles-multistream.xml'

# -*- coding: utf-8 -*-
# Static constants for dealing with different langauge wikis

# List of wikipedia prefixes - not exhaustive
prefixes = ['ru', 'nap', 'ja', 'ta', 'tl', 'az', 'ht', 'et', 'ca', 'wa', 'pms',
'de', 'nl', 'su', 'bpy', 'fa', 'tr', 'en', 'eu', 'io', 'jv', 'nds', 'pt', 'zh',
'bn', 'lt', 'la', 'nn', 'no', 'he', 'sh', 'lb', 'ro', 'hr', 'scn', 'da', 'it',
'te', 'br', 'an', 'fr', 'cs', 'is', 'new', 'lv', 'ast', 'uk', 'mk', 'oc', 'ku',
'sl', 'sk', 'af', 'ka', 'pl', 'ceb', 'th', 'sv', 'id', 'bs', 'hi', 'el', 'cy',
'gl', 'vi', 'sq', 'fi', 'mr', 'hu', 'ar', 'bg', 'ms', 'ko', 'be']

# Keyword for identifying category labels in different languages
# TODO: Complete this list
category_identifier =\
  { 'en' : 'Category'
  , 'fr' : 'Catégorie'
  , 'de' : 'Kategorie'
  , 'ja' : 'Category'
  , 'it' : 'Categoria'
  , 'ru' : 'Категория'
  , 'pl' : 'Kategoria'
  , 'nl' : 'Categorie'
  , 'sv' : 'Kategori'
  , 'zh' : 'Category'
  }


# Match the name of a dumpfile
dumpfile_name = re.compile(r'(?P<prefix>.*?)wiki-(?P<date>\d{8})-pages-articles-multistream.xml')

intrawiki_link = re.compile(r"\[\[(?P<target>.*?\|)?(?P<anchor>.*?)\]\]")

lang_prefixes = '|'.join(prefixes)
lang_link = re.compile(r"\[\[(?P<prefix>"+lang_prefixes+"):(?P<title>.+?)\]\]")

category_keywords = '|'.join(category_identifier.values())
category_link = re.compile(r"\[\[(?P<title>("+category_keywords+"):(?P<category>.+?))\|(.+?)\]\]")
category_name = re.compile(r"(?P<keyword>("+category_keywords+")):(?P<category>.+)")

redirect = re.compile(r"\#REDIRECT (?P<target>.*)")

template = re.compile(r"\{\{(?P<target>.*?)\}\}")

xml_path = xml_dumps
all_prefixes =  [    dumpfile_name.match(f).group(1)
                for  f
                in   os.listdir(xml_path)
                if   dumpfile_name.match(f)
                ]

def getSizeAndMakeOffsets(f, db, current_page=0):
    print('=== making offsets ===')

    # these exist to track progress
    start_ts = ts = time.time()
    total_time = 0
    mbytes_processed = 0
    cursor = db.cursor()

    # index is in bytes, not characters
    try:
        # idx = offsets[str(current_page)]
        idx = db.execute(
                f'SELECT idx FROM indices WHERE page_num={current_page}'
            ).fetchone()[0]
    except (    KeyError, TypeError):
        idx = 0
    f.seek(idx)

    for line in f:
        if b'<page>' is line:
            current_page += 1
            cursor.execute(f"INSERT INTO indices VALUES ('', '', {current_page}, {idx})")
        elif b'  <page>\n' is line:
            current_page += 2
            cursor.execute(f"INSERT INTO indices VALUES ('', '', {current_page}, {idx + 2})")
        elif b'<page>' in line:
            current_page += 1
            cursor.execute(f"INSERT INTO indices VALUES ('', '', {current_page}, {idx + line.index(b'<page>')})")
        idx += len(line)
        if idx % 100_000 == 0:
            mbytes_processed += 100
            db.commit()
            total_time += time.time() - ts
            print(f' {round(idx / 1000000000, 3):10} GB processed \
                     {round(1000 * (time.time() - ts) / 10, 2):10}ms per mb \
                     {round(1000 * total_time/mbytes_processed, 2):10}ms per mb avg',
                     end='\r')
            ts = time.time()
    print('\npages:', current_page, round(total_time, 1), 'seconds')
    return current_page

"""
Model of a wikipedia dump
based on wikidump code
"""

class Dump:
    logger = logging.getLogger('wikidump.model.Dump')

    def _open_db(self):
        path = os.path.join(self.cache_path, 'index.db')
        print('opening', path)
        return sqlite3.connect(path)

    def _open_shelf(self, name):
        "Open a shelf-file in a pre-determined location by name"
        path = os.path.join(self.cache_path, name)
        return shelve.open(path)

    def __init__(self, xml_path, build_index=False, scratch_folder='py3'):
        self.xml_path = os.path.abspath(xml_path)
        self.xml_file = open(self.xml_path, 'rb')
        # May want to hash the file instead for portability
        # path_hash = hashlib.sha1(os.path.basename(self.xml_path)).hexdigest()
        path_hash = scratch_folder
        self.cache_path = os.path.join(scratch, path_hash)

        self.logger.info("============================================")
        self.logger.info("Loading data for %s", self.xml_path)

        if not os.path.exists(self.cache_path):
            self.logger.info("Creating %s", self.cache_path)
            os.mkdir(self.cache_path)

        # Open a metadata shelf
        self.metadata = self._open_shelf('metadata')

        # Mapping from page index to position in file
        self.db = self._open_db()
        self.cursor = self.db.cursor()
        # self.page_offsets = self._open_shelf('page_offsets')
        try:
            rows_in_db = self.cursor.execute(
                    '''SELECT Count(*) from indices'''
                ).fetchone()[0]
        except sqlite3.OperationalError:
            print("creating a new table")
            rows_in_db = 0
            self.cursor.execute('''CREATE TABLE indices
                    (title TEXT, coords TEXT, page_num INTEGER PRIMARY KEY, idx INTEGER)''')

        if rows_in_db > 1_000_000:
            print('current mapping', round(rows_in_db/1_000_000, 1), 'm pages')
        elif rows_in_db > 1_000:
            print('current mapping', round(rows_in_db/1_000, 1), 'k pages')
        else:
            print('current mapping', rows_in_db, 'pages')

        # Compute size of dump
        try:
            # we'll only set this after all indices have been stored in the db
            size = self.metadata['size']
        except KeyError:
            start_at_page = 0
            if rows_in_db > 0:
                # start_at_page = int(list(self.page_offsets.keys())[-1])
                start_at_page = self.cursor.execute(
                        '''SELECT MAX(page_num) FROM indices'''
                    ).fetchone()[0]
            self.metadata['size'] = getSizeAndMakeOffsets(
                open(self.xml_path, 'rb'),
                self.db,
                current_page=start_at_page)
            size = self.metadata['size']
            self.logger.info("Processed %d pages", size)
            print(f'Processed {size/1000}k pages')

        self.logger.debug("Size: %d pages", size)

        # Mapping from page title to page index
        # self.page_titles = self._open_shelf('page_titles')
        num_page_titles = self.cursor.execute(
            '''SELECT Count(*) FROM indices WHERE title != ""'''
        ).fetchone()[0]
        #self.logger.debug("Currently know of %d page titles", len(self.page_titles))
        # find the rest of the pages
        if build_index and num_page_titles < size:
            print('=== making page title dictionary from beginning ===')
            total_time = 0
            for i in range(num_page_titles, size):
                ts = time.time()

                try:
                    tree = etree.fromstring(self.get_raw(i))
                except Exception as e:
                    print(f'{i} caused an error:' + self.get_raw(i)[:50], '...', self.get_raw(i)[-50:])
                    continue
                # Need to encode as etree will return both str and unicode
#                 title = tree.find('title').text.encode('utf8')
                title = tree.find('title').text
                # if title in self.page_titles:
                #     self.logger.warning("Already had '%s', index %d", title, self.page_titles[title])
                # else:
                    # self.page_titles[title] = i
                self.cursor.execute(
                    f'UPDATE indices SET title=? WHERE page_num=?',
                    (title, i+1)
                )
                total_time += time.time()-ts
                if i % 1000 == 0:
                    self.db.commit()
                    print(f' {round((100*i/size), 3):10}%\t{round(1000*total_time/(i+1), 2)}ms per page', end='\r')
        else:
            self.logger.debug("Not building page title index")

        self.page_lengths = self._open_shelf('page_lengths')
        # self.db.close()
        self.db.commit()
        print("\n__init__ complete")

    @property
    def size(self):
        return self.metadata['size']

    def get_raw(self, page_num):
        "Get raw xml dump data for a given index"
        f = self.xml_file
        # start_offset = self.page_offsets[str(index+1)]
        start_offset = self.get_offset(page_num+1)
        f.seek(start_offset)
        try:
            # end_offset = self.page_offsets[str(index+2)]
            end_offset = self.get_offset(page_num+2)
            return f.read(end_offset - start_offset).decode('utf-8')
        except KeyError:
            # Handle the corner case which is the very last entry
            raw = f.read().decode('utf-8')
            match = re.search(r'.*</page>', raw)
            return raw[:match.end()]

    def get_offset(self, page_num):
        result = self.cursor\
            .execute(f'SELECT idx FROM indices WHERE page_num={page_num}')\
            .fetchone()
        if result is None:
            raise Exception("cannot get idx for page", page_num)
        return result[0]

    def get_page_index(self, title):
        "Look up the index of a page based on its title"
        return self.page_titles[title]

    def get_page_contents(self, index):
        "Get the full text of a page by index"
        tree = etree.fromstring(self.get_raw(index))
        return tree.find('revision').find('text').text.encode('utf8')

    def get_page_length(self, index):
        "Look up the length of a page given an index"
        try:
            return self.page_lengths[str(index)]
        except KeyError:
            length = len(self.get_page_contents(index))
            self.page_lengths[str(index)] = length
            return length

    def get_page_contents_by_title(self, title):
        "Get the contents of a page with a given title"
        index = self.get_page_index(title)
        return self.get_page_contents(index)

    def get_page(self, title):
        "Return a Page object for the page of the given title"
        index = self.get_page_index(title)
        return Page(self.get_raw(index))

    def get_page_by_index(self, index):
        "Return a Page object given the raw index of the page"
        return Page(self.get_raw(index))

    def get_dumpfile_prefix(self):
        "Return the prefix code associated with the filename"
        filename = os.path.basename(self.xml_path)
        return dumpfile_name.match(filename).groups()[0]

class Page:
    """
    Represents a single page in a wikidump
    """
    logger = logging.getLogger('wikidump.model.Page')

    def __init__(self, string):
        """
        @param string: A string containin the raw xml version of the page
        """
        self.xml = string
        self.dom = etree.fromstring(string)
        self.text = self.dom.find('revision').find('text').text
        self.title = self.dom.find('title').text

    def lang_equiv(self, prefix):
        """ Returns the page title for the equivalent page in the given language prefix
        """
        lang_links = dict(lang_link.findall(self.text))
        try:
            return lang_links[prefix]
        except KeyError:
            return None

    def categories(self):
        """ Returns the set of categories this page is member of.
        changed from 0.1 : was previously a list. Do not want duplicates.
        """
        print(self.text)
        try:
            return set(category_link.findall(self.text.decode())[0])
        except IndexError: #No categories
            return []

def category_map(dump):
    "Compute the category mapping of a particular dump"
    cat_count = defaultdict(list)
    for i in range(dump.metadata['size']):
        p = dump.get_page_by_index(i)
        for c in p.categories():
            cat_count[c].append(i)
    return cat_count

def load_dumps(langs=None, dump_path=None, build_index=False, scratch_folder='py3'):
    """Load the dumps, and take note of their size"""
    # Take note that we will end up loading all the dumps we have for a given language
    # but only returning the last one we find.
    # TODO: Handle different-dated dumps of the same language
    if langs is None:
        langs = all_prefixes
    if dump_path is None:
        dump_path = xml_path
    dumps = {}
    for path in os.listdir(dump_path):
        if not re.match('|'.join(langs), path): continue
        full_path = os.path.join(dump_path, path)
        d = Dump(full_path, build_index=build_index, scratch_folder=scratch_folder)
        prefix = d.get_dumpfile_prefix()
        dumps[prefix] = d
    return dumps

if __name__ == "__main__":
    dump = load_dumps(build_index=True)
