"""Turns a settings spec into GTK controls, for both the sidebar's settings and a plugin's own."""

from gi.repository import Gtk


def build_control(store, key, kind, detail, on_change):
    """Returns the control for one setting, already wired to write back to the store."""
    value = store.get(key)

    def changed(new):
        if store.get(key) == new:
            return
        store[key] = new
        on_change(key)

    if kind == "switch":
        widget = Gtk.Switch(halign=Gtk.Align.END, valign=Gtk.Align.CENTER)
        widget.set_active(bool(value))
        widget.connect("notify::active", lambda w, _p: changed(w.get_active()))
        return widget

    if kind == "combo":
        widget = Gtk.ComboBoxText()
        for ident, label in detail:
            widget.append(ident, label)
        widget.set_active_id(str(value))
        widget.connect("changed", lambda w: changed(w.get_active_id()))
        return widget

    if kind == "spin":
        low, high, step = detail
        widget = Gtk.SpinButton.new_with_range(low, high, step)
        widget.set_value(float(value or 0))
        widget.connect("value-changed", lambda w: changed(int(w.get_value())))
        return widget

    if kind == "scale":
        low, high, step = detail
        widget = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, low, high, step)
        widget.set_size_request(200, -1)
        widget.set_value(float(value or 0))
        widget.set_digits(2)
        widget.connect("value-changed", lambda w: changed(round(w.get_value(), 2)))
        return widget

    if kind == "font":
        widget = Gtk.FontButton()
        widget.set_font(str(value or "Sans 11"))
        widget.connect("font-set", lambda w: changed(w.get_font()))
        return widget

    widget = Gtk.Entry()
    widget.set_text(str(value or ""))
    widget.set_width_chars(22)
    # Text only takes effect once you finish typing it, never mid-keystroke.
    widget.connect("activate", lambda w: changed(w.get_text()))
    widget.connect("focus-out-event", lambda w, _e: changed(w.get_text()))
    return widget


def build_group(title, rows, store, on_change):
    """Returns (widget, controls) for one titled group of settings."""
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    if title:
        heading = Gtk.Label(xalign=0.0)
        heading.set_markup("<b>%s</b>" % title)
        box.pack_start(heading, False, False, 0)

    grid = Gtk.Grid(column_spacing=12, row_spacing=8)
    box.pack_start(grid, False, False, 0)

    controls = {}
    for index, (key, label, kind, detail) in enumerate(rows):
        caption = Gtk.Label(label=label, xalign=0.0)
        caption.set_hexpand(True)
        caption.set_line_wrap(True)
        grid.attach(caption, 0, index, 1, 1)
        control = build_control(store, key, kind, detail, on_change)
        grid.attach(control, 1, index, 1, 1)
        controls[key] = (caption, control)
    return box, controls


def build_spec(spec, store, on_change):
    """Returns (widget, controls) for a whole settings spec of titled groups."""
    column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
    controls = {}
    for title, rows in spec:
        group, found = build_group(title, rows, store, on_change)
        column.pack_start(group, False, False, 0)
        controls.update(found)
    return column, controls


def set_row_sensitive(controls, key, sensitive):
    """Greys out both the label and the control of one setting."""
    for widget in controls.get(key, ()):
        widget.set_sensitive(sensitive)
