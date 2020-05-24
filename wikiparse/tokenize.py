from collections import defaultdict
from nltk.tokenize import sent_tokenize, word_tokenize
import os
from pandas import concat, DataFrame, read_csv
from pathlib import Path
import pickle
import queue
import random
import re
import threading
import time

class Storage:
    def __init__(self, total=627344, folder="."):
        self.start = time.time()
        self._lock = threading.Lock()
        self.count = 0
        self.total = total
        self.folder = Path(folder)

    def time_left(self):
        with self._lock:
            time_spent = time.time() - self.start
            per_item = time_spent / self.count
            items_left = self.total - self.count
        return items_left * per_item

    def printable_time_left(self):
        time_left = self.time_left()
        if time_left < 60:
            return f'{round(time_left,1)} seconds'
        elif time_left < 60*60:
            return f'{round(time_left/60,1)} minutes'
        return f'{round(time_left/60/60, 2)} hours'

    def finish(self):
        pass

class DictStorage(Storage):
    def __init__(self, total=627344, folder="."):
        super().__init__(total, folder)
        self.dict = defaultdict(int)

    def update(self, wordset):
        with self._lock:
            for word in wordset:
                self.dict[word] += 1
            self.count += 1

class DataFrameStorage(Storage):
    def __init__(self, total=627344, folder="."):
        super().__init__(total, folder)
        self.dfs = []
        self.dfs_count = 0

    def update(self, df):
        with self._lock:
            self.dfs.append(df)
            self.count += 1
            if self.count % 10_000 == 0:
                self._write_out()

    def _write_out(self):
        fname = self.folder/f'tfidf_{self.dfs_count}.csv'
        concat(self.dfs).to_csv(fname)
        print("wrote to CSV", fname)
        self.dfs_count += 1
        self.dfs = []

    def done_count(self):
        with self._lock:
            return self.count

    def finish(self):
        try:
            self._write_out()
        except Exception as e:
            print(e)
        print("storage finished")

def lookup(word, wikipedia, threshold=10):
    if word in wikipedia and wikipedia[word] > threshold:
        return wikipedia[word]

    return -1

def tokenize_page(page):
    text = page.text
    try:
        text = remove_metadata(page.text)
    except:
        pass
    text = text.lower()
    # make all whitespace a single space character
    text = re.sub(r'\W',' ',text)
    text = re.sub(r'\s+',' ',text)

    tokens = word_tokenize(text)
    return tokens

def get_token_counts(page):
    wordfreq = {}
    tokens = tokenize_page(page)
    for token in tokens:
        if token not in wordfreq.keys():
            wordfreq[token] = 1
        else:
            wordfreq[token] += 1
    return wordfreq

def make_tfidf_df(page, wikipedia, top_n=50):
    wordfreq = get_token_counts(page)
    df = DataFrame(wordfreq.values(), index=wordfreq.keys(), columns=['tf'])
    df['article'] = page.title
    df['df'] = df.index.map(lambda word: lookup(word, wikipedia))
    # df['df'] = map(lookup, list(df.index), wikipedia)
    df['tf_idf'] = df.tf / df.df
    return df.sort_values(by='tf_idf', ascending=False).iloc[:top_n]

def create_doc_freq(indexer, folder='.'):
    folder = Path(folder)
    page_numbers = indexer.get_page_numbers()
    num_worker_threads = 10
    storage = DictStorage(total=len(page_numbers))

    def worker():
        while True:
            page = q.get()
            if page is None:
                break
            # we only care about whether a term is in a document, not how many times it appears there (for document frequency)
            tokens = set(tokenize_page(page))
            storage.update(tokens)
            if random.randint(0, 10000) == 42:
                print('time left:', round(storage.time_left() / 60 / 60, 2), 'hours  ')

            q.task_done()
    print('creating queue with', num_worker_threads, 'threads')
    q = queue.Queue()
    threads = []
    for i in range(num_worker_threads):
        t = threading.Thread(target=worker)
        t.start()
        threads.append(t)
    print('done starting threads; queueing')
    for i in range(len(page_numbers)):
        page_num = page_numbers[i]
        q.put(indexer.get_page_by_num(page_num))
        if i % 100 == 0:
            print(round(100*(i/len(page_numbers)),3),'% done with queueing', end='\r')
    print('done queueing pages\t\t')
    q.join()
    print('telling threads to stop')
    for i in range(num_worker_threads):
        q.put(None)
    print('waiting')
    for t in threads:
        t.join()
    fname = folder/'wikipedia_wordfreq.pkl'
    with open(fname, 'wb') as f:
        f.write(pickle.dumps(storage.dict))
    print("saved docfreq file to ", fname)

def create_tfidf(indexer, folder='.'):
    folder = Path(folder)
    with open(folder/'wikipedia_wordfreq.pkl', 'rb') as f:
        wikipedia = pickle.load(f)
    page_numbers = indexer.get_page_numbers()
    # this makes it more likely that the early time estimates will be accurate
    random.shuffle(page_numbers)
    storage = DataFrameStorage(total=len(page_numbers), folder=folder)
    times = []
    print("computing TF-IDF for", len(page_numbers), "pages")
    for page_num in page_numbers:
        page = indexer.get_page_by_num(page_num)
        start = time.time()
        df = make_tfidf_df(page, wikipedia)
        storage.update(df)
        times.append(time.time() - start)
        if random.randint(0, min(10000, storage.count)) == 0:
            print('time left ~', storage.printable_time_left(), '; done:', storage.done_count())
    storage.finish()
    avg_time = (sum(times) / len(times))
    total_time = avg_time*len(page_numbers)
    if total_time < 60:
        print(round(avg_time, 2), 'ms per, total time:', round(total_time,1), 'seconds')
    elif total_time < 60*60:
        print(round(avg_time, 2), 'ms per, total time:', round(total_time/60,1), 'minutes')
    else:
        print(round(avg_time, 2), 'ms per, total time:', round(total_time/60/60,2), 'hours')
    dfs = []
    for fname in os.listdir(folder):
        if 'tfidf_' in fname and '.csv' in fname:
            dfs.append(read_csv(folder/fname))
    df = concat(dfs)
    fname = folder/'tfidf.csv'
    df.to_csv(fname)
    print("wrote final CSV to", fname)
