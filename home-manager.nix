self:
{
    config,
    lib,
    pkgs,
    ...
}:

let
    cfg = config.programs.sidebar-scratchpad;
in
{
    options.programs.sidebar-scratchpad = {
        enable = lib.mkEnableOption "the sidebar scratchpad, a docked note pane";

        package = lib.mkOption {
            type = lib.types.package;
            default = self.packages.${pkgs.stdenv.hostPlatform.system}.sidebar-scratchpad;
            defaultText = lib.literalMD "the `sidebar-scratchpad` package from this flake";
            description = "The package providing the sidebar.";
        };

        autostart = lib.mkOption {
            type = lib.types.bool;
            default = true;
            description = "Start the sidebar when the session begins.";
        };
    };

    config = lib.mkIf cfg.enable {
        home.packages = [ cfg.package ];

        xdg.configFile."autostart/sidebar-scratchpad.desktop" = lib.mkIf cfg.autostart {
            source = "${cfg.package}/share/applications/sidebar-scratchpad.desktop";
        };

        # The settings and the note itself both live in ~/.config/sidebar-scratchpad and are
        # written by the app, so neither is managed here: a store symlink would be read-only
        # and the settings window could not save. Persist that directory instead.
    };
}
