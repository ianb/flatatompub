import os
from datetime import datetime
from webob import Request, Response, html_escape, UTC
from webob.exc import *
from flatatompub.dec import wsgiapp, bindery
from taggerclient import atom
from taggerclient import gdata
from paste.fileapp import FileApp
import md5

@wsgiapp
def app(req):
    store = req.store
    next = req.path_info_peek()
    req.app_root = req.application_url + '/'
    if next == 'service':
        return serve_service
    elif next == 'media':
        req.path_info_pop()
        return serve_media
    elif next == '-':
        # GData query
        return serve_gdata
    elif next:
        # A slug!
        req.slug = req.path_info_pop()
        return serve_entry
    elif req.method == 'POST':
        if req.content_type.split(';')[0] == 'application/atom+xml':
            return post_entry
        else:
            return post_media
    else:
        return serve_feed

@wsgiapp
def serve_entry(req):
    try:
        entry = req.store.get_entry(req.slug)
    except KeyError, e:
        return HTTPNotFound(
            comment='No file %s' % e.args[0])
    store = req.store
    entry = store.get_entry(req.slug)
    res = check_conditional_headers(
        req, entry.etag, entry.last_modified)
    if res is not None:
        return res
    if req.method == 'DELETE':
        entry.delete()
        return HTTPNoContent()
    elif req.method == 'PUT':
        atom_entry = atom.ATOM(req.body)
        if req.config.clean_html:
            clean_html(atom_entry)
        entry.atom_entry = atom_entry
        entry.save()
    if req.method not in ['GET', 'HEAD', 'PUT']:
        return HTTPMethodNotAllowed(
            headers=dict(Allow='GET,HEAD,DELETE,PUT'))
    res = req.response
    res.content_type = 'application/atom+xml; type=entry'
    res.etag = entry.etag
    res.last_modified = entry.last_modified
    res.body = str(entry)
    return res

def make_feed(config):
    feed = atom.Element('feed', nsmap=atom.nsmap)
    if config.feed_info is not None:
        feed.extend(config.feed_info)
    if not feed.title:
        feed.title = config.feed_title or 'Feed'
    return feed

@wsgiapp
def serve_feed(req):
    if req.method not in ['GET', 'HEAD']:
        return HTTPMethodNotAllowed(
            headers=dict(allow='GET,HEAD'))
    feed = make_feed(req.config)
    feed.updated = req.store.most_recent()
    if req.if_modified_since and req.if_modified_since >= feed.updated:
        return HTTPNotModified()
    try:
        start_index = int(req.queryvars.get('start-index', 1))
        start_index -= 1
        if start_index < 0:
            raise ValueError("start-index must not be negative")
        max_results = int(req.queryvars.get('max-results', req.config.page_limit))
        if max_results < 0:
            raise ValueError("max-results must not be negative")
    except ValueError, e:
        return HTTPBadRequest(
            "value is invalid: %s" % e)
    full_length, slugs = req.store.index.most_recent(
        req.store, start_index, max_results)
    if start_index:
        prev_link = atom.Element('link')
        prev_pos = max(start_index - (max_results or 10), 0)
        prev_link.href = req.path_url + '?start-index=%s' % (prev_pos+1)
        prev_link.rel = 'previous'
        feed.append(prev_link)
    if slugs and (full_length is None or full_length - start_index > max_results):
        next_link = atom.Element('link')
        next_pos = start_index + max_results
        next_link.href = req.path_url + '?start-index=%s' % (next_pos+1)
        next_link.rel = 'next'
        feed.append(next_link)
    if start_index:
        first_link = atom.Element('link')
        first_link.rel = 'first'
        first_link.href = req.path_url
        feed.append(first_link)
    if full_length is not None and full_length > max_results:
        if full_length is not None:
            last_pos = full_length - (full_length%max_results)
            if last_pos == full_length:
                last_pos -= max_results
            last_link = atom.Element('link')
            last_link.href = req.path_url + '?start-index=%s' % (last_pos+1)
            last_link.rel = 'last'
            feed.append(last_link)
    for slug in slugs:
        entry = req.store.get_entry(slug)
        feed.append(entry.atom_entry)
    res = req.response
    res.content_type = 'application/atom+xml'
    res.body = atom.tostring(feed, pretty_print=True)
    res.last_modified = feed.updated
    res.etag = md5.new(res.body).hexdigest()
    if res.etag in req.if_none_match:
        return HTTPNotModified()
    return res

@wsgiapp
def serve_gdata(req):
    query = gdata.parse_gdata(req)
    query, slugs = req.store.index.gdata_query(query, req.store)
    if query is not None:
        # Need to do more filtering...
        entries = []
        for slug in slugs:
            entry = req.store.get_entry(slug)
            matches = query.evaluate(entry.atom_entry)
            if matches:
                entries.append(entry.atom_entry)
    else:
        entries = [req.store.get_entry(slug).atom_entry for slug in slugs]
    ## FIXME: this should do type checking and other stuff
    start_index = int(req.queryvars.get('start-index', 1))-1
    max_results = int(req.queryvars.get('max-results', req.config.page_limit))
    if start_index:
        entries = entries[start_index:]
    if max_results:
        entries = entries[:max_results]
    feed = make_feed(req.config)
    feed.extend(entries)
    res = req.response
    res.content_type = 'application/atom+xml'
    res.body = atom.tostring(feed, pretty_print=True)
    res.etag = md5.new(res.body).hexdigest()
    if res.etag in req.if_none_match:
        return HTTPNotModified()
    return res

@wsgiapp
def post_entry(req):
    ## FIXME: should conditional request headers be handled here at
    ## all?
    atom_entry = atom.ATOM(req.body)
    assert atom_entry.tag == '{%s}entry' % atom.atom_ns
    if req.config.clean_html:
        clean_html(atom_entry)
    if atom_entry.updated is None:
        atom_entry.updated = datetime.utcnow()
    entry = req.store.EntryClass(
        req.store, suggest_slug=req.headers.get('slug'),
        atom_entry=atom_entry)
    entry.save()
    slug = entry.slug
    res = req.response
    res.content_type = 'application/atom+xml; type=entry'
    res.body = str(entry)
    res.location = slug
    res.status = 201
    ## FIXME: should I set etag, last_modified?
    return res

def clean_html(entry):
    from lxml.html import clean
    from lxml.html import tostring
    cleaner = clean.Cleaner()
    for el in entry:
        if isinstance(el, atom.TextElement):
            strip_tag = el.type == 'html' and not el.text.startswith('<')
            try:
                html = el.html
            except AttributeError:
                continue
            cleaner(html)
            if strip_tag:
                html = tostring(html).split('>', 1)[1].rsplit('<', 1)[0]
            el.html = html

@wsgiapp
def post_media(req):
    slug = req.headers.get('slug')
    content_type = req.content_type
    media = req.store.MediaClass(
        req.store, suggest_slug=slug)
    media.create(content_type)
    slug = media.slug
    media.copy_file(req.body_file, req.content_length)
    atom_entry = atom.Element('entry', nsmap=atom.nsmap)
    atom_entry.updated = datetime.utcnow()
    atom_entry.title = slug or content_type.split('/')[-1]
    if not atom_entry.id:
        atom_entry.make_id()
    content = atom.Element('content')
    content.attrib['type'] = content_type
    content.attrib['src'] = 'media/'+slug
    atom_entry.append(content)
    link = atom.Element('link')
    link.rel='edit-media'
    link.href = 'media/'+slug
    atom_entry.append(link)
    entry = req.store.EntryClass(
        req.store, suggest_slug=slug, atom_entry=atom_entry)
    entry.save()
    media.entry = entry
    res = req.response
    res.content_type = 'application/atom+xml; type=entry'
    res.body = str(entry)
    res.location = entry.slug
    res.status = 201
    ## FIXME: Should I set ETag, Last-Modified?
    return res

@wsgiapp
def serve_service(req):
    res = req.response
    res.content_type = 'application/atomsvc+xml'
    title = req.config.feed_title or 'Main Feed'
    service = '''\
<service xmlns="http://www.w3.org/2007/app"
         xmlns:atom="http://www.w3.org/2005/Atom">
  <workspace>
    <atom:title>%(title)s</atom:title>
    <collection href="%(root)s">
      <atom:title>%(title)s</atom:title>
      <accept>*/*</accept>
      <accept>application/atom+xml;type=entry</accept>
    </collection>
  </workspace>
</service>
'''
    service = service % dict(root=html_escape(req.app_root),
                             title=html_escape(title))
    res.body = service
    return res

def check_conditional_headers(req, etag, last_modified):
    if (req.if_unmodified_since
        and req.if_unmodified_since < last_modified):
        return HTTPPreconditionFailed(
            "Precondition If-Unmodified-Since %s failed: "
            "last modified on %s"
            % (req.if_unmodified_since.strftime('%c'),
               last_modified.strftime('%c')))
    if etag not in req.if_match:
        return HTTPPreconditionFailed(
            "Precondition If-Match %s failed: "
            "current ETag %s"
            % (req.if_match, etag))
    return None

@wsgiapp
def serve_media(req):
    slug = req.path_info_pop()
    media = req.store.get_media(slug)
    fn = media.filename
    if not os.path.exists(fn):
        return HTTPNotFound(
            comment='in %s' % fn)
    app = FileApp(fn, content_type=media.content_type)
    app.update()
    res = check_conditional_headers(
        req, app.calculate_etag(),
        datetime.fromtimestamp(app.last_modified, UTC))
    if res is not None:
        return res
    if req.method == 'DELETE':
        media.delete()
        return HTTPNoContent()
    if req.method == 'PUT':
        media.copy_file(req.body_file, req.content_length)
        media.content_type = req.content_type
        return HTTPNoContent()
    if req.method not in ['GET', 'HEAD']:
        return HTTPMethodNotAllowed(
            headers=dict(Allow='GET,HEAD,DELETE,PUT'))
    return app
    
