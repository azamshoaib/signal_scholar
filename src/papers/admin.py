"""Django admin registrations for the core domain models.

See GitHub issue #7. `Paper`, `Author`, `Institution`, `Venue`, and
`Citation` get top-level registrations with `list_display`,
`search_fields`, and (where a field has a small number of distinct
values) `list_filter`, so ingested data can be inspected and manually
corrected without writing raw queries.

`PaperAuthorship` (the `Paper`/`Author` through-model added by #5) is
deliberately *not* given its own top-level registration — it's exposed
as a `TabularInline` on `PaperAdmin` instead, so an author's `position`
on a specific paper is edited in the context of that paper rather than
as an orphaned row in a standalone changelist.
"""

from django.contrib import admin

from papers.models import Author, Citation, Institution, Paper, PaperAuthorship, Venue


class PaperAuthorshipInline(admin.TabularInline):
    model = PaperAuthorship
    extra = 1


@admin.register(Paper)
class PaperAdmin(admin.ModelAdmin):
    list_display = ["title", "publication_year", "doi", "venue"]
    search_fields = ["title"]
    list_filter = ["venue"]
    inlines = [PaperAuthorshipInline]


@admin.register(Author)
class AuthorAdmin(admin.ModelAdmin):
    list_display = ["name", "institution"]
    search_fields = ["name"]
    list_filter = ["institution"]


@admin.register(Institution)
class InstitutionAdmin(admin.ModelAdmin):
    list_display = ["name"]
    search_fields = ["name"]


@admin.register(Venue)
class VenueAdmin(admin.ModelAdmin):
    list_display = ["name"]
    search_fields = ["name"]


@admin.register(Citation)
class CitationAdmin(admin.ModelAdmin):
    list_display = ["citing_paper", "cited_paper"]
    search_fields = ["citing_paper__title", "cited_paper__title"]
