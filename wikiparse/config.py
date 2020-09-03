import json

with open("config.json") as f:
    j = json.loads(f.read())
    xml = j['xml_dump']
    folder = j['folder']
