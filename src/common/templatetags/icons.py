"""
Icon template tags for consistent inline SVG icon rendering.

Renders self-contained SVG icons (no external dependencies) with consistent
sizing/color classes and accessibility attributes. Icon SVGs live in
``common/templates/icons/<name>.svg``.

Usage:
    {% load icons %}
    {% icon "plus" size="md" color="primary" aria_label="Add item" %}
    {% icon "chevron-up" %}
"""
from django import template
from django.template.loader import get_template
from django.utils.html import escape
from django.utils.safestring import mark_safe

register = template.Library()

# Allow-listed icon names (prevents arbitrary template inclusion via {% icon %}).
# This is the union of the SVGs shipped under common/templates/icons/.
AVAILABLE_ICONS = {
    'audio-disabled',
    'audio-enabled',
    'bold',
    'book',
    'book-open',
    'calendar',
    'camera',
    'cancel',
    'check',
    'check-circle',
    'chevron-double-left',
    'chevron-double-right',
    'chevron-down',
    'chevron-left',
    'chevron-right',
    'chevron-up',
    'circle-slash',
    'clock',
    'clock-rotate',
    'close',
    'cloud',
    'cloud-check',
    'code',
    'collection',
    'copy',
    'delete',
    'disabled',
    'document',
    'document-list',
    'dollar-sign',
    'door-exit',
    'download',
    'edit',
    'exclamation-circle',
    'exclamation-triangle',
    'eye',
    'eye-off',
    'forecast',
    'gear',
    'globe',
    'grid',
    'group',
    'heading',
    'history',
    'home',
    'house',
    'indent',
    'info-circle',
    'italic',
    'key',
    'keyboard',
    'layers',
    'lightbulb',
    'link',
    'list-ol',
    'list-ul',
    'lock',
    'magnifying-glass-plus',
    'map-pin',
    'minus-circle',
    'moon',
    'move',
    'outdent',
    'path',
    'pause',
    'pencil',
    'play',
    'plug',
    'plus',
    'question-circle',
    'quote-left',
    'rocket',
    'rotate',
    'save',
    'settings',
    'shield',
    'sleep',
    'star',
    'sync',
    'tasks',
    'times-circle',
    'trash',
    'triangle-right',
    'undo',
    'unlink',
    'unlock',
    'upload',
    'user',
    'video',
    'view',
    'warning',
    'x',
    'zoom',
}

# Available sizes (styled by the front-end CSS via the icon-<size> class).
ICON_SIZES = {'sm', 'md', 'lg', 'xl', 'xxl', 'xxxl', 'fluid'}

# Available semantic colors (matching CSS variables via the icon-<color> class).
ICON_COLORS = {
    'primary',
    'secondary',
    'success',
    'warning',
    'error',
    'muted',
}


@register.simple_tag
def icon(name, size='md', color=None, aria_label=None, title=None, css_class=''):
    """
    Render an inline SVG icon with consistent styling and accessibility.

    Args:
        name (str): Icon name (must be in AVAILABLE_ICONS)
        size (str): Icon size (see ICON_SIZES). Default: 'md'
        color (str): Semantic color (see ICON_COLORS). Default: None
        aria_label (str): Accessibility label. If provided, the icon is
                         meaningful (role="img"); if None it is decorative
                         (aria-hidden="true").
        title (str): Tooltip text. Default: None
        css_class (str): Additional CSS classes. Default: ''

    Returns:
        SafeString: Rendered SVG icon HTML

    Raises:
        template.TemplateSyntaxError: If the icon name is not available
    """
    if name not in AVAILABLE_ICONS:
        raise template.TemplateSyntaxError(
            f'Icon "{name}" is not available. '
            f'Available icons: {", ".join(sorted(AVAILABLE_ICONS))}'
        )

    if size not in ICON_SIZES:
        size = 'md'  # Default fallback

    if color and color not in ICON_COLORS:
        color = None  # Invalid color, use default

    classes = ['icon', f'icon-{size}']
    if color:
        classes.append(f'icon-{color}')
    if css_class:
        classes.append(css_class)
    class_attr = ' '.join(classes)

    # Build accessibility attributes. Dynamic values are escaped; the assembled
    # attribute string is then marked safe so it is not double-escaped when
    # inserted into the SVG template via {{ accessibility_attrs }}.
    accessibility_attrs = []
    if aria_label:
        accessibility_attrs.append(f'aria-label="{escape(aria_label)}"')
        accessibility_attrs.append('role="img"')
    else:
        accessibility_attrs.append('aria-hidden="true"')
    if title:
        accessibility_attrs.append(f'title="{escape(title)}"')
    accessibility_str = mark_safe(' '.join(accessibility_attrs))

    try:
        icon_template = get_template(f'icons/{name}.svg')
        rendered_icon = icon_template.render({
            'class_attr': class_attr,
            'accessibility_attrs': accessibility_str,
        })
        return mark_safe(rendered_icon)

    except template.TemplateDoesNotExist:
        # Fallback if the icon SVG is missing.
        return mark_safe(
            f'<span class="{class_attr}" {accessibility_str}>[{name}]</span>'
        )


@register.simple_tag
def icon_list():
    """Return a sorted list of available icon names (for docs/debugging)."""
    return sorted(AVAILABLE_ICONS)


@register.filter
def has_icon(name):
    """Template filter: True if the icon name is available."""
    return name in AVAILABLE_ICONS
