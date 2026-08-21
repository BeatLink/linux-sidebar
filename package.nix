{
    lib,
    stdenvNoCC,
    python3,
    gtk3,
    gtk-layer-shell,
    gobject-introspection,
    wrapGAppsHook3,
    wl-clipboard,
    xclip,
}:

let
    python = python3.withPackages (ps: [
        ps.pygobject3
        ps.pycairo
    ]);
in
stdenvNoCC.mkDerivation {
    pname = "sidebar-scratchpad";
    version = "1.0.0";

    src = ./.;

    nativeBuildInputs = [
        wrapGAppsHook3
        gobject-introspection
    ];

    # gtk-layer-shell is reached through introspection at runtime, so it has to be on
    # GI_TYPELIB_PATH rather than linked; gobject-introspection's hook handles that.
    buildInputs = [
        gtk3
        gtk-layer-shell
        python
    ];

    dontBuild = true;

    # Cut, copy and paste go through wl-clipboard, since the compositor does not offer
    # the clipboard selection to layer-shell surfaces.
    preFixup = ''
        gappsWrapperArgs+=(--prefix PATH : ${lib.makeBinPath [ wl-clipboard xclip ]})
    '';

    installPhase = ''
        runHook preInstall

        install -Dm755 sidebar_scratchpad.py $out/bin/sidebar-scratchpad
        install -Dm644 style.css $out/share/sidebar-scratchpad/style.css
        install -Dm644 sidebar-scratchpad.desktop \
            $out/share/applications/sidebar-scratchpad.desktop

        runHook postInstall
    '';

    meta = {
        description = "A full-height note scratchpad docked to the side of the screen";
        longDescription = ''
            A wlr-layer-shell surface anchored to the edge of the screen, whose exclusive
            zone the compositor keeps clear of windows. The note is stored either in a
            plain text file or through a pair of user commands. Requires a Wayland
            compositor implementing zwlr_layer_shell_v1.
        '';
        homepage = "https://github.com/BeatLink/sidebar-scratchpad";
        license = lib.licenses.gpl3Plus;
        platforms = lib.platforms.linux;
        mainProgram = "sidebar-scratchpad";
    };
}
