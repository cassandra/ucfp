# Style Guidelines

## Design Targets

**Primary**: Tablet landscape mode with a touch screen
**Secondary**: Laptop / desktop
**Minimum**: Phone landscape mode (not portrait)

These are the defaults inherited from the source projects; adjust them to your
own product's primary surface when adapting the template.

## Responsive Design

### Breakpoints
Bootstrap 4 breakpoints with a tablet-first approach:
- **768px+ (md)**: primary target -- tablets
- **992px+ (lg)**: desktops
- **1200px+ (xl)**: large desktops

### Touch-Friendly Requirements
- **Minimum touch target**: 44x44px for all interactive elements
- **No hover dependencies**: use click/tap interactions
- **Adequate spacing**: between clickable elements
- **Standard gestures**: swipe, pinch-zoom where appropriate

## Color System and Theming

Theme through **CSS custom properties** defined in the `:root` block of
`src/ucfp/static/css/main.css`, rather than hard-coded colors scattered across
rules. This is the one place to restyle the project's palette.

A common pattern for status is a traffic-light scale (e.g. active / recent /
idle / unknown) expressed as custom properties and applied via a small set of
state classes -- define the variables once and reference them everywhere.

## Form Styling

### Touch Optimization
- **Minimum height**: 44px for form controls
- **Font size**: 16px minimum (prevents iOS zoom)
- **Spacing**: generous margin between form groups

## Performance Guidelines

### Animation Best Practices
- **Use**: `opacity` and `transform` for smooth, compositor-friendly animations
- **Avoid**: `transition: all` -- specify properties explicitly
- **Timing**: ~0.3s standard transition duration

### Accessibility Features
- **Focus indicators**: a visible outline with offset on focusable controls
- **High-contrast support**: honor `prefers-contrast: high`
- **Keyboard navigation**: visible focus states throughout

## CSS Organization

- A single `src/ucfp/static/css/main.css` holds the theme palette, the icon
  system, and Bootstrap overrides. Add a separate CSS file (registered in Django
  Pipeline in `src/ucfp/settings/base.py`) only for a special-purpose,
  high-volume module.
- Organize by component, not by page; extend Bootstrap classes rather than
  overriding them; use BEM naming where appropriate.

## Related Documentation
- [Icon System](icon-system.md)
- [Frontend Guidelines](frontend-guidelines.md)
- [Template Conventions](template-conventions.md)
- [Interview UI Guidelines](interview-ui-guidelines.md)
