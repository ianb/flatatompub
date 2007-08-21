import os
import re
import md5
from taggerclient import atom
import mimetypes
from itertools import count
from datetime import datetime
from webob import UTC

safe_slug_re = re.compile(r'^[a-z0-9_.-]+$', re.I)
unsafe_slug_re = re.compile(r'[^a-z0-9_.-]', re.I)
sep_re = re.compile(r'[ .]')

bad_slugs = ['service', 'media']

last_id_creation = None
id_counter = count(1)

def create_slug():
    global last_id_creation, id_counter
    create_date = datetime.utcnow().strftime('%Y-%m-%d')
    if last_id_creation != create_date:
        last_id_creation = create_date
        # Reset counter
        id_counter = count(1)
    while 1:
        fn = create_date + '-%s' % id_counter.next()
        yield fn

def ensure_exists(dir):
    if not os.path.exists(dir):
        print 'Creating directory %s' % dir
        os.makedirs(dir)

def clear_files(dir):
    for fn in os.listdir(dir):
        fn = os.path.join(dir, fn)
        if not os.path.isdir(fn):
            os.unlink(fn)

def ext_for_mimetype(type):
    ext = mimetypes.guess_extension(type.split(';')[0])
    if not ext:
        ext = '.bin'
    if ext == '.jpe':
        # grrr... stupid mimetypes module
        ext = '.jpg'
    return ext

def copyfile(infile, outfile, length):
    while length:
        chunk = infile.read(min(length, 4096))
        if not chunk:
            break
        length -= len(chunk)
        outfile.write(chunk)

class StoredEntry(object):

    def __init__(self, store, slug=None, suggest_slug=None,
                 atom_entry=None):
        self.store = store
        self.slug = slug
        if slug is not None and suggest_slug is not None:
            raise TypeError(
                "You cannot give a suggest_slug and slug argument")
        self.suggest_slug = suggest_slug
        if atom_entry is not None:
            self.atom_entry = atom_entry
        else:
            if slug is not None:
                self.atom_entry = self.store.load_entry(self.slug)
            else:
                self.atom_entry = None

    def save(self):
        created = False
        if self.slug is None:
            self.slug = self.store.create_slug(self.suggest_slug, 'entry', '')
            self.suggest_slug = None
            created = True
        self.atom_entry.update_edited()
        self.confirm_slug()
        if created:
            meth = self.store.index.entry_added
        else:
            meth = self.store.index.entry_updated
        new_entry = self.store.index.rewrite_entry(self.slug, self.atom_entry)
        if new_entry is not None:
            self.atom_entry = new_entry
        meth(self.slug, self.atom_entry)
        self.store.save_entry(self.slug, self.atom_entry)

    def confirm_slug(self):
        found = False
        for link in self.atom_entry.rel_links('edit'):
            if link.href != self.slug:
                link.getparent().remove(link)
            else:
                found = True
        if not found:
            link = atom.Element('link')
            link.rel = 'edit'
            link.href = self.slug
            self.atom_entry.append(link)

    def delete(self, delete_media=True):
        if delete_media:
            for media in self.media:
                media.delete(delete_entry=False)
        self.store.index.entry_deleted(self.slug, self.atom_entry)
        self.store.delete_entry(self.slug)

    @property
    def etag(self):
        return self.store.etag(self.slug, 'entry')

    @property
    def last_modified(self):
        return self.store.last_modified(self.slug, 'entry')

    @property
    def media(self):
        result = []
        for link in self.atom_entry.rel_links('edit-media'):
            media = self.store.get_media_by_link(link.href)
            if media is not None and media.entry.slug == self.slug:
                result.append(media)
        return result

    def __str__(self):
        return atom.tostring(self.atom_entry)

class StoredMedia(object):

    def __init__(self, store, slug=None, suggest_slug=None,
                 entry=None):
        self.store = store
        self.slug = slug
        if slug is not None and suggest_slug is not None:
            raise TypeError(
                "You cannot give a suggest_slug and slug argument")
        self.suggest_slug = suggest_slug
        if entry is not None:
            self.entry = entry

    def create(self, content_type):
        if self.slug is None:
            ext = ext_for_mimetype(content_type)
            self.slug = self.store.create_slug(self.suggest_slug, 'media', ext)
            self.suggest_slug = None
        self.store.touch_media(self.slug)
        self.content_type = content_type

    def copy_file(self, fp, content_length=None):
        out = self.store.open_media(self.slug, 'wb')
        if content_length is None:
            shutil.copyfileobj(fp, out)
        else:
            copyfile(fp, out, content_length)
        if self.entry:
            # Update mtime and edited time
            self.entry.save()

    @property
    def file(self):
        return self.store.open_media(self.slug, 'rb')

    @property
    def filename(self):
        return self.store.get_filename(self.slug, 'media')

    def entry__get(self):
        entry_slug = self.store.get_media_entry(self.slug)
        if not entry_slug:
            return None
        return self.store.get_entry(entry_slug)
    def entry__set(self, value):
        if not isinstance(value, basestring):
            value = value.slug
        self.store.set_media_entry(self.slug, value)
    entry = property(entry__get, entry__set)

    def content_type__get(self):
        return self.store.get_media_content_type(self.slug)
    def content_type__set(self, value):
        self.store.set_media_content_type(self.slug, value)
    content_type = property(content_type__get, content_type__set)

    def delete(self, delete_entry=True):
        if delete_entry:
            self.entry.delete(delete_media=False)
        self.store.delete_media(self.slug)

    @property
    def etag(self):
        return self.store.etag(self.slug, 'media')

    @property
    def last_modified(self):
        return self.store.last_modified(self.slug, 'media')

class Store(object):

    EntryClass = StoredEntry
    MediaClass = StoredMedia

    def __init__(self, data_dir, media_dir=None, page_limit=None, index=None):
        if index is None:
            raise TypeError("You must provide an index")
        self.index = index
        data_dir = os.path.normpath(data_dir)
        if media_dir is None:
            media_dir = os.path.join(data_dir, 'media')
        self.data_dir = data_dir
        self.media_dir = media_dir
        ensure_exists(self.data_dir)
        ensure_exists(self.media_dir)
        self.page_limit = page_limit

    def get_entry(self, slug):
        return self.EntryClass(
            self, slug, atom_entry=self.load_entry(slug))

    def get_media(self, slug):
        return self.MediaClass(self, slug)

    def clear(self):
        self.index.clear(self)
        clear_files(self.data_dir)
        clear_files(self.media_dir)

    def create_slug(self, suggest, type, ext):
        if suggest:
            suggest = suggest.split('.', 1)[0]
            suggest = sep_re.sub(' ', suggest)
            suggest = unsafe_slug_re.sub('', suggest)
            suggest += ext
            try:
                self.assert_good_slug(suggest)
            except ValueError:
                pass
            else:
                fn = self.get_filename(suggest, type)
                if not os.path.exists(fn):
                    return suggest
        for slug in create_slug():
            slug += ext
            fn = self.get_filename(slug, type)
            if not os.path.exists(fn):
                return slug

    def get_filename(self, slug, type):
        if type == 'entry':
            base = self.data_dir
        elif type == 'media':
            base = self.media_dir
        else:
            assert 0, 'bad type: %r' % type
        self.assert_good_slug(slug)
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

    def etag(self, slug, type):
        fn = self.get_filename(slug, type)
        if os.path.getsize(fn) > 4096:
            # Large files get a simple mtime + bytes + path
            etag = '%s-%s-%s' % (
                os.path.getmtime(fn),
                os.path.getsize(fn),
                hash(fn))
            return etag
        else:
            f = open(fn, 'rb')
            h = md5.new(f.read())
            f.close()
            return h.hexdigest()

    def last_modified(self, slug, type):
        fn = self.get_filename(slug, type)
        t = os.path.getmtime(fn)
        t = datetime.fromtimestamp(t, UTC)
        return t

    def load_entry(self, slug):
        fn = self.get_filename(slug, 'entry')
        if not os.path.exists(fn):
            raise KeyError(fn)
        f = open(fn, 'rb')
        try:
            v = atom.ATOM(f.read())
            assert isinstance(v, atom.Entry)
            return v
        finally:
            f.close()

    def save_entry(self, slug, atom_entry):
        fn = self.get_filename(slug, 'entry')
        f = open(fn, 'wb')
        try:
            f.write(atom.tostring(atom_entry))
        finally:
            f.close()

    def delete_entry(self, slug):
        fn = self.get_filename(slug, 'entry')
        os.unlink(fn)

    def get_media_by_link(self, link):
        if 'media/' not in link:
            # Not recognized
            return None
        pos = link.find('media/') + len('media/')
        slug = link[pos:]
        media = self.get_media(slug)
        return media

    def touch_media(self, slug):
        fn = self.get_filename(slug, 'media')
        f = open(fn, 'a')
        f.close()

    def touch_entry(self, slug):
        fn = self.get_filename(slug, 'entry')
        f = open(fn, 'a')
        f.close()

    def open_media(self, slug, mode):
        fn = self.get_filename(slug, 'media')
        return open(fn, mode)

    def get_media_entry(self, slug):
        fn = self.get_filename(slug, 'media') + '.entry-slug'
        if not os.path.exists(fn):
            return None
        f = open(fn, 'r')
        try:
            return f.read().strip()
        finally:
            f.close()

    def set_media_entry(self, media_slug, entry_slug):
        fn = self.get_filename(media_slug, 'media') + '.entry-slug'
        f = open(fn, 'w')
        f.write(entry_slug)
        f.close()

    def get_media_content_type(self, slug):
        fn = self.get_filename(slug, 'media') + '.content-type'
        if not os.path.exists(fn):
            return mimetypes.guess_type(slug)[0]
        f = open(fn)
        try:
            return f.read().strip()
        finally:
            f.close()

    def set_media_content_type(self, slug, content_type):
        fn = self.get_filename(slug, 'media') + '.content-type'
        f = open(fn, 'w')
        f.write(content_type)
        f.close()

    def delete_media(self, slug):
        base = self.get_filename(slug, 'media')
        for ext in ['.content-type', '.entry-slug', '']:
            fn = base + ext
            if os.path.exists(fn):
                os.unlink(fn)

    ############################################################
    ## Feeds
    ############################################################

    def entry_slugs(self):
        filenames = [
            fn for fn in os.listdir(self.data_dir)
            if not os.path.isdir(os.path.join(self.data_dir, fn))]
        filenames.sort(key=lambda fn:
                       -os.path.getmtime(os.path.join(self.data_dir, fn)))
        return filenames

    def most_recent(self):
        most_recent = 0
        for fn in os.listdir(self.data_dir):
            fn = os.path.join(self.data_dir, fn)
            if os.path.isdir(fn):
                continue
            most_recent = max(os.path.getmtime(fn), most_recent)
        return datetime.fromtimestamp(most_recent, UTC)
