import logging
import os
import shelve
import sqlite3
import time
import xml.etree.ElementTree as etree

from . import pipeline_utils as utils

PAGES_ESTIMATE = 21_000_000

def page_generator(f, current_page=0, sample=1.0):
    start_idx = 0
    end_idx = 0
    current_page = 0

    for line in f:
        if b'<page>' in line and start_idx != end_idx:
            f.seek(start_idx)
            current_page += 1
            yield start_idx, end_idx, f.read(end_idx - start_idx)
            start_idx = end_idx
            if sample < 1.0 and current_page > PAGES_ESTIMATE * sample:
                print("reached end of sample, ", current_page, "pages found, idx at", start_idx)
                break
        else:
            end_idx = end_idx + len(line)

class Indexer:
    logger = logging.getLogger('wikidump.model.Dump')

    def __init__(self, xml_path, scratch_folder='./py3'):
        self.xml_path = os.path.abspath(xml_path)
        self.xml_file = open(self.xml_path, 'rb')
        # May want to hash the file instead for portability
        self.cache_path = scratch_folder

        self.logger.info("============================================")
        self.logger.info("Loading data for %s", self.xml_path)

        if not os.path.exists(self.cache_path):
            self.logger.info("Creating %s", self.cache_path)
            os.mkdir(self.cache_path)

        self.metadata = self._open_shelf('metadata')

        # Mapping from page index to position in file
        self.db = self._open_db()
        self.cursor = self.db.cursor()

        # self.page_offsets = self._open_shelf('page_offsets')
        try:
            self.cursor.execute('''SELECT Count(*) from indices''').fetchone()[0]
            self.cursor.execute('''SELECT Count(*) from coords''').fetchone()[0]
        except sqlite3.OperationalError:
            print("creating a new table")
            self.cursor.execute('''CREATE TABLE indices
                    (title TEXT, coords TEXT, page_num INTEGER PRIMARY KEY, start_idx INTEGER, end_idx INTEGER)''')
            self.cursor.execute(utils.get_coords_db_create_string())

        print("Ready. Metadata:", [(key,self.metadata[key]) for key in self.metadata.keys()])

    def _open_db(self):
        path = os.path.join(self.cache_path, 'index.db')
        print('opening', path)
        return sqlite3.connect(path)

    def _open_shelf(self, name):
        "Open a shelf-file in a pre-determined location by name"
        path = os.path.join(self.cache_path, name)
        return shelve.open(path)

    def get_raw(self, page_num):
        "Get raw xml dump data for a given page number"
        f = self.xml_file
        start_idx,end_idx = self.get_offsets(page_num)
        f.seek(start_idx)
        return f.read(end_idx - start_idx).decode('utf-8')

    def get_page_by_num(self, page_num):
        "Get the full text of a page by page_num"
        return Page(self.get_raw(page_num))

    def get_offsets(self, page_num):
        result = self.cursor\
            .execute(f'SELECT start_idx,end_idx FROM indices WHERE page_num={page_num}')\
            .fetchone()
        if result is None:
            raise Exception("cannot get idx for page", page_num)
        return result

    def get_page_numbers(self):
        page_nums = self.cursor.execute('''SELECT page_num FROM coords WHERE display="inline,title"''').fetchall()
        return [int(page_num[0]) for page_num in page_nums]

    def load(self, sample=1.):
        start = time.time()
        pg = page_generator(open(self.xml_path, 'rb'), sample=sample)
        coords_count = 0
        for i,page in enumerate(pg):
            start_idx, end_idx, page = page
            if utils.tag_finder(page, ['Coord', 'coord']):
                coords_count += 1
                page_text = page.decode('utf-8')
                data_extract = utils.page_to_geographic_db(page_text)
                if data_extract['coords']:
                    try:
                        self.cursor.execute(f"INSERT INTO indices VALUES (?,?,?,?,?)",
                            (data_extract['title'], data_extract['coords'], int(i),
                             int(start_idx), int(end_idx))
                        )
                    except sqlite3.IntegrityError:
                        pass
                    coords_dict = utils.coord_string_to_dict(data_extract['coords'])
                    coords_dict['title'] = data_extract['title']
                    coords_dict['page_num'] = i
                    qstring = f'''INSERT INTO coords
                        ({",".join(coords_dict.keys())}) VALUES
                        ({",".join(["?" for item in coords_dict.values()])})'''
                    # print(qstring, coords_dict.values())
                    try:
                        self.cursor.execute(qstring, list(coords_dict.values()))
                    except sqlite3.IntegrityError:
                        pass
                else:
                    pass
                    # print(data_extract['title'], 'coord tag not found')
            if coords_count % 1_000 == 0:
                self.db.commit()
            print(i, end='\r')
        print(f"iterating {round(sample*100,2)}% of pages took {round((time.time()-start)/60,2)} minutes")
        print(round(100*coords_count/i,2), '% contained coordinates tag')
        self.metadata['size'] = coords_count
        self.db.commit()
        self.create_title_db()

    def create_title_db(self):
        print("Creating title dictionary")
        try:
            self.cursor.execute('DROP TABLE titles')
        except sqlite3.OperationalError:
            pass
        self.cursor.execute('CREATE TABLE titles\
                            (title TEXT PRIMARY KEY, start_idx INTEGER, end_idx INTEGER, page_num INTEGER)')
        total_time = 0
        start_ts = time.time()
        page_numbers = self.get_page_numbers()
        for i,page_num in enumerate(page_numbers):
            try:
                tree = etree.fromstring(self.get_raw(page_num))
            except Exception as e:
                try:
                    print(f'{page_num} caused an error:', str(e))
                    continue
                except:
                    # print(f'{i} cannot get raw')
                    continue
            # Need to encode as etree will return both str and unicode
#                 title = tree.find('title').text.encode('utf8')
            title = tree.find('title').text
            start_idx,end_idx = self.cursor.execute(f'SELECT start_idx,end_idx FROM indices WHERE page_num={page_num}').fetchone()
            try:
                self.cursor.execute(
                    f"INSERT INTO titles VALUES (?,?,?,?)",
                    (title, start_idx, end_idx, page_num)
                )
            except sqlite3.OperationalError as e:
                print(e, title)
                return
            except sqlite3.IntegrityError as e:
                print(e, title)
            if i % 1000 == 0:
                total_time = time.time() - start_ts
                self.db.commit()
                print(f' {round((100*i/len(page_numbers)), 3):10}%\t{round(1000*total_time/(i+1), 2)}ms / page  ', end='\r')

class Page:
    def __init__(self, string):
        self.xml = string
        self.dom = etree.fromstring(string)
        self.text = self.dom.find('revision').find('text').text
        self.title = self.dom.find('title').text

    def __str__(self):
        return 'Page: ' + self.title
def run_test():
    indexer = Indexer("C:/Users/rowan/Documents/geowiki/enwiki-20200101-pages-articles-multistream.xml",
                scratch_folder='C:/Users/rowan/Documents/geowiki/scratch')
    indexer.load(1.0)

if __name__ == "__main__":
    # import cProfile
    # cProfile.run('run_test()')

    run_test()
