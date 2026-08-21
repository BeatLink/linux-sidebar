{
    description = "A full-height note scratchpad docked to the side of the screen";

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
                    sidebar-scratchpad = pkgs.callPackage ./package.nix { };
                    default = self.packages.${system}.sidebar-scratchpad;
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
                            pkgs.gobject-introspection
                            (pkgs.python3.withPackages (ps: [
                                ps.pygobject3
                                ps.pycairo
                            ]))
                        ];
                    };
                }
            );

            homeManagerModules = {
                sidebar-scratchpad = import ./home-manager.nix self;
                default = self.homeManagerModules.sidebar-scratchpad;
            };

            formatter = forAllSystems (system: (pkgsFor system).nixfmt-tree);
        };
}
