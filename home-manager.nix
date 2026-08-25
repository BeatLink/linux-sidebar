self:
{
    config,
    lib,
    pkgs,
    ...
}:

let
    cfg = config.programs.linux-sidebar;
in
{
    options.programs.linux-sidebar = {
        enable = lib.mkEnableOption "the sidebar, a docked strip of plugins";

        package = lib.mkOption {
            type = lib.types.package;
            default = self.packages.${pkgs.stdenv.hostPlatform.system}.linux-sidebar;
            defaultText = lib.literalMD "the `linux-sidebar` package from this flake";
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

        xdg.configFile."autostart/linux-sidebar.desktop" = lib.mkIf cfg.autostart {
            source = "${cfg.package}/share/applications/linux-sidebar.desktop";
        };

        # The settings, the layout and the notes all live in ~/.config/linux-sidebar and are
        # written by the app, so none of them is managed here: a store symlink would be
        # read-only and the settings window could not save. Persist that directory instead.
    };
}
