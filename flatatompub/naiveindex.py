"""
Interface for interfacing, coupled with a very naive/slow index over content
"""

class Index(object):

    def __init__(self):
        # This one does nothing
        pass

    ## Validation/rewriting:

    def rewrite_entry(self, slug, entry):
        """
        This can raise an HTTPException, or rewrite the entry (e.g.,
        scrub HTML content).

        The slug cannot be modified
        """
        return entry

    ## Events:

    def entry_added(self, slug, entry):
        """
        Called whenever an entry is added to the store.
        """
        pass

    def entry_updated(self, slug, entry):
        """
        Called whenever an entry is updated.
        """
        pass

    def entry_deleted(self, slug, entry):
        """
        Called whenever an entry is deleted from the store.  This is
        called *before* an entry is deleted.
        """
        pass

    ## FIXME: should have:
    # media_added
    # media_updated
    # media_deleted

    def clear(self, store):
        """
        Called before the store is completely cleared.
        """
        pass

    ## Queryies:

    def gdata_query(self, gdata, store):
        """
        Returns ``(gdata, slug_list)``.  slug_list is an ordered list
        of slugs for the given gdata query.  If gdata is None, then
        this is the list of slugs served.  Otherwise it is a GData
        query object (perhaps the one passed in, but not necessary),
        with which any entries will be further filtered.  This can be
        used to implement partial queries, letting the more primitive
        filtering be used on the partial set.

        You should not do paging as part of this (max_results,
        start_index).
        """
        return (gdata, store.entry_slugs())

    def most_recent(self, store, start_index, length):
        """
        Returns ``(total_length, [slugs...])``, the list of most
        recent slugs, with the given ``start_index`` offset (often 0)
        and length.

        length may be None, meaning unlimited length
        """
        slugs = store.entry_slugs()
        if length is None:
            # Unlimited
            return (len(slugs), slugs[start_index:])
        else:
            return (len(slugs), slugs[start_index:start_index+length])

    def categories(self):
        """
        Return the list of applicable categories in the form
        ``[(scheme, term), ...]`` (scheme may be None), or simply None
        if any category is accepted.
        """
        return None

    def accept_media(self):
        """
        Return a list of media types, like ``['image/*']``, or None if
        any type of media is accepted.
        """
        return None
    
    
def make_index(global_conf):
    return Index()
