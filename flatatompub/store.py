import os
import re
import uuid
from taggerclient import atom
import mimetypes

safe_slug_re = re.compile(r'^[a-z0-9_.-]+$', re.I)
unsafe_slug_re = re.compile(r'[^a-z0-9_.-]', re.I)
sep_re = re.compile(r'[ .]')

bad_slugs = ['service', 'media']

class Store(object):

    def __init__(self, data_dir):
        self.data_dir = data_dir
        self.media_dir = os.path.join(data_dir, 'media')
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir)
        if not os.path.exists(self.media_dir):
            os.makedirs(self.media_dir)

    def clear(self):
        for fn in os.listdir(self.data_dir):
            if fn == 'media':
                continue
            fn = os.path.join(self.data_dir, fn)
            os.unlink(fn)

    ############################################################
    ## Entry handling
    ############################################################

    def add_entry(self, entry, suggest_slug=None):
        """
        Adds the entry, returning the modified entry
        """
        slug = self.create_slug(suggest_slug, type='media')
        self.update_entry(entry, slug)
        return slug

    def set_slug(self, entry, slug):
        for el in entry.rel_links('edit'):
            el.getparent().remove(el)
        link = atom.Element('link')
        link.rel = 'edit'
        link.href = slug
        entry.append(link)

    def get_slug(self, entry):
        slugs = entry.rel_links('edit')
        if not slugs:
            return None
        return slugs[0].href

    def get_entry(self, slug):
        fn = self.get_filename(slug)
        if not os.path.exists(fn):
            raise KeyError(slug)
        f = open(fn, 'rb')
        try:
            return atom.ATOM(f.read())
        finally:
            f.close()

    def update_entry(self, entry, slug=None):
        if slug is None:
            fn = self.get_filename(entry)
        else:
            fn = self.get_filename(slug)
            self.set_slug(entry, slug)
        entry.update_edited()
        f = open(fn, 'wb')
        try:
            f.write(atom.tostring(entry))
        finally:
            f.close()

    def delete_entry(self, entry):
        if isinstance(entry, basestring):
            entry = self.get_entry(entry)
        links = entry.rel_links('edit-media')
        for link in links:
            media_slug = (link.href or '')
            if not media_slug.startswith('media/'):
                continue
            media_slug = media_slug[len('media/'):]
            fn = self.get_filename(media_slug, 'media')+'.entry-slug'
            if not os.path.exists(fn):
                continue
            f = open(fn)
            entry_slug = f.read()
            f.close()
            if entry_slug != self.get_slug(entry):
                continue
            self.delete_media(media_slug, delete_entry=False)
        fn = self.get_filename(entry)
        os.unlink(fn)

    def iter_entries(self, inorder=True):
        filenames = os.listdir(self.data_dir)
        if inorder:
            filenames.sort(key=lambda fn:
                           -os.path.getmtime(os.path.join(self.data_dir, fn)))
        for fn in filenames:
            if os.path.isdir(os.path.join(self.data_dir, fn)):
                continue
            try:
                self.assert_good_slug(fn)
            except ValueError:
                continue
            yield self.get_entry(fn)

    def get_feed(self):
        feed = atom.Element('feed')
        feed.title = 'Feed'
        for entry in self.iter_entries():
            feed.append(entry)
        return feed
        
    ############################################################
    ## Slug generation
    ############################################################

    def get_filename(self, entry, type='entry'):
        if not isinstance(entry, basestring):
            # an entry
            slug = entry.rel_links('edit')[0].href
        else:
            slug = entry
        self.assert_good_slug(slug)
        if type == 'media':
            base = self.media_dir
        elif type == 'entry':
            base = self.data_dir
        else:
            assert 0, 'Unknown type: %r' % type
        return os.path.join(base, slug)

    def assert_good_slug(self, slug):
        if not slug:
            raise ValueError(
                "Empty slug")
        if len(slug) > 200:
            raise ValueError(
                "Slug too big: %r" % slug)
        if not safe_slug_re.search(slug):
            raise ValueError(
                "Bad slug: %r" % slug)
        if slug.lower() in bad_slugs:
            raise ValueError(
                "Reserved slug: %r" % slug)
        
    def create_slug(self, suggest_slug=None, type='entry', ext='.entry'):
        if suggest_slug:
            suggest_slug = suggest_slug.split('.', 1)[0]
            suggest_slug = sep_re.sub(' ', suggest_slug)
            suggest_slug = unsafe_slug_re.sub('', suggest_slug)
            if not suggest_slug.endswith(ext):
                suggest_slug += ext
            try:
                self.assert_good_slug(suggest_slug)
            except ValueError:
                pass
            else:
                fn = self.get_filename(suggest_slug, type=type)
                if not os.path.exists(fn):
                    return suggest_slug
        slug = str(uuid.uuid4())
        slug += ext
        return slug

    ############################################################
    ## Media handling
    ############################################################

    def add_media(self, content_type, body, length, suggest_slug=None):
        ext = mimetypes.guess_extension(content_type.split(';')[0])
        if not ext:
            ext = '.bin'
        if ext == '.jpe':
            # grrr... stupid mimetypes module
            ext = '.jpg'
        slug = self.create_slug(suggest_slug, type='media', ext=ext)
        self.update_media(slug, content_type, body, length)
        return slug

    def update_media(self, slug, content_type, body, length):
        fn = self.get_filename(slug, 'media')
        f = open(fn, 'wb')
        while length:
            chunk = body.read(min(length, 4096))
            length -= len(chunk)
            f.write(chunk)
        f.close()
        f = open(fn + ".content-type", 'w')
        f.write(content_type)
        f.close()
        if os.path.exists(fn+'.entry-slug'):
            f = open(fn+'.entry-slug')
            entry_slug = f.read().strip()
            f.close()
            entry = self.get_entry(entry_slug)
            # To set edited date
            self.update_entry(entry)

    def delete_media(self, slug, delete_entry=True):
        fn = self.get_filename(slug, 'media')
        os.unlink(fn)
        os.unlink(fn+'.content-type')
        if os.path.exists(fn+'.entry-slug'):
            f = open(fn+'.entry-slug')
            entry_slug = f.read().strip()
            f.close()
            os.unlink(fn+'.entry-slug')
            if delete_entry:
                req.store.delete_entry(entry_slug)
