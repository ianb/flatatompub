import os
import shutil
from webtest import TestApp
from flatatompub.wsgiapp import make_app
from taggerclient import atom
import urllib

here = os.path.dirname(__file__)
gdata_dir = os.path.join(here, 'gdata-test-data')
output_dir = os.path.join(here, 'unittest-data')

def get_app():
    return TestApp(make_app(
        {}, data_dir=output_dir,
        index='FlatAtomPub:sqlite',
        clear=True))

def test_gdata():
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    for fn in os.listdir(gdata_dir):
        if fn.endswith('.testcase'):
            yield run_case, fn

def read_file(fn):
    f = open(fn, 'rb')
    try:
        return f.read()
    finally:
        f.close()

def run_case(fn):
    fn = os.path.join(gdata_dir, fn)
    app = get_app()
    last_results = None
    last_query = None
    found = None
    for lineno, line in enumerate(read_file(fn).splitlines()):
        lineno += 1
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        parts = line.split(None, 1)
        command = parts[0]
        if parts[1:]:
            data = parts[1]
        else:
            data = None
        error = None
        try:
            if command == 'post':
                app.post('/', make_entry(data),
                         headers={'content-type': 'application/atom+xml;type=entry'},
                         status=201)
            elif command == 'post-file':
                app.post('/', read_file(data),
                         headers={'content-type': 'application/atom+xml;type=entry'},
                         status=201)
            elif command == 'get':
                last_query = data
                res = app.get('/-/%s' % data)
                feed = atom.ATOM(res.body)
                assert isinstance(feed, atom.Feed)
                last_results = [
                    entry.id for entry in feed.entries]
                found = []
            elif command == 'result-set':
                extra = list(last_results)
                for item in data.split(','):
                    item = item.strip()
                    if item not in last_results:
                        raise AssertionError(
                            "id %s not in results: %s"
                            % (item, format_results(last_results)))
                    if item in extra:
                        extra.remove(item)
                if extra:
                    raise AssertionError(
                        "Extra ids: %s" % format_results(extra))
            elif command == 'empty-results':
                if last_results:
                    raise AssertionError(
                        "Unexpected results: %s"
                        % format_results(last_results))
            elif command == 'check':
                if data not in last_results:
                    raise AssertionError(
                        "id %s not in results: %s"
                        % (id, format_results(last_results) or '(empty)'))
                found.append(data)
            elif command == 'length':
                if int(data) != len(last_results):
                    raise AssertionError(
                        "results not length %s (actually %s)"
                        % (data, len(last_results)))
            elif command == 'nomore':
                extra = list(last_results)
                for item in found:
                    if item in extra:
                        extra.remove(item)
                if extra:
                    raise AssertionError(
                        "unidentified ids: %s"
                        % (format_results(extra)))
            elif command == 'not':
                if data in last_results:
                    raise AssertionError(
                        "id %s not expected in results %s"
                        % (data, format_results(last_results)))
            else:
                assert 0, "unknown command: %r" % command
        except AssertionError, e:
            e.args = tuple(['line %s: %s (query: %s)' % (lineno, e.args[0], last_query)])
            raise
            

def format_results(results):
    if not results:
        return '(empty results)'
    else:
        return ', '.join([i or '(empty)' for i in results])

def make_entry(data):
    parts = data.split()
    entry = atom.Element('entry')
    assert '=' not in parts[0], (
        "Bad id: %r" % parts[0])
    entry.id = parts[0]
    for part in parts[1:]:
        if '=' not in part:
            raise ValueError("Bad assignment: %r in %r" % (part, data))
        name, value = part.split('=', 1)
        value = urllib.unquote_plus(value)
        if name.startswith('author'):
            if not entry.author:
                entry.append(atom.Element('author'))
            attr = name.split('.', 1)[1]
            setattr(entry.author, attr, value)
        elif name == 'id':
            entry.id = value
        elif name == 'cat' or name == 'category':
            el = atom.Element('category')
            if value.startswith('{'):
                value = value[1:]
                scheme, term = value.split('}', 1)
                el.scheme = scheme
                el.term = term
            else:
                el.term = value
            entry.append(el)
        elif name == 'updated':
            entry.updated = value
        elif name == 'content':
            value = '<content xmlns="%s">%s</content>' % (
                atom.atom_ns, value)
            el = atom.ATOM(value)
            entry.append(el)
        elif name == 'link':
            rel, href = value.split(':', 1)
            link = atom.Element('link')
            link.rel = rel
            link.href = href
            entry.append(link)
        else:
            assert 0, "Unknown parameter: %r" % name
    return atom.tostring(entry)
