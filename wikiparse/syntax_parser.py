import re
import time

def _get_starting_indices(string, tag):
    return [m.start() for m in re.finditer(tag, string)]

def get_tags(string, tag):
    tags = []
    if tag[-1] != '\|':
        tag = tag+'\|'
    starting_indices = _get_starting_indices(string, tag)
    for idx in starting_indices:
        ending_idx = string[idx:].find('}}')
        tags.append(string[idx:idx+ending_idx])
    return tags
