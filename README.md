# Linux Sidebar

A full-height strip docked to the edge of the screen, holding tabs of plugins. It is a real
dock: the compositor or the window manager keeps its space clear, so windows cannot occupy the
strip in the first place.

The plugin that comes with it is a note, edited in [CKEditor 5](https://ckeditor.com/ckeditor-5/)
and saved as you type.

## Docking

The sidebar picks the best way to dock that the session offers, and says which it chose in the
settings window and on standard error at startup.

| Backend | Used on | Reserves space |
| --- | --- | --- |
| Wayland layer shell | Any compositor implementing `zwlr_layer_shell_v1`: Cinnamon's Muffin, KWin, wlroots, COSMIC | Yes, through an exclusive zone |
| X11 dock | Any EWMH window manager: Xfwm, Metacity, Muffin, KWin, Openbox, i3 | Yes, through `_NET_WM_STRUT_PARTIAL` |
| Plain window | Anything else, GNOME's Wayland session in particular | No |

Set `dock_backend` to pin one rather than letting it choose.

### On X11

The strut needs `python-xlib`. Without it the sidebar still docks, but windows may sit under it.

`x11_window_type` decides which EWMH type the window claims. `normal` is the default because
every window manager lets you type into a normal window, while some refuse the keyboard to a
`dock`. Choose `dock` if you would rather it stacked strictly like a panel and your window
manager focuses docks.

### On Wayland

Layer-shell has no layer meaning "above windows but below the shell's own panels", which is
exactly where a dock belongs, so neither layer is free:

- `top` draws above everything, including the panels. An auto-hide panel reserves no space of
  its own, so it appears underneath the sidebar and looks clipped.
- `bottom` lets the panels draw over the sidebar, but any window that ignores the exclusive
  zone then covers it. The usual offender is a window that was already maximised when the
  sidebar started.

`layer` defaults to `auto`, which picks `bottom` whenever the sidebar reserves space. The
panels then slide over the sidebar by themselves and the exclusive zone still keeps windows
out, so being on the lower layer costs nothing. `margin_top` and `margin_bottom` exist for the
`top` layer: set one to a panel's height and the sidebar stops short of it.

## Installing

### With Nix

    nix run github:BeatLink/linux-sidebar

As a flake input, with the Home Manager module:

```nix
{
    inputs.linux-sidebar.url = "github:BeatLink/linux-sidebar";

    # ...where the Home Manager modules are collected:
    sharedModules = [ inputs.linux-sidebar.homeManagerModules.default ];
}
```

```nix
programs.linux-sidebar = {
    enable = true;
    autostart = true;    # writes the autostart entry; on by default
};
```

The settings, the layout and the notes all live in `~/.config/linux-sidebar` and are written by
the app, so the module deliberately does not manage them: a store symlink would be read-only
and the settings window could not save. Persist that directory if the home directory is not
persistent.

### Without Nix

The dependencies are GTK 3, PyGObject, pycairo and, for each thing they enable:

| Dependency | Without it |
| --- | --- |
| `gtk-layer-shell` | No layer-shell docking on Wayland |
| `python-xlib` | No space reservation on X11 |
| `webkitgtk` 4.1 | The note falls back to a plain text view of its source |
| `libsoup` 3 | The Trilium plugin cannot reach its server |
| `hunspell` and a dictionary | No spell checking in the note |
| `xclip` or `wl-clipboard` | No clipboard where the compositor withholds it from a docked surface |

Then run `./linux-sidebar`. `run.sh` runs it through `nix-shell` for development, and
`nix develop` gives the same environment.

## Tabs and plugins

The sidebar holds tabs, and each tab holds a stack of plugins. A plugin section can be folded
away by clicking its header, and stays folded until you unfold it again.

Build the layout under **Tabs and plugins** in the settings: add and remove tabs, add plugins to
a tab, reorder either, and open a plugin's own settings underneath its row. A plugin marked as
filling the tab, which the note is, takes whatever height the sections above and below it leave.

The tab bar appears once there is more than one tab. **Ctrl+Tab** and **Ctrl+Shift+Tab** move
between them, as do `--next-tab` and `--previous-tab`.

Five plugins are built in:

| Plugin | What it is |
| --- | --- |
| `note` | A rich text note, edited in CKEditor 5 |
| `trilium` | The same editor, over a note kept in [Trilium](https://github.com/TriliumNext/Trilium) |
| `clock` | The time and the date, in whatever `strftime` format you give it |
| `command` | The standard output of a shell command, rerun on a timer |
| `timer` | A countdown with presets, which runs a command of your choosing at zero |

### Writing one

Drop a `.py` file, or a directory with an `__init__.py`, into
`~/.config/linux-sidebar/plugins/`. It has to name its class `PLUGIN`:

```python
from gi.repository import Gtk
from linux_sidebar.plugins.api import SidebarPlugin


class HelloPlugin(SidebarPlugin):
    id = "hello"
    title = "Hello"
    icon = "face-smile-symbolic"
    settings_spec = [("Hello", [("who", "Greet", "entry", None)])]
    defaults = {"who": "world"}

    def build(self):
        self.label = Gtk.Label()
        return self.label

    def start(self):
        self.settings_changed()

    def settings_changed(self):
        self.label.set_text("Hello, %s" % self.settings["who"])


PLUGIN = HelloPlugin
```

`build` returns the section's widget. `start`, `flush`, `reload`, `settings_changed` and `stop`
are the lifecycle, and `self.host` reaches the sidebar: `host.settings` is this instance's own
persisted settings, `host.set_status` writes to the footer, `host.flash` puts a message there
for a moment, and `host.clipboard` is the clipboard set up for the docking backend in use. A
plugin that raises is reported and skipped rather than taking the sidebar down.

Each entry in `settings_spec` is `(key, label, kind, detail)`, where `kind` is `switch`,
`combo`, `spin`, `scale`, `font` or an entry, and `detail` is the choices for a combo or the
`(minimum, maximum, step)` for a spin button or a scale.

## The note

The note is a CKEditor 5 instance in a WebKitGTK view, themed from the desktop's own GTK
colours and font. Headings, lists, todo lists, tables, code blocks, links, find and replace and
a source view are all there; the toolbar collapses into an overflow menu at narrow widths, and
`toolbar` trims it to `compact` or hides it.

### What it is stored as

`note_format` is `html` by default, which loses nothing CKEditor can express. Set it to
`markdown` and the note is stored as GitHub-flavoured Markdown instead: readable, diffable and
safe to keep in git, at the cost of anything Markdown cannot say. Changing it rebuilds the
editor.

A note with no tags in it is read as plain text and its blank lines become paragraphs, so a
plain text file from somewhere else opens sensibly.

By default the note is a file in `~/.config/linux-sidebar`, named after its plugin instance and
its format. It is written through a temporary file and renamed, so an interrupted save cannot
truncate it. An empty note is only ever written if you emptied it yourself: until the stored
note has reached the editor, nothing the editor holds is saved, so a failed read cannot lead to
the note being wiped.

Setting `storage_backend` to `command` replaces the file with a pair of shell commands, which
lets the note live anywhere:

- `read_command` runs through `sh -c` and its standard output becomes the note;
- `write_command` runs through `sh -c` and receives the note on standard input.

Both run asynchronously, so a slow command never freezes the sidebar. A failing command logs its
standard error and says so in the footer, leaving the note on screen alone.

| Store | `read_command` | `write_command` |
| --- | --- | --- |
| A file on another host | `ssh box cat notes.md` | `ssh box 'cat > notes.md'` |
| A password store entry | `pass show notes` | `pass insert -m -f notes` |
| An encrypted file | `gpg -dq ~/notes.gpg` | `gpg -e -r me -o ~/notes.gpg --yes` |
| A REST API | `curl -s $URL/note` | `curl -s -X PUT --data-binary @- $URL/note` |

`reload_interval` polls the store on a timer so edits made elsewhere appear on their own. A poll
never overwrites a note with unsaved edits in it.

### Controls

- **Click the note** to type in it. Under layer-shell the surface takes focus when you click it
  and never steals it otherwise.
- **Escape** hands the keyboard back to the window underneath.
- **Ctrl+S** saves immediately; otherwise the note saves shortly after you stop typing.
- **Ctrl+C**, **Ctrl+X** and **Ctrl+V** cut, copy and paste.

Right-click opens the same actions, drawn inside the page. Anything in its own surface — a menu,
a popover — is placed by the compositor as though the sidebar were an ordinary window, and lands
off the sidebar entirely.

Clipboard keys are handled by the sidebar rather than by the editor. Muffin offers no clipboard
selection to layer-shell surfaces, so the page's own cut, copy and paste have nothing to read.
The sidebar reaches it through `xclip` where there is an X server, since Muffin bridges the X
selection and an X client never touches Wayland focus, and through `wl-clipboard` otherwise.
Where the session hands a docked surface the clipboard normally, GTK's own is used and no helper
is needed; the settings window says which it is using. Drag and drop is a separate protocol and
works normally.

## Trilium

The `trilium` plugin is the same editor over a note that lives in Trilium, reached through
ETAPI. A Trilium text note is HTML and so is this editor's output, so the same note can be
edited from either end and neither has to convert anything.

ETAPI offers no way to push a change to a client, so the sidebar polls: every `poll_interval`
seconds it reads the note's metadata, which is cheap, and only fetches the content once the
note's blob has actually moved. An edit made in Trilium therefore turns up here on its own,
within one poll. A poll never overwrites a note with unsaved edits in it, and the revision a
save produces is recorded, so the sidebar never mistakes its own write for somebody else's.

| Key | Default | Meaning |
| --- | --- | --- |
| `server_url` | `http://localhost:37840` | Where Trilium is |
| `note_id` | `root` | Which note to edit; copy the id from Trilium's note info |
| `token` | empty | An ETAPI token, made under *Options → ETAPI* |
| `token_command` | empty | A command printing the token, for a secret you would rather not keep here |
| `poll_interval` | `15` | Seconds between checks, 0 to never check |
| `title_in_header` | `true` | Put Trilium's own title in the section header |
| `allow_insecure_tls` | `false` | Accept a certificate from a private authority |

`token_command` is the one to use where the token is already managed: `cat
/run/secrets/trilium_etapi_token`, `pass show trilium/etapi` and so on. It runs once and the
token is kept for the session.

This needs `libsoup` 3. Without it the plugin loads but every request fails and says so.

## The timer

A countdown, with a row of preset lengths above **Start** and **Reset**. A preset restarts the
countdown at that length straight away; **Start** uses the configured length, and becomes
**Pause**, which keeps the time that is left.

| Setting | Default | What it does |
| --- | --- | --- |
| `duration` | `25` | The length **Start** and **Reset** use, in minutes |
| `presets` | `5, 10, 25` | The preset buttons, as a comma separated list of minutes, up to six |
| `count_in_title` | on | Shows the time left beside the section's title, so a folded timer still counts |
| `alert_command` | `notify-send "Timer" "Time is up"` | Run through `sh -c` when the countdown reaches zero |
| `alert_message` | `The timer finished` | Shown in the footer for a moment at zero, or blank for nothing |

The countdown is kept against the monotonic clock rather than counted in ticks, so it still
finishes on time after the sidebar has been hidden or the machine has been busy. It does not
survive quitting: a timer that was running starts again at its full length next time.

## Settings

Use the gear button in the footer, or `linux-sidebar --settings`. Every change applies
immediately and is written straight to the settings file; there is nothing to confirm. The
window is an ordinary toplevel rather than a docked surface, so the window manager focuses and
decorates it like any other dialog.

The same settings live in `~/.config/linux-sidebar/config.json` if you would rather edit them by
hand; apply those changes with `linux-sidebar --reload`.

| Key | Default | Meaning |
| --- | --- | --- |
| `side` | `"right"` | Which edge to dock to, `left` or `right` |
| `width` | `380` | Width of the strip in pixels |
| `monitor` | `-1` | Monitor index, or -1 for the one the pointer is on |
| `dock_backend` | `"auto"` | `auto`, `layer-shell`, `x11` or `plain` |
| `x11_window_type` | `"normal"` | EWMH window type on X11, `normal` or `dock` |
| `reserve_space` | `true` | Claim the strip so windows keep out |
| `layer` | `"auto"` | Layer-shell layer: `auto`, `bottom` or `top` |
| `margin_top` | `0` | Space held clear at the top edge, in pixels |
| `margin_bottom` | `0` | Space held clear at the bottom edge, in pixels |
| `opacity` | `1.0` | Whole-window opacity |
| `hot_corner_gap` | `24` | Size of the corner squares cut out of the input region |
| `start_hidden` | `false` | Start without showing the sidebar |
| `show_status` | `true` | Show the footer's status line |
| `tab_position` | `"top"` | `top`, `bottom` or `hidden` |
| `tabs` | one note | The layout, which the settings window edits |

A full-height strip covers the screen corners, and hot corners sit underneath it.
`hot_corner_gap` cuts a square of that size out of each end of the input region so the pointer
reaches them; the trade is that the very corners of the sidebar are not clickable. Set it to `0`
to take the whole strip.

## A shortcut for showing and hiding

The sidebar cannot grab a global hotkey for itself: a global shortcut belongs to the desktop.
The settings window's **Shortcuts** page hands you each command with a copy button, and a link
through to whichever keyboard settings this desktop provides.

| Command | What it does |
| --- | --- |
| `--toggle` | Show or hide the sidebar |
| `--show`, `--hide` | Show or hide it |
| `--next-tab`, `--previous-tab` | Move between tabs |
| `--settings` | Open the settings window |
| `--reload` | Reread the settings file |
| `--quit` | Save and exit |

A second launch talks to the running instance rather than starting another.

## Files

| File | Purpose |
| --- | --- |
| `linux-sidebar` | The launcher |
| `linux_sidebar/app.py` | The application and its command line |
| `linux_sidebar/config.py` | The settings file and the layout |
| `linux_sidebar/net.py` | Asynchronous HTTP, for plugins that talk to a server |
| `linux_sidebar/docking/` | One module per way of docking |
| `linux_sidebar/plugins/` | The plugin API, the registry and the built-in plugins |
| `linux_sidebar/ui/` | The sidebar window, its sections and the settings window |
| `vendor/ckeditor5/` | The CKEditor 5 build, vendored so nothing is fetched at runtime |
| `style.css` | Shape only; colours come from the GTK theme |
| `flake.nix`, `package.nix`, `home-manager.nix` | Packaging |

## Migrating from sidebar-scratchpad

The first launch reads `~/.config/sidebar-scratchpad/config.json` if it is there, and folds its
settings into the one note in the default layout and copying `scratchpad.txt` into that note's
own file, with its format set to Markdown so it stays readable. The note is copied rather than
pointed at, so nothing afterwards depends on the old directory, and nothing in it is changed or
removed.

## Licence

GPL-3.0-or-later. The vendored CKEditor 5 build in `vendor/ckeditor5/` is CKSource's, under the
GPL-2.0-or-later terms in `vendor/ckeditor5/LICENSE.md`, and the editor is configured with the
`GPL` licence key accordingly.
