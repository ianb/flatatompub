import os
from datetime import datetime
from webob import Request, Response, html_escape, UTC
from webob.exc import *
from flatatompub.dec import wsgiapp, bindery
from taggerclient import atom
from paste.fileapp import FileApp

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
        atom_entry = atom.ATOM(req.read_body())
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

@wsgiapp
def serve_feed(req):
    feed = atom.Element('feed')
    feed.title = 'Feed'
    try:
        pos = int(req.queryvars.get('pos', 0))
        if pos < 0:
            raise ValueError("pos must not be negative")
    except ValueError, e:
        return HTTPBadRequest(
            "pos value is invalid: %s" % e)
    limit = req.store.page_limit
    if pos:
        prev_link = atom.Element('link')
        prev_pos = max(pos - (limit or 10), 0)
        prev_link.href = req.path_url + '?pos=%s' % prev_pos
        prev_link.rel = 'previous'
        feed.append(prev_link)
    slugs = req.store.entry_slugs()
    if len(slugs) > pos+limit:
        next_link = atom.Element('link')
        next_pos = pos + limit
        next_link.href = req.path_url + '?pos=%s' % next_pos
        next_link.rel = 'next'
        feed.append(next_link)
    if len(slugs) > limit:
        first_link = atom.Element('link')
        first_link.rel = 'first'
        first_link.href = req.path_url
        feed.append(first_link)
        last_pos = len(slugs) - (len(slugs)%limit)
        if last_pos == len(slugs):
            last_pos -= limit
        last_link = atom.Element('link')
        last_link.href = req.path_url + '?pos=%s' % last_pos
        last_link.rel = 'last'
        feed.append(last_link)
    slugs = slugs[pos:pos+limit]
    for slug in slugs:
        entry = req.store.get_entry(slug)
        feed.append(entry.atom_entry)
    res = req.response
    res.content_type = 'application/atom+xml'
    res.body = atom.tostring(feed)
    return res

@wsgiapp
def post_entry(req):
    ## FIXME: should conditional request headers be handled here at
    ## all?
    atom_entry = atom.ATOM(req.read_body())
    assert atom_entry.tag == '{%s}entry' % atom.atom_ns
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

@wsgiapp
def post_media(req):
    entry = atom.Element('entry')
    slug = req.headers.get('slug')
    content_type = req.content_type
    media = req.store.MediaClass(
        req.store, suggest_slug=slug)
    media.create(content_type)
    slug = media.slug
    media.copy_file(req.body, req.content_length)
    atom_entry = atom.Element('entry')
    atom_entry.updated = datetime.now()
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
    service = '''\
<service xmlns="http://www.w3.org/2007/app"
         xmlns:atom="http://www.w3.org/2005/Atom">
  <workspace>
    <atom:title>Main Site</atom:title>
    <collection href="%s">
      <atom:title>Main Site</atom:title>
      <accept>*/*</accept>
      <accept>application/atom+xml;type=entry</accept>
    </collection>
  </workspace>
</service>
'''
    service = service % req.app_root
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
        media.copy_file(req.body, req.content_length)
        media.content_type = req.content_type
        return HTTPNoContent()
    if req.method not in ['GET', 'HEAD']:
        return HTTPMethodNotAllowed(
            headers=dict(Allow='GET,HEAD,DELETE,PUT'))
    # FIXME: damn, I can't control etag, etc here
    return app

    
