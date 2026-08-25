{
    description = "A docked sidebar of plugins for any Linux desktop";

    inputs = {
        nixpkgs = {
            url = "github:NixOS/nixpkgs/nixos-unstable";
        };
    };

    outputs =
        { self, nixpkgs }:
        let
            systems = [
                "x86_64-linux"
                "aarch64-linux"
            ];
            forAllSystems = nixpkgs.lib.genAttrs systems;
            pkgsFor = system: nixpkgs.legacyPackages.${system};
        in
        {
            packages = forAllSystems (
                system:
                let
                    pkgs = pkgsFor system;
                in
                {
                    linux-sidebar = pkgs.callPackage ./package.nix { };
                    default = self.packages.${system}.linux-sidebar;
                }
            );

            # A shell for hacking on the script directly, without building it first.
            devShells = forAllSystems (
                system:
                let
                    pkgs = pkgsFor system;
                in
                {
                    default = pkgs.mkShell {
                        packages = [
                            pkgs.gtk3
                            pkgs.gtk-layer-shell
                            pkgs.webkitgtk_4_1
                            pkgs.libsoup_3
                            pkgs.gobject-introspection
                            pkgs.wl-clipboard
                            pkgs.xclip
                            pkgs.hunspell
                            pkgs.hunspellDicts.en_US
                            (pkgs.python3.withPackages (ps: [
                                ps.pygobject3
                                ps.pycairo
                                ps.xlib
                            ]))
                        ];
                    };
                }
            );

            homeManagerModules = {
                linux-sidebar = import ./home-manager.nix self;
                default = self.homeManagerModules.linux-sidebar;
            };

            formatter = forAllSystems (system: (pkgsFor system).nixfmt-tree);
        };
}
