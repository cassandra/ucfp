# Coding Patterns

Concrete, reusable Django recipes. The examples use generic models (`Article`,
`Comment`) purely to illustrate the pattern -- they are not part of this project.
For the *syntactic* conventions these snippets follow, see
[Coding Standards](coding-standards.md); for higher-level architecture and the
manager/singleton philosophy, see [Backend Guidelines](../backend/backend-guidelines.md).

## Conventions Checklist

- [ ] New modal dialogs extend the `ModalView` base and a base template in `ucfp/templates/modals`.
- [ ] The `antinode` framework (`common/antinode.py`, `static/js/antinode.js`) is used for async/ajax content updates and modals.
- [ ] Javascript uses jQuery for DOM manipulation.
- [ ] Minimal business logic in templates: the view prepares the context the template needs.
- [ ] Minimal business logic in Django views: delegate to helper/manager classes.
- [ ] No ORM calls in template tags.
- [ ] Only internal system icons are used (no Font Awesome). Pick an existing icon or add one.

## Model Patterns

### Abstract Base Models

Use abstract models for common fields:

```python
class TimestampedModel( models.Model ):
    created_at = models.DateTimeField( auto_now_add = True )
    updated_at = models.DateTimeField( auto_now = True )

    class Meta:
        abstract = True

class Article( TimestampedModel ):
    title = models.CharField( max_length = 200 )
    # inherits created_at / updated_at
```

### Custom Model Managers

Encapsulate common query patterns on a manager rather than repeating filters:

```python
class ArticleManager( models.Manager ):
    def published( self ):
        return self.filter( is_published = True )

    def with_comments( self ):
        return self.filter( comments__isnull = False ).distinct()

class Article( TimestampedModel ):
    objects = ArticleManager()
    # ... fields ...
```

### Model Properties and Methods

Put computed fields and business logic on the model, not in the view:

```python
class Article( TimestampedModel ):
    @property
    def is_recent( self ):
        cutoff = datetimeproxy.now() - timedelta( days = 7 )
        return bool( self.created_at >= cutoff )

    def latest_comment( self ):
        return self.comments.order_by( '-created_at' ).first()
```

## View Patterns

### Class-Based View Mixins

Reuse cross-view context through a mixin:

```python
class SectionContextMixin:
    def get_context_data( self, **kwargs ):
        context = super().get_context_data( **kwargs )
        context['current_section'] = self.get_current_section()
        return context

    def get_current_section( self ):
        return self.request.session.get( 'section', 'home' )

class ArticleListView( SectionContextMixin, ListView ):
    model = Article

    def get_queryset( self ):
        return Article.objects.published()
```

### Form Processing

Standard form handling with explicit error paths:

```python
class ArticleUpdateView( UpdateView ):
    model = Article
    form_class = ArticleForm

    def form_valid( self, form ):
        try:
            article = form.save( commit = False )
            article.updated_by = self.request.user
            article.save()
            messages.success( self.request, f"'{article.title}' updated." )
            return super().form_valid( form )
        except ValidationError as error:
            form.add_error( None, error.message )
            return self.form_invalid( form )

    def get_success_url( self ):
        if 'save_and_continue' in self.request.POST:
            return reverse( 'article_edit', kwargs = { 'pk': self.object.pk } )
        return reverse( 'article_list' )
```

### Dual-Mode (Ajax + Full-Page) Views

A view reached both by a normal request and by an `antinode` ajax call returns
the right response for each. Detect the ajax case and branch:

```python
class ArticlePublishView( View ):
    def post( self, request, *args, **kwargs ):
        article = get_object_or_404( Article, id = kwargs['article_id'] )
        article.publish()

        is_async = bool( request.headers.get('X-Requested-With') == 'XMLHttpRequest' )
        if is_async:
            return JsonResponse( { 'status': 'success', 'article_id': article.id } )

        messages.success( request, f"'{article.title}' published." )
        return redirect( 'article_detail', pk = article.id )
```

See [Testing Patterns](../testing/testing-patterns.md) for how the five view
shapes (sync HTML, sync JSON, async HTML, async JSON, dual-mode) are tested.

## Custom Template Tags and Filters

Inclusion tags render a reusable fragment; keep ORM work in the view, not the tag:

```python
# In templatetags/article_tags.py
from django import template

register = template.Library()

@register.inclusion_tag( 'article/panes/byline.html' )
def article_byline( article ):
    return { 'author': article.author, 'published': article.is_published }

@register.simple_tag
def article_url( article, action ):
    return reverse( 'article_action', kwargs = { 'pk': article.id, 'action': action } )

@register.filter
def comment_count_label( article ):
    count = article.comments.count()
    return f"{count} comment{'s' if count != 1 else ''}"
```

## Django Admin Customization

```python
@admin.register( Article )
class ArticleAdmin( admin.ModelAdmin ):
    list_display = [ 'title', 'author', 'is_published', 'updated_at' ]
    list_filter = [ 'is_published', 'created_at' ]
    search_fields = [ 'title' ]
    readonly_fields = [ 'created_at', 'updated_at' ]

    def get_queryset( self, request ):
        return super().get_queryset( request ).select_related( 'author' )
```

## Signal Patterns

Use signals for cross-cutting reactions to model lifecycle events:

```python
# In signals.py
@receiver( post_save, sender = Article )
def article_post_save( sender, instance, created, **kwargs ):
    if created:
        SearchIndex.objects.index( instance )
    cache.delete( f'article:{instance.id}' )

@receiver( pre_delete, sender = ArticleImage )
def cleanup_article_image( sender, instance, **kwargs ):
    if instance.image and os.path.isfile( instance.image.path ):
        os.remove( instance.image.path )
```

## Migration Patterns

### Data Migrations

Use `apps.get_model()` (the historical model), never the imported model:

```python
def populate_slugs( apps, schema_editor ):
    Article = apps.get_model( 'article', 'Article' )
    for article in Article.objects.filter( slug = '' ):
        article.slug = slugify( article.title )
        article.save( update_fields = [ 'slug' ] )

class Migration( migrations.Migration ):
    dependencies = [ ( 'article', '0003_article_slug' ) ]
    operations = [ migrations.RunPython( populate_slugs, migrations.RunPython.noop ) ]
```

### Schema Migrations with Indexes

```python
class Migration( migrations.Migration ):
    operations = [
        migrations.AddIndex(
            model_name = 'comment',
            index = models.Index(
                fields = [ 'article', '-created_at' ],
                name = 'comment_article_time_idx',
            ),
        ),
    ]
```

## Related Documentation
- Syntactic conventions: [Coding Standards](coding-standards.md)
- Architecture and managers: [Backend Guidelines](../backend/backend-guidelines.md)
- View testing: [Testing Patterns](../testing/testing-patterns.md)
