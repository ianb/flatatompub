import os
from datetime import datetime
from webob import Request, Response, html_escape
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
    except KeyError:
        return HTTPNotFound()
    store = req.store
    if req.method == 'DELETE':
        store.delete_entry(req.slug)
        return HTTPNoContent()
    elif req.method == 'PUT':
        new_entry = atom.ATOM(req.read_body())
        assert new_entry.tag == '{%s}entry' % atom.atom_ns
        store.update_entry(new_entry, req.slug)
        entry = store.get_entry(req.slug)
    res = req.response
    res.content_type = 'application/atom+xml; type=entry'
    res.body = atom.tostring(entry)
    return res

@wsgiapp
def serve_feed(req):
    feed = req.store.get_feed()
    res = req.response
    res.content_type = 'application/atom+xml'
    res.body = atom.tostring(feed)
    return res

@wsgiapp
def post_entry(req):
    new_entry = atom.ATOM(req.read_body())
    assert new_entry.tag == '{%s}entry' % atom.atom_ns
    slug = req.store.add_entry(new_entry, suggest_slug=req.headers.get('slug'))
    res = req.response
    res.content_type = 'application/atom+xml; type=entry'
    res.body = atom.tostring(new_entry)
    res.location = slug
    res.status = 201
    return res

@wsgiapp
def post_media(req):
    entry = atom.Element('entry')
    slug = req.headers.get('slug')
    content_type = req.content_type
    if req.headers.get('slug'):
        entry.title = slug or content_type.split('/')[-1]
        if not entry.id:
            entry.make_id()
        entry.updated = datetime.now()
    slug = req.store.add_media(content_type, req.body, req.content_length,
                               slug)
    content = atom.Element('content')
    content.attrib['type'] = content_type
    content.attrib['src'] = 'media/'+slug
    entry.append(content)
    link = atom.Element('link')
    link.rel='edit-media'
    link.href = 'media/'+slug
    entry.append(link)
    entry_slug = req.store.add_entry(entry, slug)
    media_fn = req.store.get_filename(slug, 'media')
    f = open(media_fn+'.entry-slug', 'w')
    f.write(entry_slug)
    f.close()
    res = req.response
    res.content_type = 'application/atom+xml; type=entry'
    res.body = atom.tostring(entry)
    res.location = entry_slug
    res.status = 201
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

@wsgiapp
def serve_media(req):
    slug = req.path_info_pop()
    fn = req.store.get_filename(slug, 'media')
    if not os.path.exists(fn):
        return HTTPNotFound(
            comment='in %s' % fn)
    if req.method == 'DELETE':
        store.delete_media(slug)
        return HTTPNoContent()
    if req.method == 'PUT':
        req.store.update_media(slug, req.content_type, req.body, req.content_length)
        return HTTPNoContent()
    ct_fn = fn + '.content-type'
    f = open(ct_fn, 'r')
    content_type = f.read().strip()
    f.close()
    app = FileApp(fn, content_type=content_type)
    return app

    
