# Sidebar Scratchpad

A full-height note scratchpad docked to the side of the screen. It is a real dock: a
wlr-layer-shell surface that the compositor anchors to the edge and whose exclusive zone it
keeps clear, so windows cannot occupy the strip in the first place.

## Requirements

A Wayland session whose compositor implements `zwlr_layer_shell_v1`. Cinnamon's Muffin advertises
it (version 4), so Cinnamon on Wayland works. **X11 sessions cannot run this** — layer-shell does
not exist there, and the app exits with a message rather than opening an undockable window.

Dependencies are GTK 3, `gtk-layer-shell`, PyGObject, pycairo, `xclip` and `wl-clipboard`.

### With Nix

    nix run github:BeatLink/sidebar-scratchpad

As a flake input, with the Home Manager module:

```nix
{
    inputs.sidebar-scratchpad.url = "github:BeatLink/sidebar-scratchpad";

    # ...where the Home Manager modules are collected:
    sharedModules = [ inputs.sidebar-scratchpad.homeManagerModules.default ];
}
```

```nix
programs.sidebar-scratchpad = {
    enable = true;
    autostart = true;    # writes the autostart entry; on by default
};
```

The settings file and the note both live in `~/.config/sidebar-scratchpad` and are written by the
app, so the module deliberately does not manage them: a store symlink would be read-only and the
settings window could not save. Persist that directory if the home directory is not persistent.

### Without Nix

Install the dependencies through your package manager and run `sidebar_scratchpad.py`. `run.sh`
runs it through `nix-shell` for development, and `nix develop` gives the same environment.

## Autostart

Copy the desktop entry, editing `Exec=` if the project lives somewhere else:

    cp sidebar-scratchpad.desktop ~/.config/autostart/

## Controls

- **Click the note** to type in it. The surface uses layer-shell's on-demand keyboard mode, so it
  takes focus when you click it and never steals it otherwise.
- **Escape** hands the keyboard straight back to the window underneath.
- **Ctrl+S** saves immediately; otherwise the note saves shortly after you stop typing.
- **Tab** indents inside the note.
- **Ctrl+C**, **Ctrl+X** and **Ctrl+V** cut, copy and paste.

Clipboard keys are handled by the app rather than by GTK, and go through `xclip` rather than
`wl-clipboard`. Muffin offers no clipboard selection to layer-shell surfaces, so GTK's own paste
finds nothing to read, and it implements no data-control protocol, so `wl-paste` and `wl-copy` have
to open a surface and take the keyboard to reach the selection at all — which hands focus to the
previously focused window when they exit. An X11 client reaches the same selection, which Muffin
bridges, over the X protocol and never touches Wayland focus. `wl-clipboard` remains as a fallback
where there is no X server, with the focus jump as its cost.

Drag and drop is a separate protocol and works normally.

Right-click opens the same actions as a menu. It is drawn as an overlay widget inside the sidebar
rather than as a menu or a popover, because anything in its own surface is placed by the compositor
as though the sidebar were an ordinary window: a `GtkMenu` opened well off the sidebar, and a
`GtkPopover` reported itself visible and correctly sized while never appearing at all.

The footer shows the word and character count, reads `- unsaved` from the moment you type until the
write lands, then flashes **Saved**. The gear button beside it opens the settings.

### A shortcut for showing and hiding

The app cannot grab a global hotkey for itself — on Wayland only the compositor can, so the settings
window has no shortcut capture. Its **Keyboard shortcuts** section hands you the command to bind,
with a copy button and a link through to Cinnamon's keyboard settings. Bind it under
*System Settings → Keyboard → Shortcuts → Custom Shortcuts*:

    /Storage/Files/Projects/Coding/Note Sidebar/sidebar-scratchpad/run.sh --toggle

A second launch talks to the running instance rather than starting another. The same applies to
`--show`, `--hide`, `--settings`, `--reload` (reread the settings file) and `--quit`.

## Settings

Use the gear button in the footer, or `./run.sh --settings`. Every change applies immediately and is
written straight to the settings file; there is nothing to confirm. The window is an ordinary
toplevel rather than a layer-shell surface, so the window manager focuses and decorates it like any
other dialog.

The same settings live in `~/.config/sidebar-scratchpad/config.json` if you would rather edit them
by hand; apply those changes with `./run.sh --reload`. New settings are added to the file as they
appear, so it always lists everything available.

| Key | Default | Meaning |
| --- | --- | --- |
| `side` | `"right"` | Which edge to dock to, `left` or `right` |
| `width` | `360` | Width of the strip in pixels |
| `monitor` | `-1` | Monitor index, or -1 for wherever the compositor puts it |
| `reserve_space` | `true` | Claim an exclusive zone so windows keep out |
| `layer` | `"auto"` | Which layer-shell layer to sit on: `auto`, `bottom` or `top` |
| `margin_top` | `0` | Space held clear at the top edge, in pixels |
| `margin_bottom` | `0` | Space held clear at the bottom edge, in pixels |
| `font_size` | `11` | Note font size in points |
| `monospace` | `false` | Use a monospace font |
| `opacity` | `1.0` | Whole-window opacity |
| `show_counter` | `true` | Show the word and character count |
| `hot_corner_gap` | `24` | Size of the corner squares cut out of the input region |
| `start_hidden` | `false` | Start without showing the sidebar |
| `autosave_delay` | `800` | Milliseconds of idle before a save |
| `reload_interval` | `0` | Seconds between rereads, 0 to never |

With `reserve_space` off the sidebar still floats above the desktop, but windows may sit under it.

### Layers and margins

Cinnamon's panels are not layer-shell surfaces at all. They are shell chrome, Clutter actors inside
the Cinnamon process, stacked above the window group. Muffin composites a layer-shell `top` surface
above that chrome and a `bottom` one below ordinary windows, and there is no layer in between. That
is unfortunate, because "above windows, below the panels" is exactly where a dock belongs.

So neither layer is free:

- `top` draws above everything, which is what a dock wants, but also above the panels. An auto-hide
  panel reserves no space of its own, so it appears underneath the sidebar and looks clipped.
- `bottom` lets the panels draw over the sidebar, but any window that ignores the exclusive zone
  then covers it. The usual offender is a window that was already maximised when the sidebar
  started: it keeps its old full-width geometry until something re-maximises it.

`auto` chooses `bottom` whenever the sidebar reserves space, and that is usually what you want: the
panels slide over the sidebar by themselves, so an auto-hide panel is handled without the sidebar
having to watch for it or hold a permanent gap open for it. The exclusive zone still keeps windows
out, so being on the lower layer costs nothing.

The one artifact is windows that were already maximised when the sidebar started. They keep their
old full-width geometry and so overlap the strip until they are re-maximised; windows maximised
afterwards fit the reserved area correctly. Autostarting the sidebar at login avoids it entirely,
since nothing is maximised yet when it claims its zone.

`margin_top` and `margin_bottom` exist for the `top` layer, where the sidebar would otherwise cover
the panels: set one to a panel's height and the sidebar stops short of it, shrinking the reserved
strip to match.

### Hot corners

A full-height strip covers the screen corners, and hot corners sit underneath it. `hot_corner_gap`
cuts a square of that size out of each end of the input region so the pointer reaches them; the
trade is that the very corners of the note are not clickable. Set it to `0` to take the whole strip.

## Storage

By default the note is a plain text file at `~/.config/sidebar-scratchpad/scratchpad.txt`. It is
written through a temporary file and renamed, so an interrupted save cannot truncate it.

An empty note is only ever written if you emptied it yourself. Otherwise a failed read would leave
the sidebar blank and the save on exit would then wipe the stored note, which matters most with the
command backend, where the store is somewhere you cannot easily recover from.

Setting `storage_backend` to `"command"` replaces the file with a pair of shell commands, which lets
the note live anywhere:

- `read_command` runs through `bash -c` and its standard output becomes the note text;
- `write_command` runs through `bash -c` and receives the note text on standard input.

Both run asynchronously, so a slow command never freezes the sidebar. A failing command logs its
standard error and says so in the footer, leaving the text on screen alone.

| Store | `read_command` | `write_command` |
| --- | --- | --- |
| A file on another host | `ssh box cat notes.txt` | `ssh box 'cat > notes.txt'` |
| A password store entry | `pass show notes` | `pass insert -m -f notes` |
| An encrypted file | `gpg -dq ~/notes.gpg` | `gpg -e -r me -o ~/notes.gpg --yes` |
| A REST API | `curl -s $URL/note` | `curl -s -X PUT --data-binary @- $URL/note` |

`reload_interval` polls the store on a timer so edits made elsewhere appear on their own. A poll
never overwrites text while the note has focus.

## Files

| File | Purpose |
| --- | --- |
| `sidebar_scratchpad.py` | The application |
| `style.css` | Shape only; colours come from the GTK theme |
| `run.sh` | Runs it with dependencies from nix |
| `sidebar-scratchpad.desktop` | Autostart entry |
| `flake.nix` | Package, Home Manager module and dev shell |
| `package.nix` | The derivation |
| `home-manager.nix` | The Home Manager module |

## The Cinnamon extension

This started as a Cinnamon extension, kept in `../cinnamon-spices-extensions/`. It works, but the
desktop is not a window: it had to take a modal input grab to type, which swallowed shortcuts and
made leaving the note a two-click affair, and it could only approximate a dock by setting a strut
and shoving overlapping windows back out. Layer-shell gives real focus and true space reservation,
which is why this replaced it.
