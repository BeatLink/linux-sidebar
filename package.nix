{
    lib,
    stdenvNoCC,
    python3,
    gtk3,
    gtk-layer-shell,
    webkitgtk_4_1,
    libsoup_3,
    gobject-introspection,
    wrapGAppsHook3,
    wl-clipboard,
    xclip,
    hunspell,
    hunspellDicts,
}:

let
    python = python3.withPackages (ps: [
        ps.pygobject3
        ps.pycairo
        ps.xlib
    ]);
in
stdenvNoCC.mkDerivation {
    pname = "linux-sidebar";
    version = "2.0.0";

    src = ./.;

    nativeBuildInputs = [
        wrapGAppsHook3
        gobject-introspection
    ];

    # Everything here is reached through introspection at runtime rather than linked, so it
    # has to be on GI_TYPELIB_PATH; gobject-introspection's setup hook handles that.
    buildInputs = [
        gtk3
        gtk-layer-shell
        webkitgtk_4_1
        libsoup_3
        python
    ];

    dontBuild = true;

    # xclip and wl-clipboard are the fallbacks for compositors that do not offer a docked
    # surface the clipboard selection, and hunspell is what WebKit spell checks against.
    preFixup = ''
        gappsWrapperArgs+=(
            --prefix PATH : ${lib.makeBinPath [ wl-clipboard xclip ]}
            --prefix DICPATH : ${hunspellDicts.en_US}/share/hunspell
            --prefix LD_LIBRARY_PATH : ${lib.makeLibraryPath [ hunspell ]}
        )
    '';

    installPhase = ''
        runHook preInstall

        mkdir -p $out/share/linux-sidebar
        cp -r linux_sidebar $out/share/linux-sidebar/
        cp -r vendor $out/share/linux-sidebar/
        install -Dm644 style.css $out/share/linux-sidebar/style.css
        install -Dm644 shell.css $out/share/linux-sidebar/shell.css

        install -Dm755 linux-sidebar $out/bin/linux-sidebar
        substituteInPlace $out/bin/linux-sidebar \
            --replace-fail 'os.path.dirname(os.path.abspath(__file__))' \
                           "'$out/share/linux-sidebar'"

        install -Dm644 linux-sidebar.desktop $out/share/applications/linux-sidebar.desktop

        runHook postInstall
    '';

    meta = {
        description = "A docked sidebar of plugins for any Linux desktop";
        longDescription = ''
            A full-height strip docked to the edge of the screen, holding tabs of plugins.
            It docks through wlr-layer-shell on Wayland, through an EWMH strut on X11, and
            falls back to an always-on-top window where neither is available. The note
            plugin is a CKEditor 5 instance whose note is stored as HTML or Markdown.
        '';
        homepage = "https://github.com/BeatLink/linux-sidebar";
        license = lib.licenses.gpl3Plus;
        platforms = lib.platforms.linux;
        mainProgram = "linux-sidebar";
    };
}
